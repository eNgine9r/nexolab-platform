#!/usr/bin/env python3
"""WP2c Stage 2 (#1734): guarded same-origin LAN dashboard activation, owner-run.

Runs on the production host as the operator account (docker group, never root).
The LAN dashboard is a stateless, frontend-only Compose service; this tool swaps
only its image and adds the server-only API origin, with automatic verified
rollback. It never touches volumes, networks, PostgreSQL, MQTT, the Edge or any
other service, and never uses --remove-orphans, ``down``, ``prune`` or ``-v``.

Modes (all state lives in --workspace, mode 0700):

  stage    verify the GitHub Actions artifact ZIP (streamed SHA-256), extract it
           safely, verify every artifact file and every runtime file hash, and
           require the same-origin LOCAL_LAN contract.
  build    build nexolab/dashboard:wp2c-stage2-<src12>-arm64 OFFLINE on the proven
           base of the CURRENT dashboard image (tar-streamed context, no pull,
           no cache, no network) and compare every /app file with the artifact.
  preview  derive candidate and rollback Compose files from ``docker inspect`` of
           the current dashboard (rollback = exact current config; candidate =
           new image + NEXOLAB_SERVER_API_BASE_URL), prove both reproduce the
           current container settings, then run the candidate as a preview on
           127.0.0.1:<port> and prove identity, routes and Docker DNS to the API.
  check    read-only preflight (no state-changing docker command).
  execute  switch with automatic verified rollback; JSON report (0600).
  rollback explicit verified rollback to the recorded previous configuration.

Markers: STAGE2_FRONTEND_GREEN, STAGE2_ROLLED_BACK_VERIFIED,
HARD_BLOCKER_ROLLBACK_UNVERIFIED, STOP <reason>.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_WORKSPACE = "/home/nexolab/commander-workspaces/nexolab-wp2c-stage2"
DEFAULT_LOCK = "/tmp/nexolab-current-head-launch.lock"
DEFAULT_BACKENDS = (
    "nexolab-central-postgres-1",
    "nexolab-central-mqtt-1",
    "nexolab-central-telemetry-service-1",
    "nexolab-edge-device-agent-1",
    "nexolab-central-minio-1",
)
DEFAULT_ROUTES = ("/", "/login", "/live", "/refrigeration")
PREVIEW_LABEL = "nexolab.wp2c.stage2"
FIDELITY_PROJECT = "nexolab-wp2c-stage2-fidelity"
SERVER_API_ENV = "NEXOLAB_SERVER_API_BASE_URL"
IDENTITY_SOURCE = "offline_image_manifest"
GIB = 1024**3
CHUNK = 4 * 1024 * 1024
DEFAULT_SHM = 64 * 1024 * 1024
POLL_SECONDS = 1.0

ARTIFACT_FILES = frozenset(
    {
        "frontend-runtime.tar.gz",
        "package.json",
        "package-lock.json",
        "frontend-source-sha.txt",
        "frontend-package-sha256.txt",
        "frontend-runtime-contract.txt",
        "frontend-platform.txt",
        "frontend-node-version.txt",
        "frontend-build-id.txt",
        "frontend-runtime-files-sha256.txt",
        "frontend-public-contract.txt",
        "frontend-native-files.txt",
        "frontend-artifact-sha256.txt",
    }
)
CONTRACT_KEYS = frozenset(
    {"runtime_mode", "api_base_url", "websocket_url", "auth_provider", "organization_id", "external_https_stage"}
)
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
BUILD_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# HostConfig settings that must stay at their Docker default for this stateless
# frontend; anything else is translated explicitly or proven by the fidelity check.
MUST_BE_EMPTY = (
    "Binds", "Mounts", "VolumesFrom", "Devices", "DeviceRequests", "DeviceCgroupRules",
    "Privileged", "PublishAllPorts", "PidMode", "UTSMode", "UsernsMode", "CgroupParent",
    "VolumeDriver", "AutoRemove", "Cgroup",
)
COMPARE_IGNORE_HOSTCONFIG = frozenset({"ContainerIDFile", "Links"})


class Stop(Exception):
    """Fail closed before or outside a production change."""


def need(condition: object, reason: str) -> None:
    if not condition:
        raise Stop(reason)


# ---------------------------------------------------------------- utilities


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def docker_env() -> dict[str, str]:
    """Inherited environment without Compose overrides that could redirect a command."""
    return {k: v for k, v in os.environ.items() if not k.startswith("COMPOSE_")}


def run(argv: list[str], timeout: int = 120, check: bool = True, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(argv, input=stdin, capture_output=True, timeout=timeout, check=False, env=docker_env())
    if check and result.returncode:
        raise Stop("COMMAND_FAILED " + " ".join(argv[:5]) + ": " + result.stderr.decode(errors="replace")[-400:])
    return result


def text(argv: list[str], timeout: int = 120) -> str:
    return run(argv, timeout=timeout).stdout.decode(errors="replace").strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def sha256_stream(handle) -> str:
    digest = hashlib.sha256()
    while block := handle.read(CHUNK):
        digest.update(block)
    return digest.hexdigest()


def free_bytes(path: Path) -> int:
    probe = path
    while not probe.exists():
        probe = probe.parent
    st = os.statvfs(probe)
    return st.f_bavail * st.f_frsize


def write_private(path: Path, data: str, exclusive: bool = False) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if exclusive:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(data)
        return
    tmp = path.with_name(f".{path.name}.tmp")
    if tmp.exists() or tmp.is_symlink():
        tmp.unlink()
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(data)
    os.replace(tmp, path)


def read_json(path: Path, reason: str) -> dict:
    need(path.is_file() and not path.is_symlink(), reason)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object, exclusive: bool = False) -> None:
    write_private(path, json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", exclusive=exclusive)


# ---------------------------------------------------------------- HTTP probes

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_get(url: str, timeout: float = 5.0) -> tuple[int, bytes]:
    try:
        with _OPENER.open(url, timeout=timeout) as response:
            return response.status, response.read(1024 * 1024)
    except urllib.error.HTTPError as error:
        return error.code, b""
    except Exception as error:  # noqa: BLE001 - every transport failure is a failed probe
        raise Stop(f"HTTP_UNAVAILABLE {url} {str(error)[:160]}") from error


def identity(base: str) -> dict:
    status, body = http_get(base.rstrip("/") + "/api/runtime-identity")
    need(status == 200, f"IDENTITY_HTTP_{status} {base}")
    try:
        return json.loads(body)
    except ValueError as error:
        raise Stop(f"IDENTITY_NOT_JSON {base}") from error


def probe(base: str, source: str, build: str, routes: tuple[str, ...]) -> dict:
    data = identity(base)
    need(
        data.get("source_commit") == source and data.get("build_id") == build
        and data.get("identity_source") == IDENTITY_SOURCE,
        f"IDENTITY_MISMATCH {base} expected={source[:12]}/{build} got={str(data)[:200]}",
    )
    for route in routes:
        status, _ = http_get(base.rstrip("/") + route)
        need(status == 200, f"ROUTE_FAILED {base}{route} status={status}")
    return data


def gateway_probe(gateway: str, source: str, build: str) -> None:
    status, _ = http_get(gateway.rstrip("/") + "/__nexolab_lan_gateway/health")
    need(status == 200, f"GATEWAY_HEALTH_{status}")
    status, _ = http_get(gateway.rstrip("/") + "/")
    need(status == 200, f"GATEWAY_ROOT_{status}")
    data = identity(gateway)
    need(
        data.get("source_commit") == source and data.get("build_id") == build,
        f"GATEWAY_IDENTITY_MISMATCH expected={source[:12]}/{build} got={str(data)[:200]}",
    )


# ---------------------------------------------------------------- docker reads


def inspect(name: str) -> dict:
    result = run(["docker", "inspect", "--type", "container", name], timeout=60, check=False)
    need(result.returncode == 0, "CONTAINER_NOT_FOUND " + name)
    return json.loads(result.stdout)[0]


def try_inspect(name: str) -> dict | None:
    result = run(["docker", "inspect", "--type", "container", name], timeout=60, check=False)
    return json.loads(result.stdout)[0] if result.returncode == 0 else None


def image_inspect(ref: str) -> dict:
    result = run(["docker", "image", "inspect", ref], timeout=60, check=False)
    need(result.returncode == 0, "IMAGE_NOT_FOUND " + ref)
    return json.loads(result.stdout)[0]


def health(container: dict) -> str:
    state = container.get("State") or {}
    if not state.get("Running"):
        return "not-running"
    return (state.get("Health") or {}).get("Status") or "running"


def published(container: dict) -> tuple[str, str, str]:
    """(host_ip, host_port, container_port) of the single configured publish."""
    bindings = (container.get("HostConfig") or {}).get("PortBindings") or {}
    entries = [(cport, b) for cport, items in bindings.items() for b in (items or [])]
    need(len(entries) == 1, f"EXPECTED_ONE_PORT_BINDING {container.get('Name')} {bindings}")
    cport, binding = entries[0]
    need(binding.get("HostPort"), "PORT_BINDING_WITHOUT_HOST_PORT")
    return binding.get("HostIp") or "", binding["HostPort"], cport


def local_url(container: dict) -> str:
    host, port, _ = published(container)
    host = "127.0.0.1" if host in ("", "0.0.0.0") else host
    host = f"[{host}]" if ":" in host else host
    return f"http://{host}:{port}"


def readiness_url(args: argparse.Namespace) -> str:
    if args.readiness_url:
        return args.readiness_url
    telemetry = [name for name in args.backend if "telemetry-service" in name]
    need(len(telemetry) == 1, "TELEMETRY_BACKEND_NOT_IDENTIFIED (pass --readiness-url)")
    return local_url(inspect(telemetry[0])) + "/health/ready"


def snapshots(backends: list[str]) -> dict:
    entries = {}
    for name in backends:
        data = inspect(name)
        state = data.get("State") or {}
        need(state.get("Running"), "BACKEND_NOT_RUNNING " + name)
        need(health(data) in ("healthy", "running"), f"BACKEND_UNHEALTHY {name} {health(data)}")
        entries[name] = {
            "container_id": data["Id"],
            "image_id": data["Image"],
            "started_at": state.get("StartedAt"),
            "restart_count": data.get("RestartCount", 0),
            "networks": sorted((data.get("NetworkSettings") or {}).get("Networks") or {}),
        }
    return entries


# ---------------------------------------------------------------- service model


def compose_labels(container: dict) -> dict:
    return {k: v for k, v in ((container.get("Config") or {}).get("Labels") or {}).items() if k.startswith("com.docker.compose.")}


def user_labels(container: dict, image: dict) -> dict:
    image_labels = (image.get("Config") or {}).get("Labels") or {}
    labels = (container.get("Config") or {}).get("Labels") or {}
    return {k: v for k, v in labels.items() if not k.startswith("com.docker.compose.") and image_labels.get(k) != v}


def duration(ns: int | None) -> str | None:
    return f"{int(ns) // 1_000_000}ms" if ns else None


def candidate_env(env: list[str], server_api: str) -> list[str]:
    out = []
    for item in env:
        key, _, value = item.partition("=")
        if key == SERVER_API_ENV:
            need(value == server_api, f"{SERVER_API_ENV}_ALREADY_SET_DIFFERENTLY {value}")
            continue
        out.append(item)
    return out + [f"{SERVER_API_ENV}={server_api}"]


def validate_current(container: dict, args: argparse.Namespace) -> None:
    labels = compose_labels(container)
    need(labels.get("com.docker.compose.project") == args.project, "COMPOSE_PROJECT_CHANGED")
    need(labels.get("com.docker.compose.service") == args.service, "COMPOSE_SERVICE_CHANGED")
    need(container["Name"].lstrip("/") == f"{args.project}-{args.service}-1", "UNEXPECTED_CONTAINER_NAME")
    need(not container.get("Mounts"), "DASHBOARD_NOT_STATELESS mounts present")
    networks = (container.get("NetworkSettings") or {}).get("Networks") or {}
    need(sorted(networks) == [args.network], f"DASHBOARD_NETWORKS_CHANGED {sorted(networks)}")
    published(container)


def service_model(container: dict, image: dict, args: argparse.Namespace) -> dict:
    """Compose service equivalent to the inspected container (fail closed on the unknown)."""
    cfg, host, img = container["Config"], container["HostConfig"], image.get("Config") or {}
    for key in MUST_BE_EMPTY:
        need(not host.get(key), f"UNSUPPORTED_CONTAINER_SETTING {key}={host.get(key)!r}")
    need(host.get("IpcMode") in (None, "", "private", "shareable"), f"UNSUPPORTED_CONTAINER_SETTING IpcMode={host.get('IpcMode')}")
    need(host.get("Runtime") in (None, "", "runc"), f"UNSUPPORTED_CONTAINER_SETTING Runtime={host.get('Runtime')}")
    need(host.get("NetworkMode") == args.network, f"UNSUPPORTED_NETWORK_MODE {host.get('NetworkMode')}")
    need(not (image.get("Config") or {}).get("Volumes"), "IMAGE_DECLARES_VOLUMES")

    svc: dict = {"image": cfg["Image"], "pull_policy": "never"}
    if cfg.get("User") != img.get("User"):
        svc["user"] = cfg.get("User") or ""
    if cfg.get("Entrypoint") != img.get("Entrypoint"):
        svc["entrypoint"] = cfg.get("Entrypoint") or []
    if cfg.get("Cmd") != img.get("Cmd"):
        svc["command"] = cfg.get("Cmd") or []
    if cfg.get("WorkingDir") != img.get("WorkingDir"):
        svc["working_dir"] = cfg.get("WorkingDir") or ""
    if cfg.get("StopSignal") and cfg.get("StopSignal") != img.get("StopSignal"):
        svc["stop_signal"] = cfg["StopSignal"]
    if cfg.get("StopTimeout") is not None:
        svc["stop_grace_period"] = f"{int(cfg['StopTimeout'])}s"
    if cfg.get("Tty"):
        svc["tty"] = True
    if cfg.get("OpenStdin"):
        svc["stdin_open"] = True
    env = list(cfg.get("Env") or [])
    for item in env:
        need(ENV_KEY.match(item.partition("=")[0]) and "\n" not in item, "UNSUPPORTED_ENV_ENTRY " + item.partition("=")[0])
    svc["environment"] = env
    labels = user_labels(container, image)
    if labels:
        svc["labels"] = labels
    extra_expose = sorted(set(cfg.get("ExposedPorts") or {}) - set(img.get("ExposedPorts") or {}) - set(host.get("PortBindings") or {}))
    if extra_expose:
        svc["expose"] = extra_expose
    hip, hport, cport = published(container)
    svc["ports"] = [f"{hip}:{hport}:{cport}" if hip else f"{hport}:{cport}"]
    endpoint = container["NetworkSettings"]["Networks"][args.network] or {}
    ipam = endpoint.get("IPAMConfig") or {}
    need(not ipam.get("IPv4Address") and not ipam.get("IPv6Address"), "UNSUPPORTED_STATIC_IP")
    auto = {args.service, container["Name"].lstrip("/"), container["Id"][:12]}
    aliases = sorted(a for a in (endpoint.get("Aliases") or []) if a not in auto)
    svc["networks"] = {args.network: {"aliases": aliases} if aliases else {}}
    restart = host.get("RestartPolicy") or {}
    if restart.get("Name") and restart["Name"] != "no":
        retries = restart.get("MaximumRetryCount") or 0
        svc["restart"] = f"on-failure:{retries}" if restart["Name"] == "on-failure" and retries else restart["Name"]
    else:
        svc["restart"] = "no"
    if host.get("Init"):
        svc["init"] = True
    hc = cfg.get("Healthcheck")
    if hc and hc.get("Test"):
        if hc["Test"] == ["NONE"]:
            svc["healthcheck"] = {"disable": True}
        else:
            block: dict = {"test": hc["Test"]}
            for key, name in (("Interval", "interval"), ("Timeout", "timeout"), ("StartPeriod", "start_period"), ("StartInterval", "start_interval")):
                if duration(hc.get(key)):
                    block[name] = duration(hc.get(key))
            if hc.get("Retries"):
                block["retries"] = int(hc["Retries"])
            svc["healthcheck"] = block
    if host.get("ReadonlyRootfs"):
        svc["read_only"] = True
    for key, name in (("CapAdd", "cap_add"), ("CapDrop", "cap_drop"), ("SecurityOpt", "security_opt"), ("ExtraHosts", "extra_hosts"),
                      ("Dns", "dns"), ("DnsSearch", "dns_search"), ("DnsOptions", "dns_opt"), ("GroupAdd", "group_add")):
        if host.get(key):
            svc[name] = list(host[key])
    if host.get("Tmpfs"):
        svc["tmpfs"] = [f"{path}:{opts}" if opts else path for path, opts in sorted(host["Tmpfs"].items())]
    if host.get("Sysctls"):
        svc["sysctls"] = dict(host["Sysctls"])
    if host.get("Ulimits"):
        svc["ulimits"] = {u["Name"]: {"soft": int(u["Soft"]), "hard": int(u["Hard"])} for u in host["Ulimits"]}
    if host.get("Memory"):
        svc["mem_limit"] = int(host["Memory"])
        if host.get("MemorySwap"):
            svc["memswap_limit"] = int(host["MemorySwap"])
    if host.get("MemoryReservation"):
        svc["mem_reservation"] = int(host["MemoryReservation"])
    if host.get("NanoCpus"):
        svc["cpus"] = format(host["NanoCpus"] / 1e9, "g")
    if host.get("CpuShares"):
        svc["cpu_shares"] = int(host["CpuShares"])
    if host.get("PidsLimit") and int(host["PidsLimit"]) > 0:
        svc["pids_limit"] = int(host["PidsLimit"])
    if host.get("ShmSize") and int(host["ShmSize"]) != DEFAULT_SHM:
        svc["shm_size"] = int(host["ShmSize"])
    if host.get("OomScoreAdj"):
        svc["oom_score_adj"] = int(host["OomScoreAdj"])
    log = host.get("LogConfig") or {}
    if log.get("Type"):
        svc["logging"] = {"driver": log["Type"], "options": dict(log.get("Config") or {})}
    return svc


def compose_document(svc: dict, args: argparse.Namespace) -> dict:
    return {
        "services": {args.service: svc},
        "networks": {args.network: {"name": args.network, "external": True}},
    }


def _scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    need(isinstance(value, str), f"UNSUPPORTED_YAML_VALUE {value!r}")
    return json.dumps(value.replace("$", "$$"))  # Compose interpolation escape


def to_yaml(value: object, indent: int = 0) -> str:
    pad = "  " * indent
    lines: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            k = json.dumps(str(key))
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}{k}:")
                lines.append(to_yaml(item, indent + 1))
            elif isinstance(item, dict):
                lines.append(f"{pad}{k}: {{}}")
            elif isinstance(item, list):
                lines.append(f"{pad}{k}: []")
            else:
                lines.append(f"{pad}{k}: {_scalar(item)}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                need(isinstance(item, dict) and item, "UNSUPPORTED_YAML_NESTING")
                nested = to_yaml(item, indent + 1).splitlines()
                lines.append(f"{pad}- {nested[0].lstrip()}")
                lines.extend(nested[1:])
            else:
                lines.append(f"{pad}- {_scalar(item)}")
    return "\n".join(lines)


def render_compose(svc: dict, args: argparse.Namespace, title: str) -> str:
    header = (
        f"# {title}\n# Generated by wp2c-stage2-frontend.py from `docker inspect` at {utc_now()}.\n"
        f"# Use only with: docker compose --file <this> --project-name {args.project} up --no-deps --no-build "
        f"--pull never --force-recreate --detach {args.service}\n"
    )
    return header + to_yaml(compose_document(svc, args)) + "\n"


def _norm(value: object) -> object:
    if isinstance(value, dict):
        out = {k: _norm(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, [], {}, "", 0, False)}
    if isinstance(value, list):
        return [_norm(v) for v in value]
    return value


def effective(container: dict) -> dict:
    """Settings that must match between the recorded and the recreated container."""
    cfg, host = container.get("Config") or {}, container.get("HostConfig") or {}
    return {
        "image_id": container.get("Image"),
        "config_image": cfg.get("Image"),
        "env": sorted(cfg.get("Env") or []),
        "user": cfg.get("User") or "",
        "cmd": cfg.get("Cmd"),
        "entrypoint": cfg.get("Entrypoint"),
        "working_dir": cfg.get("WorkingDir") or "",
        "healthcheck": _norm(cfg.get("Healthcheck") or {}),
        "stop_signal": cfg.get("StopSignal") or "",
        "stop_timeout": cfg.get("StopTimeout"),
        "exposed_ports": sorted(cfg.get("ExposedPorts") or {}),
        "labels": {k: v for k, v in (cfg.get("Labels") or {}).items() if not k.startswith("com.docker.compose.")},
        "networks": sorted((container.get("NetworkSettings") or {}).get("Networks") or {}),
        "host_config": _norm({k: v for k, v in host.items() if k not in COMPARE_IGNORE_HOSTCONFIG}),
    }


def expected_effective(baseline: dict, *, image_id: str, config_image: str, image_labels: dict,
                       baseline_image: dict, server_api: str | None) -> dict:
    exp = effective(baseline)
    exp["image_id"], exp["config_image"] = image_id, config_image
    if server_api is not None:
        exp["env"] = sorted(candidate_env(baseline["Config"].get("Env") or [], server_api))
        exp["labels"] = {**image_labels, **user_labels(baseline, baseline_image)}
    return exp


def differences(expected: dict, actual: dict) -> list[str]:
    diffs = [k for k in expected if k != "host_config" and expected[k] != actual.get(k)]
    eh, ah = expected["host_config"], actual.get("host_config") or {}
    diffs += [f"HostConfig.{k}" for k in sorted(set(eh) | set(ah)) if eh.get(k) != ah.get(k)]
    return diffs


# ---------------------------------------------------------------- guards


def hold_lock(path: Path) -> int:
    if not path.exists() and not path.is_symlink():
        try:
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
        except FileExistsError:
            pass
    st = os.lstat(path)
    need(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_uid == os.geteuid() and (st.st_mode & 0o777) == 0o600,
         "CANONICAL_LOCK_UNSAFE " + str(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    fst = os.fstat(fd)
    if (fst.st_dev, fst.st_ino) != (st.st_dev, st.st_ino):
        os.close(fd)
        raise Stop("CANONICAL_LOCK_INODE_CHANGED")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        os.close(fd)
        raise Stop("ACTIVE_DEPLOYMENT_LOCK " + str(path)) from error
    return fd


def common_checks(args: argparse.Namespace, working_gib: int = 0) -> None:
    need(os.geteuid() != 0, "RUN_AS_OPERATOR_NONROOT")
    need(os.uname().nodename.split(".")[0] == args.expect_node, f"WRONG_NODE {os.uname().nodename} expected={args.expect_node}")
    need(free_bytes(Path(args.workspace)) >= (args.reserve_gib + working_gib) * GIB,
         f"DISK_RESERVE_{args.reserve_gib}GIB_PLUS_{working_gib}GIB_FAILED")


def workspace(args: argparse.Namespace) -> Path:
    path = Path(args.workspace)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    need(not path.is_symlink() and path.stat().st_uid == os.geteuid(), "WORKSPACE_NOT_OWNED " + str(path))
    os.chmod(path, 0o700)
    return path


def rollback_identity(args: argparse.Namespace) -> tuple[str, str]:
    need(args.rollback_source and SHA40.match(args.rollback_source), "ROLLBACK_SOURCE_REQUIRED (40 hex)")
    need(args.rollback_build and BUILD_ID.match(args.rollback_build), "ROLLBACK_BUILD_REQUIRED")
    return args.rollback_source, args.rollback_build


# ---------------------------------------------------------------- stage


def parse_manifest(path: Path) -> list[tuple[str, str]]:
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        need(len(parts) == 2 and SHA64.match(parts[0]), "MALFORMED_MANIFEST_LINE " + path.name)
        name = parts[1].lstrip("*").removeprefix("./")
        need(name and not name.startswith("/") and ".." not in Path(name).parts, "UNSAFE_MANIFEST_PATH " + name)
        entries.append((parts[0], name))
    return entries


def kv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            need(key not in out, "DUPLICATE_KEY " + key)
            out[key] = value
    return out


def check_tar_member(member: tarfile.TarInfo) -> None:
    name = member.name
    need(name and not name.startswith("/") and ".." not in Path(name).parts, "UNSAFE_TAR_PATH " + name)
    need(not (member.ischr() or member.isblk() or member.isfifo()), "UNSAFE_TAR_MEMBER " + name)
    if member.issym() or member.islnk():
        target = os.path.normpath(os.path.join(os.path.dirname(name), member.linkname)) if member.issym() else member.linkname
        need(not member.linkname.startswith("/") and not target.startswith(".."), "UNSAFE_TAR_LINK " + name)


def verify_runtime_tar(archive: Path, manifest: Path) -> int:
    expected = {name: digest for digest, name in parse_manifest(manifest)}
    seen = set()
    with tarfile.open(archive, "r|gz") as tar:
        for member in tar:
            check_tar_member(member)
            name = member.name.removeprefix("./")
            if member.isfile():
                need(name in expected, "RUNTIME_FILE_NOT_IN_MANIFEST " + name)
                handle = tar.extractfile(member)
                need(handle is not None and sha256_stream(handle) == expected[name], "RUNTIME_FILE_HASH_MISMATCH " + name)
                seen.add(name)
    need(seen == set(expected), f"RUNTIME_FILES_MISSING {len(set(expected) - seen)}")
    return len(seen)


def verify_artifact(art: Path) -> dict:
    listed = parse_manifest(art / "frontend-artifact-sha256.txt")
    names = [name for _, name in listed]
    need(len(names) == len(set(names)), "DUPLICATE_ARTIFACT_MANIFEST_ENTRY")
    need(set(names) == ARTIFACT_FILES - {"frontend-artifact-sha256.txt"}, f"ARTIFACT_MANIFEST_INCOMPLETE {sorted(set(names) ^ (ARTIFACT_FILES - {'frontend-artifact-sha256.txt'}))}")
    for digest, name in listed:
        path = art / name
        need(path.is_file() and not path.is_symlink(), "ARTIFACT_FILE_MISSING " + name)
        need(sha256_file(path) == digest, "ARTIFACT_FILE_HASH_MISMATCH " + name)
    contract = kv(art / "frontend-runtime-contract.txt")
    need(set(contract) == CONTRACT_KEYS, f"RUNTIME_CONTRACT_KEYS {sorted(contract)}")
    need(contract["runtime_mode"] == "live", "RUNTIME_CONTRACT_NOT_LIVE")
    need(contract["api_base_url"] == "same-origin" and contract["websocket_url"] == "same-origin", "RUNTIME_CONTRACT_NOT_SAME_ORIGIN")
    need(contract["auth_provider"] == "local", "RUNTIME_CONTRACT_AUTH_NOT_LOCAL")
    need(contract["external_https_stage"] == "false", "RUNTIME_CONTRACT_EXTERNAL_HTTPS_STAGE")
    need(UUID.match(contract["organization_id"]), "RUNTIME_CONTRACT_ORGANIZATION_ID")
    source = (art / "frontend-source-sha.txt").read_text(encoding="utf-8").strip()
    build = (art / "frontend-build-id.txt").read_text(encoding="utf-8").strip()
    need(SHA40.match(source), "ARTIFACT_SOURCE_INVALID")
    need(BUILD_ID.match(build), "ARTIFACT_BUILD_ID_INVALID")
    need((art / "frontend-platform.txt").read_text(encoding="utf-8").strip() == "linux/arm64", "ARTIFACT_PLATFORM_NOT_ARM64")
    public = (art / "frontend-public-contract.txt").read_text(encoding="utf-8").splitlines()
    need("status=PASS" in public, "PUBLIC_CONTRACT_NOT_PASS")
    need("same_origin_browser_bundle=no-absolute-host-origin" in public, "PUBLIC_CONTRACT_NO_SAME_ORIGIN_PROOF")
    need(f"build_id={build}" in public, "PUBLIC_CONTRACT_BUILD_ID_MISMATCH")
    need("NEXT_PUBLIC_NEXOLAB_API_BASE_URL=same-origin" in public and "NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=same-origin" in public,
         "PUBLIC_CONTRACT_ENDPOINTS_NOT_SAME_ORIGIN")
    return {"source": source, "build_id": build, "organization_id": contract["organization_id"],
            "node_version": (art / "frontend-node-version.txt").read_text(encoding="utf-8").strip()}


def mode_stage(args: argparse.Namespace) -> int:
    common_checks(args, working_gib=2)
    expected = (args.expect_zip_sha256 or "").lower()
    need(SHA64.match(expected), "EXPECT_ZIP_SHA256_REQUIRED")
    zip_path = Path(args.artifact_zip)
    need(zip_path.is_file(), "ARTIFACT_ZIP_MISSING")
    ws = workspace(args)
    art = ws / "artifact"
    need(not art.exists(), f"ARTIFACT_ALREADY_STAGED {art} (move it away to restage)")
    need(sha256_file(zip_path) == expected, "ARTIFACT_ZIP_SHA256_MISMATCH")
    staging = ws / ".artifact.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(mode=0o700)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            infos = archive.infolist()
            names = [i.filename for i in infos]
            need(len(names) == len(set(names)), "DUPLICATE_ZIP_ENTRY")
            for info in infos:
                name = info.filename
                need(name and "/" not in name and "\\" not in name and not name.startswith(".") and name != "..",
                     "UNSAFE_ZIP_ENTRY " + name)
                need(not info.is_dir() and not stat.S_ISLNK(info.external_attr >> 16), "UNSAFE_ZIP_ENTRY_TYPE " + name)
                need(name in ARTIFACT_FILES, "UNEXPECTED_ZIP_ENTRY " + name)
            need(set(names) == ARTIFACT_FILES, f"ZIP_INCOMPLETE {sorted(ARTIFACT_FILES - set(names))}")
            for info in infos:
                with archive.open(info) as source, (staging / info.filename).open("xb") as target:
                    shutil.copyfileobj(source, target, CHUNK)
        facts = verify_artifact(staging)
        count = verify_runtime_tar(staging / "frontend-runtime.tar.gz", staging / "frontend-runtime-files-sha256.txt")
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    os.rename(staging, art)
    facts.update(zip_sha256=expected, runtime_files=count, staged_at=utc_now())
    write_json(ws / "stage.json", facts)
    print(f"STAGE_VERIFIED source={facts['source']} build={facts['build_id']} runtime_files={count}", flush=True)
    return 0


# ---------------------------------------------------------------- build


def candidate_tag(source: str) -> str:
    return f"nexolab/dashboard:wp2c-stage2-{source[:12]}-arm64"


def prove_base(old: dict) -> dict:
    layers = old["RootFS"]["Layers"]
    best: list[dict] = []
    best_len = 0
    for image_id in text(["docker", "images", "--no-trunc", "--quiet"], timeout=60).split():
        cand = image_inspect(image_id)
        if cand["Id"] == old["Id"]:
            continue
        cl = cand["RootFS"]["Layers"]
        if len(cl) < len(layers) and layers[: len(cl)] == cl and any(t.startswith("node:") for t in cand.get("RepoTags") or []):
            if len(cl) > best_len:
                best, best_len = [cand], len(cl)
            elif len(cl) == best_len and cand["Id"] not in {b["Id"] for b in best}:
                best.append(cand)
    need(len(best) == 1, f"BASE_IMAGE_NOT_UNIQUELY_PROVEN candidates={[b.get('RepoTags') for b in best]}")
    return best[0]


def base_reference(base: dict) -> str:
    """A local `node:` tag that resolves to the proven base ID.

    BuildKit cannot build FROM a bare image ID (it resolves `sha256:<id>` as the Docker Hub
    repository `library/sha256` and tries to pull; site run 2026-11-26, #1782). The tag is
    re-proven against the ID here and immediately before the build, and the built image's
    layers are proven to start with the base layers afterwards."""
    tags = sorted(t for t in base.get("RepoTags") or [] if t.startswith("node:") and "@" not in t)
    need(tags, "BASE_IMAGE_HAS_NO_NODE_TAG " + base["Id"])
    for tag in tags:
        if image_inspect(tag)["Id"] == base["Id"]:
            return tag
    raise Stop("BASE_TAG_DOES_NOT_RESOLVE_TO_PROVEN_ID " + base["Id"])


def dockerfile_for(old: dict, base_ref: str, owner: str, source: str) -> str:
    cfg = old["Config"]
    need(not base_ref.startswith("sha256:"), "BUILDKIT_CANNOT_BUILD_FROM_IMAGE_ID")
    lines = [f"FROM {base_ref}"]
    for item in cfg.get("Env") or []:
        key, _, value = item.partition("=")
        lines.append(f"ENV {key}={json.dumps(value)}")
    workdir = cfg.get("WorkingDir") or "/app"
    lines += [f"WORKDIR {workdir}", f"COPY --chown={owner} app/ {workdir}/"]
    if cfg.get("User"):
        lines.append(f"USER {cfg['User']}")
    for port in sorted(cfg.get("ExposedPorts") or {}):
        lines.append(f"EXPOSE {port}")
    hc = cfg.get("Healthcheck")
    if hc and hc.get("Test"):
        def secs(ns: int | None, default: str) -> str:
            return f"{int(ns // 1_000_000_000)}s" if ns else default
        test = hc["Test"]
        need(test[0] in ("CMD", "CMD-SHELL"), "UNSUPPORTED_HEALTHCHECK")
        cmd = json.dumps(test[1:]) if test[0] == "CMD" else test[1]
        start_interval = f" --start-interval={secs(hc['StartInterval'], '5s')}" if hc.get("StartInterval") else ""
        lines.append(
            f"HEALTHCHECK --interval={secs(hc.get('Interval'), '30s')} --timeout={secs(hc.get('Timeout'), '30s')} "
            f"--start-period={secs(hc.get('StartPeriod'), '0s')}{start_interval} --retries={hc.get('Retries') or 3} CMD {cmd}"
        )
    labels = dict(cfg.get("Labels") or {})
    labels["org.opencontainers.image.revision"] = source
    if "org.opencontainers.image.version" in labels:
        labels["org.opencontainers.image.version"] = source
    for key, value in sorted(labels.items()):
        lines.append(f"LABEL {json.dumps(key)}={json.dumps(value)}")
    if cfg.get("Entrypoint"):
        lines.append(f"ENTRYPOINT {json.dumps(cfg['Entrypoint'])}")
    if cfg.get("Cmd"):
        lines.append(f"CMD {json.dumps(cfg['Cmd'])}")
    return "\n".join(lines) + "\n"


def identity_manifest(template: dict, source: str, build: str) -> bytes:
    need(set(template) == {"schema_version", "service", "source_commit", "build_id", "deployed_at", "identity_source"},
         "IDENTITY_TEMPLATE_KEYS_CHANGED")
    need(template.get("identity_source") == IDENTITY_SOURCE, "IDENTITY_TEMPLATE_SOURCE_CHANGED")
    return (json.dumps({**template, "source_commit": source, "build_id": build}, separators=(",", ":")) + "\n").encode()


def safe_extract_tar(archive: Path, dest: Path) -> None:
    with tarfile.open(archive, "r|gz") as tar:
        for member in tar:
            check_tar_member(member)
            tar.extract(member, dest, filter="data")


def mode_build(args: argparse.Namespace) -> int:
    common_checks(args, working_gib=3)
    old_source, old_build = rollback_identity(args)
    ws = workspace(args)
    facts = read_json(ws / "stage.json", "STAGE_NOT_DONE")
    art = ws / "artifact"
    need(verify_artifact(art)["source"] == facts["source"], "STAGED_ARTIFACT_CHANGED")
    source, build = facts["source"], facts["build_id"]
    tag = candidate_tag(source)
    need(text(["docker", "images", "--quiet", tag], timeout=60) == "", "CANDIDATE_TAG_ALREADY_EXISTS " + tag)
    current = inspect(args.dashboard_container)
    old = image_inspect(current["Image"])
    need(old["Architecture"] == "arm64", "CURRENT_IMAGE_NOT_ARM64")
    base = prove_base(old)
    base_ref = base_reference(base)
    print("BASE_PROVEN " + base["Id"] + " " + ",".join(base.get("RepoTags") or []) + " via " + base_ref, flush=True)
    workdir = old["Config"].get("WorkingDir") or "/app"

    def in_old(*cmd: str) -> str:
        return text(["docker", "run", "--rm", "--network", "none", "--pull", "never", "--entrypoint", cmd[0], old["Id"], *cmd[1:]])

    old_identity = json.loads(in_old("cat", f"{workdir}/.nexolab-runtime-identity.json"))
    need(old_identity.get("source_commit") == old_source and old_identity.get("build_id") == old_build,
         f"CURRENT_IMAGE_IDENTITY_NOT_ROLLBACK_IDENTITY {old_identity}")
    old_top = sorted(in_old("ls", "-A", workdir).split())
    owner = in_old("stat", "-c", "%u:%g", f"{workdir}/.next/BUILD_ID")
    node_version = in_old("node", "--version")
    need(node_version == "v" + facts["node_version"], f"NODE_VERSION_MISMATCH image={node_version} artifact={facts['node_version']}")
    context = ws / "image-context"
    if context.exists():
        shutil.rmtree(context)
    app = context / "app"
    app.mkdir(parents=True, mode=0o700)
    safe_extract_tar(art / "frontend-runtime.tar.gz", app)
    for name in ("package.json", "package-lock.json"):
        if name in old_top:
            shutil.copyfile(art / name, app / name)
    (app / ".nexolab-runtime-identity.json").write_bytes(identity_manifest(old_identity, source, build))
    new_top = sorted(p.name for p in app.iterdir())
    need(set(new_top) == set(old_top), f"APP_LAYOUT_DIFFERS old={old_top} new={new_top}")
    manifest = parse_manifest(art / "frontend-runtime-files-sha256.txt")
    for digest, name in manifest:
        path = app / name
        need(path.is_file() and not path.is_symlink() and sha256_file(path) == digest, "CONTEXT_FILE_MISMATCH " + name)
    (context / "Dockerfile").write_text(dockerfile_for(old, base_ref, owner, source), encoding="utf-8")
    need(image_inspect(base_ref)["Id"] == base["Id"], "BASE_TAG_MOVED " + base_ref)  # re-proven right before the build
    print("== build: tar-streamed context, no cache, no pull, no network", flush=True)
    tar = subprocess.Popen(["tar", "-C", str(context), "-cf", "-", "."], stdout=subprocess.PIPE)
    result = subprocess.run(["docker", "build", "--no-cache", "--pull=false", "--network", "none", "--platform", "linux/arm64",
                             "--tag", tag, "-"], stdin=tar.stdout, capture_output=True, timeout=1800, check=False, env=docker_env())
    tar.stdout.close()
    need(tar.wait() == 0, "CONTEXT_TAR_FAILED")
    need(result.returncode == 0, "IMAGE_BUILD_FAILED " + result.stderr.decode(errors="replace")[-500:])
    new = image_inspect(tag)
    need(new["Architecture"] == "arm64", "NEW_IMAGE_NOT_ARM64")
    need(new["RootFS"]["Layers"][: len(base["RootFS"]["Layers"])] == base["RootFS"]["Layers"], "NEW_IMAGE_NOT_ON_PROVEN_BASE")
    for key in ("Env", "User", "WorkingDir", "ExposedPorts", "Healthcheck", "Cmd", "Entrypoint", "Volumes"):
        need(new["Config"].get(key) == old["Config"].get(key), "IMAGE_CONFIG_DIFFERS " + key)
    need((new["Config"].get("Labels") or {}).get("org.opencontainers.image.revision") == source, "NEW_IMAGE_REVISION_LABEL")
    print("== build: file-by-file comparison of the image with the artifact", flush=True)
    root = workdir.strip("/")
    expected = {f"{root}/{name}": digest for digest, name in manifest}
    extras = {f"{root}/.nexolab-runtime-identity.json"} | {f"{root}/{n}" for n in ("package.json", "package-lock.json") if n in old_top}
    container = text(["docker", "create", "--network", "none", "--pull", "never", tag], timeout=60)
    seen: set[str] = set()
    try:
        export = subprocess.Popen(["docker", "export", container], stdout=subprocess.PIPE, env=docker_env())
        with tarfile.open(fileobj=export.stdout, mode="r|") as stream:
            for member in stream:
                name = member.name.lstrip("./")
                if not name.startswith(root + "/") or not member.isfile():
                    continue
                handle = stream.extractfile(member)
                digest = sha256_stream(handle) if handle else ""
                if name in expected:
                    need(digest == expected[name], "IMAGE_FILE_DIFFERS_FROM_ARTIFACT " + name)
                    seen.add(name)
                elif name in extras or name.startswith(root + "/.next/cache/"):
                    continue
                else:
                    raise Stop("UNEXPECTED_FILE_IN_IMAGE " + name)
        need(export.wait() == 0, "DOCKER_EXPORT_FAILED")
    finally:
        run(["docker", "rm", container], timeout=60, check=False)
    need(seen == set(expected), f"IMAGE_MISSING_ARTIFACT_FILES {len(set(expected) - seen)}")
    image_identity = json.loads(text(["docker", "run", "--rm", "--network", "none", "--pull", "never", "--entrypoint", "cat",
                                      new["Id"], f"{workdir}/.nexolab-runtime-identity.json"]))
    need(image_identity.get("source_commit") == source and image_identity.get("build_id") == build, "IMAGE_IDENTITY_MISMATCH")
    shutil.rmtree(context)
    write_json(ws / "build.json", {"tag": tag, "image_id": new["Id"], "base_image_id": base["Id"], "source": source,
                                   "build_id": build, "previous_image_id": old["Id"], "built_at": utc_now()})
    print(f"IMAGE_VERIFIED {tag} {new['Id']} files={len(seen)}", flush=True)
    return 0


# ---------------------------------------------------------------- preview


def compose_paths(ws: Path) -> tuple[Path, Path]:
    return ws / "compose" / "candidate.compose.yaml", ws / "compose" / "rollback.compose.yaml"


def compose_up_argv(path: Path, args: argparse.Namespace) -> list[str]:
    # No --remove-orphans, no down, no volumes: only the stateless dashboard is recreated.
    return ["docker", "compose", "--file", str(path), "--project-name", args.project, "up", "--no-deps", "--no-build",
            "--pull", "never", "--force-recreate", "--detach", args.service]


def server_api_probe(container: str, server_api: str) -> None:
    url = urllib.parse.urlsplit(server_api)
    need(url.hostname and url.port, "SERVER_API_BASE_URL_INVALID")
    result = run(["docker", "exec", container, "getent", "hosts", url.hostname], timeout=30, check=False)
    need(result.returncode == 0 and result.stdout.strip(), f"DOCKER_DNS_FAILED {url.hostname} in {container}")
    script = ("fetch(process.argv[1],{signal:AbortSignal.timeout(5000)})"
              ".then(r=>process.exit(r.status===200?0:3)).catch(()=>process.exit(4))")
    target = server_api.rstrip("/") + "/health/ready"
    result = run(["docker", "exec", container, "node", "-e", script, target], timeout=30, check=False)
    need(result.returncode == 0, f"SERVER_SIDE_API_UNREACHABLE {target} from {container} rc={result.returncode}")


def wait_container(name: str, deadline_s: int, image_id: str | None = None) -> dict:
    deadline = time.monotonic() + deadline_s
    last = "unknown"
    while time.monotonic() < deadline:
        data = try_inspect(name)
        if data is not None:
            last = health(data)
            if (image_id is None or data.get("Image") == image_id) and last in ("healthy", "running"):
                return data
        time.sleep(POLL_SECONDS)
    raise Stop(f"CONTAINER_NOT_HEALTHY {name} last={last}")


def fidelity(path: Path, expected: dict, args: argparse.Namespace, label: str) -> None:
    """Create (never start) the service under a scratch project and compare settings."""
    scratch = f"{FIDELITY_PROJECT}-{args.service}-1"
    stale = try_inspect(scratch)
    if stale is not None:
        need(compose_labels(stale).get("com.docker.compose.project") == FIDELITY_PROJECT, "SCRATCH_NAME_IN_USE " + scratch)
        need(not (stale.get("State") or {}).get("Running"), "SCRATCH_CONTAINER_RUNNING " + scratch)
        run(["docker", "rm", stale["Id"]], timeout=60)
    run(["docker", "compose", "--file", str(path), "--project-name", FIDELITY_PROJECT, "create", "--no-build",
         "--pull", "never", "--force-recreate", args.service], timeout=120)
    created = inspect(scratch)
    try:
        need(not (created.get("State") or {}).get("Running"), "SCRATCH_CONTAINER_STARTED")
        diffs = differences(expected, effective(created))
        need(not diffs, f"COMPOSE_FIDELITY_FAILED {label} differs: {diffs}")
    finally:
        run(["docker", "rm", created["Id"]], timeout=60, check=False)
    print(f"COMPOSE_FIDELITY_PROVEN {label}", flush=True)


def remove_preview(name: str) -> None:
    data = try_inspect(name)
    if data is None:
        return
    need(((data.get("Config") or {}).get("Labels") or {}).get(PREVIEW_LABEL) == "preview", "PREVIEW_NAME_IN_USE_BY_FOREIGN " + name)
    run(["docker", "rm", "--force", data["Id"]], timeout=60)


def mode_preview(args: argparse.Namespace) -> int:
    common_checks(args)
    old_source, old_build = rollback_identity(args)
    ws = workspace(args)
    facts = read_json(ws / "stage.json", "STAGE_NOT_DONE")
    built = read_json(ws / "build.json", "BUILD_NOT_DONE")
    new_image = image_inspect(built["tag"])
    need(new_image["Id"] == built["image_id"], "CANDIDATE_IMAGE_CHANGED_SINCE_BUILD")
    need((new_image["Config"].get("Labels") or {}).get("org.opencontainers.image.revision") == facts["source"], "CANDIDATE_REVISION_LABEL")
    current = inspect(args.dashboard_container)
    validate_current(current, args)
    need(health(current) == "healthy", "CURRENT_DASHBOARD_NOT_HEALTHY")
    probe(local_url(current), old_source, old_build, tuple(args.route))
    old_image = image_inspect(current["Image"])
    need(image_inspect(current["Config"]["Image"])["Id"] == current["Image"], "ROLLBACK_TAG_NOT_CURRENT_IMAGE")

    (ws / "preview.json").unlink(missing_ok=True)  # a failed preview never leaves an executable state
    rollback_svc = service_model(current, old_image, args)
    candidate_svc = dict(rollback_svc)
    candidate_svc["image"] = built["tag"]
    candidate_svc["environment"] = candidate_env(rollback_svc["environment"], args.server_api_base_url)
    candidate_path, rollback_path = compose_paths(ws)
    write_private(candidate_path, render_compose(candidate_svc, args, f"WP2c Stage 2 CANDIDATE ({facts['source'][:12]} {facts['build_id']})"))
    write_private(rollback_path, render_compose(rollback_svc, args, f"WP2c Stage 2 ROLLBACK = exact current {current['Id'][:12]}"))
    write_json(ws / "baseline.json", {"container": current, "image": old_image, "recorded_at": utc_now(),
                                      "rollback_source": old_source, "rollback_build": old_build})
    for path in (candidate_path, rollback_path):
        print(f"----- {path} -----\n{path.read_text(encoding='utf-8')}", flush=True)
        run(["docker", "compose", "--file", str(path), "--project-name", args.project, "config", "--quiet"], timeout=60)

    exp_rollback = expected_effective(current, image_id=current["Image"], config_image=current["Config"]["Image"],
                                      image_labels={}, baseline_image=old_image, server_api=None)
    exp_candidate = expected_effective(current, image_id=new_image["Id"], config_image=built["tag"],
                                       image_labels=new_image["Config"].get("Labels") or {}, baseline_image=old_image,
                                       server_api=args.server_api_base_url)
    fidelity(rollback_path, exp_rollback, args, "rollback")
    fidelity(candidate_path, exp_candidate, args, "candidate")

    _, _, cport = published(current)
    env_file = ws / "preview.env"
    write_private(env_file, "".join(f"{item}\n" for item in candidate_svc["environment"]))
    remove_preview(args.preview_name)
    argv = ["docker", "run", "--detach", "--name", args.preview_name, "--network", args.network, "--pull", "never",
            "--restart", "no", "--label", f"{PREVIEW_LABEL}=preview", "--env-file", str(env_file),
            "--publish", f"127.0.0.1:{args.preview_port}:{cport}"]
    if current["HostConfig"].get("Init"):
        argv.append("--init")
    run(argv + [built["image_id"]], timeout=120)
    try:
        wait_container(args.preview_name, args.wait_seconds, new_image["Id"])
        data = probe(f"http://127.0.0.1:{args.preview_port}", facts["source"], facts["build_id"], tuple(args.route))
        print(f"PREVIEW_IDENTITY_VERIFIED {data['source_commit'][:12]} {data['build_id']}", flush=True)
        server_api_probe(args.preview_name, args.server_api_base_url)
        print(f"PREVIEW_DOCKER_DNS_AND_SERVER_API_VERIFIED {args.server_api_base_url}", flush=True)
    finally:
        remove_preview(args.preview_name)
        env_file.unlink(missing_ok=True)
    write_json(ws / "preview.json", {
        "baseline_container_id": current["Id"], "baseline_image_id": current["Image"],
        "candidate_image_id": new_image["Id"], "candidate_tag": built["tag"],
        "compose_sha256": {p.name: sha256_file(p) for p in (candidate_path, rollback_path)},
        "source": facts["source"], "build_id": facts["build_id"], "verified_at": utc_now(),
    })
    print("PREVIEW_GREEN (preview container removed; production unchanged)", flush=True)
    return 0


# ---------------------------------------------------------------- check / execute / rollback


def load_state(args: argparse.Namespace) -> dict:
    ws = workspace(args)
    state = {
        "ws": ws,
        "build": read_json(ws / "build.json", "BUILD_NOT_DONE"),
        "baseline": read_json(ws / "baseline.json", "PREVIEW_NOT_DONE"),
        "preview": read_json(ws / "preview.json", "PREVIEW_NOT_DONE"),
    }
    candidate_path, rollback_path = compose_paths(ws)
    need(sorted(p.name for p in candidate_path.parent.iterdir()) == sorted([candidate_path.name, rollback_path.name]),
         "COMPOSE_DIRECTORY_HAS_FOREIGN_FILES")
    for path in (candidate_path, rollback_path):
        need(path.is_file() and sha256_file(path) == state["preview"]["compose_sha256"][path.name], "COMPOSE_FILE_CHANGED_SINCE_PREVIEW " + path.name)
    state["candidate_path"], state["rollback_path"] = candidate_path, rollback_path
    return state


def preflight(args: argparse.Namespace, state: dict) -> dict:
    """Read-only checks; returns the backend snapshot."""
    common_checks(args)
    old_source, old_build = rollback_identity(args)
    base = state["baseline"]["container"]
    need((state["baseline"]["rollback_source"], state["baseline"]["rollback_build"]) == (old_source, old_build),
         "ROLLBACK_IDENTITY_DIFFERS_FROM_PREVIEW")
    current = inspect(args.dashboard_container)
    need(current["Id"] == base["Id"] and current["Image"] == base["Image"], "DASHBOARD_CHANGED_SINCE_PREVIEW (rerun preview)")
    validate_current(current, args)
    need(health(current) == "healthy", "CURRENT_DASHBOARD_NOT_HEALTHY")
    candidate = image_inspect(state["build"]["tag"])
    need(candidate["Id"] == state["build"]["image_id"] == state["preview"]["candidate_image_id"], "CANDIDATE_IMAGE_CHANGED")
    need(image_inspect(base["Config"]["Image"])["Id"] == base["Image"], "ROLLBACK_TAG_NOT_RECORDED_IMAGE")
    for path in (state["candidate_path"], state["rollback_path"]):
        run(["docker", "compose", "--file", str(path), "--project-name", args.project, "config", "--quiet"], timeout=60)
    probe(local_url(current), old_source, old_build, tuple(args.route))
    gateway_probe(args.gateway_url, old_source, old_build)
    backends = snapshots(args.backend)
    status, _ = http_get(readiness_url(args))
    need(status == 200, f"API_NOT_READY {status}")
    print(f"ROLLBACK_IDENTITY_VERIFIED {old_source[:12]} {old_build} (dashboard and gateway)", flush=True)
    return backends


def mode_check(args: argparse.Namespace) -> int:
    fd = hold_lock(Path(args.lock_path))
    try:
        preflight(args, load_state(args))
    finally:
        os.close(fd)
    print("STAGE2_CHECK_PASS NO_WRITES", flush=True)
    return 0


def verify_switched(args: argparse.Namespace, state: dict, backend_before: dict, *, rollback: bool) -> dict:
    base, base_image = state["baseline"]["container"], state["baseline"]["image"]
    url = local_url(base)
    if rollback:
        source, build = state["baseline"]["rollback_source"], state["baseline"]["rollback_build"]
        image_id = base["Image"]
        expected = expected_effective(base, image_id=base["Image"], config_image=base["Config"]["Image"], image_labels={},
                                      baseline_image=base_image, server_api=None)
    else:
        source, build = state["preview"]["source"], state["preview"]["build_id"]
        image_id = state["build"]["image_id"]
        new_image = image_inspect(state["build"]["tag"])
        expected = expected_effective(base, image_id=image_id, config_image=state["build"]["tag"],
                                      image_labels=new_image["Config"].get("Labels") or {}, baseline_image=base_image,
                                      server_api=args.server_api_base_url)
    want = "healthy" if (base.get("State") or {}).get("Health") else "running"
    deadline = time.monotonic() + args.wait_seconds
    container: dict | None = None
    last_error = "not started"
    while time.monotonic() < deadline:
        try:
            container = inspect(args.dashboard_container)
            need(container.get("Image") == image_id, "SWITCHED_IMAGE_NOT_EXPECTED")
            need(health(container) == want, "DASHBOARD_NOT_YET_HEALTHY")
            probe(url, source, build, tuple(args.route))
            break
        except Stop as error:
            last_error = str(error)
            container = None
            time.sleep(POLL_SECONDS)
    need(container is not None, "DASHBOARD_TARGET_NOT_VERIFIED " + last_error[:300])
    diffs = differences(expected, effective(container))
    need(not diffs, f"RECREATED_CONTAINER_SETTINGS_DIFFER {diffs}")
    validate_current(container, args)
    gateway_probe(args.gateway_url, source, build)
    if not rollback:
        server_api_probe(args.dashboard_container, args.server_api_base_url)
    need(snapshots(args.backend) == backend_before, "BACKEND_CONTAINER_CHANGED")
    status, _ = http_get(readiness_url(args))
    need(status == 200, f"API_NOT_READY_AFTER_SWITCH {status}")
    return container


def record(state: dict, report: dict, kind: str) -> Path:
    path = state["ws"] / "reports" / f"{kind}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    write_json(path, report, exclusive=True)
    print("REPORT_PATH " + str(path), flush=True)
    return path


def do_rollback(args: argparse.Namespace, state: dict, backend_before: dict, report: dict, kind: str) -> int:
    try:
        run(compose_up_argv(state["rollback_path"], args), timeout=180)
        container = verify_switched(args, state, backend_before, rollback=True)
        report.update(outcome="ROLLED_BACK_VERIFIED", dashboard_container=container["Id"], backend_unchanged=True,
                      finished_at_utc=utc_now())
        record(state, report, kind)
        print("STAGE2_ROLLED_BACK_VERIFIED", flush=True)
        return 0
    except Exception as error:  # noqa: BLE001 - any failure leaves the rollback unverified
        report.update(outcome="HARD_BLOCKER_ROLLBACK_UNVERIFIED", rollback_error=str(error)[:600], finished_at_utc=utc_now())
        try:
            record(state, report, kind)
        finally:
            print("HARD_BLOCKER_ROLLBACK_UNVERIFIED " + str(error)[:400], flush=True)
        return 4


def mode_execute(args: argparse.Namespace) -> int:
    fd = hold_lock(Path(args.lock_path))
    try:
        state = load_state(args)
        backend_before = preflight(args, state)
        print("STAGE2_PREFLIGHT_PASS", flush=True)
        report = {"work_package": "1734-wp2c-stage2", "mode": "frontend_only", "started_at_utc": utc_now(),
                  "candidate": {"tag": state["build"]["tag"], "image_id": state["build"]["image_id"],
                                "source": state["preview"]["source"], "build_id": state["preview"]["build_id"]},
                  "rollback": {"image_id": state["baseline"]["container"]["Image"],
                               "source": state["baseline"]["rollback_source"], "build_id": state["baseline"]["rollback_build"],
                               "container_id": state["baseline"]["container"]["Id"]},
                  "backend_before": backend_before, "compose_argv": compose_up_argv(state["candidate_path"], args)}
        try:
            # Switched from here on: even a partial Compose failure requires rollback.
            run(compose_up_argv(state["candidate_path"], args), timeout=180)
            container = verify_switched(args, state, backend_before, rollback=False)
            need(free_bytes(Path(args.workspace)) >= args.reserve_gib * GIB, "DISK_RESERVE_AFTER_SWITCH_FAILED")
        except BaseException as error:  # noqa: BLE001 - every failure (even Ctrl-C) after the switch rolls back
            print("ACTIVATION_CHECK_FAILED " + str(error)[:400], flush=True)
            report["error"] = str(error)[:600]
            rc = do_rollback(args, state, backend_before, report, "execute")
            return 3 if rc == 0 else 4
        report.update(outcome="STAGE2_FRONTEND_GREEN", dashboard_container=container["Id"], backend_unchanged=True,
                      finished_at_utc=utc_now())
        record(state, report, "execute")
        print("STAGE2_FRONTEND_GREEN", flush=True)
        print("NEXT: verify login, Live Data WebSocket, charts and photos via the gateway on Ethernet and Wi-Fi, "
              "and re-verify tailscale serve :8444.", flush=True)
        return 0
    finally:
        os.close(fd)


def mode_rollback(args: argparse.Namespace) -> int:
    fd = hold_lock(Path(args.lock_path))
    try:
        need(os.geteuid() != 0, "RUN_AS_OPERATOR_NONROOT")
        need(os.uname().nodename.split(".")[0] == args.expect_node, "WRONG_NODE")
        state = load_state(args)
        need(image_inspect(state["baseline"]["container"]["Config"]["Image"])["Id"] == state["baseline"]["container"]["Image"],
             "ROLLBACK_TAG_NOT_RECORDED_IMAGE")
        backend_before = snapshots(args.backend)
        report = {"work_package": "1734-wp2c-stage2", "mode": "explicit_rollback", "started_at_utc": utc_now(),
                  "backend_before": backend_before, "compose_argv": compose_up_argv(state["rollback_path"], args)}
        return 0 if do_rollback(args, state, backend_before, report, "rollback") == 0 else 4
    finally:
        os.close(fd)


# ---------------------------------------------------------------- CLI


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=("stage", "build", "preview", "check", "execute", "rollback"))
    p.add_argument("--workspace", default=DEFAULT_WORKSPACE)
    p.add_argument("--artifact-zip")
    p.add_argument("--expect-zip-sha256")
    p.add_argument("--rollback-source", help="expected source commit of the CURRENT LAN dashboard")
    p.add_argument("--rollback-build", help="expected Next.js build ID of the CURRENT LAN dashboard")
    p.add_argument("--dashboard-container", default="nexolab-central-dashboard-1")
    p.add_argument("--project", default="nexolab-central")
    p.add_argument("--service", default="dashboard")
    p.add_argument("--network", default="nexolab-central")
    p.add_argument("--backend", action="append", help="backend container that must stay unchanged (repeatable)")
    p.add_argument("--route", action="append", help="route that must answer 200 (repeatable)")
    p.add_argument("--gateway-url", default="http://127.0.0.1")
    p.add_argument("--readiness-url", help="default: derived from the telemetry container publish")
    p.add_argument("--server-api-base-url", default="http://telemetry-service:8082")
    p.add_argument("--preview-name", default="nexolab-wp2c-stage2-preview")
    p.add_argument("--preview-port", type=int, default=3125)
    p.add_argument("--expect-node", default="nexolab-edge-01")
    p.add_argument("--lock-path", default=DEFAULT_LOCK)
    p.add_argument("--reserve-gib", type=int, default=20)
    p.add_argument("--wait-seconds", type=int, default=120)
    return p


MODES = {"stage": mode_stage, "build": mode_build, "preview": mode_preview, "check": mode_check,
         "execute": mode_execute, "rollback": mode_rollback}


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    args.backend = args.backend or list(DEFAULT_BACKENDS)
    args.route = args.route or list(DEFAULT_ROUTES)
    if os.geteuid() == 0:
        print("STOP RUN_AS_OPERATOR_NONROOT", file=sys.stderr, flush=True)
        return 2
    if args.server_api_base_url != "http://telemetry-service:8082":
        print("WARNING non-default server API base URL " + args.server_api_base_url, flush=True)
    try:
        return MODES[args.mode](args)
    except Stop as error:
        print("STOP " + str(error)[:700], file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
