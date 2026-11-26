#!/usr/bin/env python3
"""WP2c Stage 3 (#1734): backend on loopback, Edge bridge over Docker DNS, owner-run.

Runs on the production host as the operator account (docker group, never root),
strictly AFTER Stage 2 (same-origin LAN dashboard) is live. Every service is
derived from ``docker inspect`` (they belong to different Compose projects and
configuration paths). Two phases, each with its own fidelity proof and rollback:

  switch (mode execute), order
      central MQTT -> telemetry-service (readiness) -> MinIO -> dashboard -> Edge MQTT
    * ADD a 127.0.0.1 publish next to every publish on the compatibility address
      (default 172.18.48.66; same container port, same host port, dashboard host
      port --dashboard-host-port). The compatibility publishes stay, so tailscale
      serve, the LAN gateway and every other consumer keep working;
    * Edge MQTT CENTRAL_MQTT_HOST=central-mqtt (the alias unique to the central
      broker on nexolab-standalone-runtime; ``mqtt`` is carried by BOTH brokers
      there) and CENTRAL_MQTT_PORT=1883. CENTRAL_BRIDGE_CLIENT_ID is preserved.

  drop-compat (Phase 4, mode drop-compat), order
      central MQTT -> telemetry-service -> MinIO -> dashboard
    * REMOVE the compatibility publishes (the loopback ones must exist);
    * telemetry-service OBJECT_STORAGE_PUBLIC_ENDPOINT_URL = --object-storage-public-url.
    Refused unless the owner states --consumers-retargeted (tailscale serve, the
    LAN gateway and the HTTPS private origin no longer use the compatibility
    address; the tool cannot read their configuration as non-root).

Image IDs, volumes and mounts, networks and aliases, labels, restart policy,
healthcheck, user, command, entrypoint and every other environment entry stay
identical. The tool never runs ``down``, ``-v``, ``rm``, ``prune``,
``--remove-orphans``, never creates or removes volumes or networks and never
touches the Device Agent, PostgreSQL, serial devices or Modbus.

Modes:

  plan         read-only change set (--phase switch|drop-compat) from ``docker
               inspect`` (or --from-model JSON for offline review), alias hazards,
               retained compatibility-address references and external consumers.
  check        read-only preflight for --phase: lock, non-root, node, 20 GiB, a
               fresh backup receipt (#1428), Stage 2 active (dashboard build is
               not --pre-stage2-build), every container healthy, readiness,
               exclusive aliases, Docker DNS of the bridge host from the Edge broker.
  prove        render and prove the candidate + rollback Compose of every service
               of --phase against the live containers (inspect + ``docker compose
               config`` only; no up, no exec, no backup receipt); files under
               <workspace>/proofs, never the rollback source. STAGE3_PROVE_GREEN.
  execute      the switch phase; drop-compat: the Phase 4 phase. Both run check,
               write candidate + rollback Compose per service (0600 in a 0700 run
               directory), prove both with a daemon-free ``docker compose config``
               comparison and recreate in order with per-service verification; any
               failure rolls back every attempted service in reverse order and
               verifies. Finally readiness ``last_persisted_at`` must advance
               within --continuity-seconds.
  rollback     explicit verified rollback of the latest (or --run) run.

Markers: STAGE3_BACKEND_GREEN / STAGE3_DROP_COMPAT_GREEN (0),
STAGE3_ROLLED_BACK_VERIFIED (3 after a failed switch, 0 for an explicit rollback),
HARD_BLOCKER_ROLLBACK_UNVERIFIED (4), STOP <reason> (2, nothing switched).
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import ipaddress
import json
import os
import re
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

DEFAULT_WORKSPACE = "/home/nexolab/commander-workspaces/nexolab-wp2c-stage3"
DEFAULT_LOCK = "/tmp/nexolab-current-head-launch.lock"
DEFAULT_COMPAT_IP = "172.18.48.66"
LOOPBACK = "127.0.0.1"
DEFAULT_SHARED_NETWORK = "nexolab-standalone-runtime"
DEFAULT_UNTOUCHED = ("nexolab-edge-device-agent-1", "nexolab-central-postgres-1")
OBJECT_URL_ENV = "OBJECT_STORAGE_PUBLIC_ENDPOINT_URL"
BRIDGE_HOST_ENV = "CENTRAL_MQTT_HOST"
BRIDGE_PORT_ENV = "CENTRAL_MQTT_PORT"
BRIDGE_CLIENT_ENV = "CENTRAL_BRIDGE_CLIENT_ID"
GIB = 1024**3
DEFAULT_SHM = 64 * 1024 * 1024
POLL_SECONDS = 1.0
WORK_PACKAGE = "1734-wp2c-stage3"
PRE_STAGE2_BUILD = "CWBsCWWebOZGHa5YyWp18"
AGENT_CONTAINER = "nexolab-edge-device-agent-1"
AGENT_ALIAS = "edge-device-agent"


class Spec(NamedTuple):
    key: str
    container: str
    project: str
    service: str


SERVICES = (
    Spec("central-mqtt", "nexolab-central-mqtt-1", "nexolab-central", "mqtt"),
    Spec("telemetry-service", "nexolab-central-telemetry-service-1", "nexolab-central", "telemetry-service"),
    Spec("minio", "nexolab-central-minio-1", "nexolab-central", "minio"),
    Spec("dashboard", "nexolab-central-dashboard-1", "nexolab-central", "dashboard"),
    Spec("edge-mqtt", "nexolab-edge-mqtt-1", "nexolab-edge", "mqtt"),
)
BY_KEY = {spec.key: spec for spec in SERVICES}
TELEMETRY, CENTRAL_MQTT, EDGE_MQTT, DASHBOARD = (BY_KEY["telemetry-service"], BY_KEY["central-mqtt"],
                                                  BY_KEY["edge-mqtt"], BY_KEY["dashboard"])
PHASE_SERVICES = {"switch": SERVICES, "drop-compat": tuple(s for s in SERVICES if s.key != EDGE_MQTT.key)}
GREEN_MARKER = {"switch": "STAGE3_BACKEND_GREEN", "drop-compat": "STAGE3_DROP_COMPAT_GREEN"}

ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ALIAS = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
RUN_NAME = re.compile(r"^[0-9]{8}T[0-9]{6}[0-9]{6}Z$")

# HostConfig settings that must stay at their Docker default; everything else is
# translated explicitly and compared after the switch.
MUST_BE_EMPTY = (
    "VolumesFrom", "Devices", "DeviceRequests", "DeviceCgroupRules", "Privileged", "PublishAllPorts", "PidMode",
    "UTSMode", "UsernsMode", "CgroupParent", "VolumeDriver", "AutoRemove", "Cgroup", "Links",
)
HOSTCONFIG_COMPARE = (
    "PortBindings", "RestartPolicy", "NetworkMode", "Init", "Privileged", "CapAdd", "CapDrop", "SecurityOpt",
    "ExtraHosts", "Dns", "DnsSearch", "DnsOptions", "GroupAdd", "Tmpfs", "Sysctls", "Ulimits", "Memory", "MemorySwap",
    "MemoryReservation", "NanoCpus", "CpuShares", "PidsLimit", "ShmSize", "OomScoreAdj", "LogConfig", "ReadonlyRootfs",
    "Devices", "IpcMode", "PidMode", "UsernsMode", "Runtime", "PublishAllPorts",
)


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


def run(argv: list[str], timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(argv, capture_output=True, timeout=timeout, check=False, env=docker_env())
    if check and result.returncode:
        raise Stop("COMMAND_FAILED " + " ".join(argv[:6]) + ": " + result.stderr.decode(errors="replace")[-400:])
    return result


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def write_json(path: Path, value: object, exclusive: bool = False) -> None:
    write_private(path, json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", exclusive=exclusive)


def read_json(path: Path, reason: str) -> object:
    need(path.is_file() and not path.is_symlink(), reason)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise Stop(reason + " (not JSON)") from error


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def env_map(env: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in env:
        key, sep, value = item.partition("=")
        need(sep and ENV_KEY.match(key) and "\n" not in key, "UNSUPPORTED_ENV_ENTRY " + key[:40])
        need(key not in out, "DUPLICATE_ENV_KEY " + key)
        out[key] = value
    return out


# ---------------------------------------------------------------- HTTP / TCP probes

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_get(url: str, timeout: float = 5.0) -> tuple[int, bytes]:
    try:
        with _OPENER.open(url, timeout=timeout) as response:
            return response.status, response.read(1024 * 1024)
    except urllib.error.HTTPError as error:
        return error.code, error.read(64 * 1024) if error.fp else b""
    except Exception as error:  # noqa: BLE001 - every transport failure is a failed probe
        raise Stop(f"HTTP_UNAVAILABLE {url} {str(error)[:160]}") from error


def tcp_open(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def loopback_port_free(port: int) -> bool:
    return not tcp_open(LOOPBACK, port, timeout=1.0)


# ---------------------------------------------------------------- docker reads (read-only)


def inspect(name: str) -> dict:
    result = run(["docker", "inspect", "--type", "container", name], timeout=60, check=False)
    need(result.returncode == 0, "CONTAINER_NOT_FOUND " + name)
    return json.loads(result.stdout)[0]


def image_inspect(ref: str) -> dict:
    result = run(["docker", "image", "inspect", ref], timeout=60, check=False)
    need(result.returncode == 0, "IMAGE_NOT_FOUND " + ref)
    return json.loads(result.stdout)[0]


def network_members(network: str) -> dict[str, str]:
    """Container ID -> name for every container attached to ``network``."""
    result = run(["docker", "network", "inspect", network], timeout=60, check=False)
    need(result.returncode == 0, "NETWORK_NOT_FOUND " + network)
    data = json.loads(result.stdout)[0]
    return {cid: (item or {}).get("Name", "") for cid, item in (data.get("Containers") or {}).items()}


def health(container: dict) -> str:
    state = container.get("State") or {}
    if not state.get("Running"):
        return "not-running"
    return (state.get("Health") or {}).get("Status") or "running"


def wanted_health(container: dict) -> str:
    hc = (container.get("Config") or {}).get("Healthcheck") or {}
    return "healthy" if hc.get("Test") and hc["Test"] != ["NONE"] else "running"


def bindings(container: dict) -> list[tuple[str, str, str]]:
    """Sorted (container_port, host_ip, host_port) of every configured publish."""
    raw = (container.get("HostConfig") or {}).get("PortBindings") or {}
    return sorted((cport, b.get("HostIp") or "", b.get("HostPort") or "") for cport, items in raw.items() for b in (items or []))


def local_url(container: dict) -> str:
    """The loopback publish when present (after the switch), otherwise the single publish."""
    entries = bindings(container)
    loop = [e for e in entries if e[1] == LOOPBACK]
    entries = loop or entries
    need(len(entries) == 1, f"EXPECTED_ONE_PORT_BINDING {container.get('Name')} {entries}")
    _, host, port = entries[0]
    host = LOOPBACK if host in ("", "0.0.0.0") else host
    return f"http://{host}:{port}"


def readiness() -> dict:
    url = local_url(inspect(TELEMETRY.container)) + "/health/ready"
    status, body = http_get(url)
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        data = {}
    need(status == 200 and data.get("status") == "ready", f"API_NOT_READY {url} status={status} {str(data)[:200]}")
    return data


def dashboard_identity(container: dict) -> dict:
    status, body = http_get(local_url(container) + "/api/runtime-identity")
    need(status == 200, f"DASHBOARD_IDENTITY_HTTP_{status}")
    try:
        data = json.loads(body)
    except ValueError as error:
        raise Stop("DASHBOARD_IDENTITY_NOT_JSON") from error
    return {"source_commit": data.get("source_commit"), "build_id": data.get("build_id")}


def snapshots(names: list[str]) -> dict:
    entries = {}
    for name in names:
        data = inspect(name)
        need(health(data) == wanted_health(data), f"CONTAINER_UNHEALTHY {name} {health(data)}")
        entries[name] = {"container_id": data["Id"], "image_id": data["Image"],
                         "started_at": (data.get("State") or {}).get("StartedAt"), "restart_count": data.get("RestartCount", 0)}
    return entries


# ---------------------------------------------------------------- validation of the intended values


def validate_bridge_host(host: str) -> None:
    need(host, "BRIDGE_HOST_REQUIRED")
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        raise Stop("BRIDGE_HOST_IP_LITERAL_REFUSED " + host)
    need(host.lower() not in ("mqtt", "localhost"),
         f"BRIDGE_HOST_AMBIGUOUS_REFUSED {host} (both brokers carry 'mqtt' on the shared network; use central-mqtt)")
    need(ALIAS.match(host), "BRIDGE_HOST_NOT_A_DOCKER_ALIAS " + host)


def validate_object_url(url: str | None, compat_ip: str) -> None:
    need(url, "OBJECT_STORAGE_PUBLIC_URL_REQUIRED (--object-storage-public-url; no default)")
    parts = urllib.parse.urlsplit(url)
    need(not any(ch.isspace() for ch in url) and "@" not in parts.netloc, "OBJECT_STORAGE_PUBLIC_URL_INVALID")
    need(parts.scheme in ("http", "https") and parts.hostname,
         "OBJECT_STORAGE_PUBLIC_URL_NOT_ABSOLUTE (telemetry-service passes it to boto3 as endpoint_url, which needs "
         "scheme://host; a bare same-origin path would stop the service at start)")
    need(compat_ip not in url, "OBJECT_STORAGE_PUBLIC_URL_USES_COMPAT_ADDRESS")
    try:
        ip = ipaddress.ip_address(parts.hostname)
    except ValueError:
        return
    need(ip.is_loopback, "OBJECT_STORAGE_PUBLIC_URL_IP_LITERAL_REFUSED " + parts.hostname)


# ---------------------------------------------------------------- views (inspect or offline model)


def view_from_inspect(container: dict) -> dict:
    cfg, host = container.get("Config") or {}, container.get("HostConfig") or {}
    networks = (container.get("NetworkSettings") or {}).get("Networks") or {}
    return {
        "name": container["Name"].lstrip("/"), "labels": cfg.get("Labels") or {}, "image": cfg.get("Image"),
        "image_id": container.get("Image"), "env": list(cfg.get("Env") or []), "ports": host.get("PortBindings") or {},
        "networks": {n: sorted(set((e or {}).get("Aliases") or []) | set((e or {}).get("DNSNames") or []))
                     for n, e in networks.items()},
        "running": bool((container.get("State") or {}).get("Running")),
        "redacted": False,
    }


def view_from_model(item: dict) -> dict:
    return {
        "name": item["name"], "labels": item.get("labels") or {}, "image": item.get("image"), "image_id": item.get("image_id"),
        "env": list(item.get("env") or []), "ports": item.get("port_bindings") or {},
        "networks": {n: sorted((e or {}).get("aliases") or []) for n, e in (item.get("networks") or {}).items()},
        "running": None,  # a sanitized model does not prove the running state
        "redacted": True,
    }


def load_model(path: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    """(views by name, raw docker-inspect containers by name — empty for a sanitized broker model)."""
    data = read_json(path, "MODEL_NOT_READABLE " + str(path))
    if isinstance(data, dict):
        data = (data.get("result") or data).get("containers")
    need(isinstance(data, list) and data, "MODEL_HAS_NO_CONTAINERS")
    if all(isinstance(item, dict) and "Config" in item for item in data):
        raw = {item["Name"].lstrip("/"): item for item in data}
        return {name: view_from_inspect(item) for name, item in raw.items()}, raw
    return {item["name"]: view_from_model(item) for item in data}, {}


# ---------------------------------------------------------------- change set


def service_delta(spec: Spec, view: dict, args: argparse.Namespace) -> dict:
    labels = view["labels"]
    need(labels.get("com.docker.compose.project") == spec.project, f"COMPOSE_PROJECT_UNEXPECTED {spec.container}")
    need(labels.get("com.docker.compose.service") == spec.service, f"COMPOSE_SERVICE_UNEXPECTED {spec.container}")
    need(view["name"] == spec.container == f"{spec.project}-{spec.service}-1", "UNEXPECTED_CONTAINER_NAME " + view["name"])
    ports = []
    for cport, items in sorted(view["ports"].items()):
        pairs = [(b.get("HostIp") or "", b.get("HostPort") or "") for b in items or []]
        for hip, hport in pairs:
            need(hport, f"PORT_BINDING_WITHOUT_HOST_PORT {spec.container} {cport}")
            need(hip in (args.compat_ip, LOOPBACK),
                 f"UNEXPECTED_PUBLISH_ADDRESS {spec.container} {cport} {hip or '0.0.0.0'}:{hport}")
        compat = [p for p in pairs if p[0] == args.compat_ip]
        loop = [p for p in pairs if p[0] == LOOPBACK]
        need(len(compat) <= 1 and len(loop) <= 1, f"UNEXPECTED_PUBLISH_SET {spec.container} {cport} {pairs}")
        if not compat:
            continue
        target = str(args.dashboard_host_port) if spec.key == DASHBOARD.key else compat[0][1]
        if args.phase == "switch":
            if loop:  # already switched: no change (a blocker for execute)
                need(loop[0][1] == target, f"LOOPBACK_BINDING_UNEXPECTED {spec.container} {cport} {loop[0][1]}")
                continue
            ports.append({"container_port": cport, "action": "add", "binding": [LOOPBACK, target],
                          "keep": list(compat[0])})
        else:
            need(loop, f"LOOPBACK_BINDING_MISSING {spec.container} {cport} (run execute, the switch phase, first)")
            ports.append({"container_port": cport, "action": "remove", "binding": list(compat[0]),
                          "keep": list(loop[0])})
    env = env_map(view["env"]) if not view["redacted"] else dict(item.partition("=")[::2] for item in view["env"])
    wanted: dict[str, str] = {}
    if spec.key == EDGE_MQTT.key:
        need(env.get(BRIDGE_CLIENT_ENV) and env[BRIDGE_CLIENT_ENV] not in ("<set>", "[REDACTED]"), "BRIDGE_CLIENT_ID_MISSING")
        bridge = {BRIDGE_HOST_ENV: args.bridge_host, BRIDGE_PORT_ENV: str(args.bridge_port)}
        if args.phase == "switch":
            wanted.update(bridge)
        else:
            need(all(env.get(k) == v for k, v in bridge.items()),
                 f"EDGE_BRIDGE_NOT_SWITCHED {env.get(BRIDGE_HOST_ENV)}:{env.get(BRIDGE_PORT_ENV)} (run execute first)")
    if spec.key == TELEMETRY.key and args.phase == "drop-compat":
        wanted[OBJECT_URL_ENV] = args.object_storage_public_url
    changes = {}
    for key, value in wanted.items():
        need(key in env, f"ENV_KEY_MISSING {spec.container} {key}")
        if env[key] != value:
            changes[key] = [env[key], value]
    # OBJECT_STORAGE_PUBLIC_ENDPOINT_URL is owned by drop-compat; it stays valid while the compat publish exists.
    handled = set(wanted) | ({OBJECT_URL_ENV} if spec.key == TELEMETRY.key else set())
    retained = sorted(k for k, v in env.items() if k not in handled and args.compat_ip in v)
    preserved = {BRIDGE_CLIENT_ENV: env[BRIDGE_CLIENT_ENV]} if spec.key == EDGE_MQTT.key else {}
    return {"key": spec.key, "container": spec.container, "project": spec.project, "service": spec.service,
            "image_id": view["image_id"], "ports": ports, "env": changes, "preserved": preserved,
            "retained_compat_env": retained}


def alias_analysis(views: dict[str, dict], args: argparse.Namespace) -> dict:
    carriers: dict[str, list[str]] = {}
    for name, view in sorted(views.items()):
        for alias in view["networks"].get(args.shared_network, []):
            carriers.setdefault(alias, []).append(name)
    ambiguous = {alias: names for alias, names in carriers.items() if len(names) > 1}
    consumers = []
    for name, view in sorted(views.items()):
        if args.shared_network not in view["networks"]:
            continue
        for item in view["env"]:
            key, _, value = item.partition("=")
            if key.endswith("_HOST") and value in ambiguous:
                consumers.append(f"{name} {key}={value}")
    # Aliases that must resolve to exactly one container: another RUNNING carrier is a blocker;
    # a carrier whose running state is unknown (offline model) is reported as unproven.
    intruders, unproven = [], []
    for alias, owner in ((args.bridge_host, CENTRAL_MQTT.container), (AGENT_ALIAS, AGENT_CONTAINER)):
        for name in carriers.get(alias, []):
            if name == owner:
                continue
            if views[name].get("running"):
                intruders.append(f"{alias}:{name}")
            elif views[name].get("running") is None:
                unproven.append(f"{alias}:{name}")
    return {"bridge_host_carriers": carriers.get(args.bridge_host, []), "ambiguous_aliases": ambiguous,
            "ambiguous_consumers": consumers, "exclusive_alias_intruders": intruders,
            "exclusive_alias_unproven": unproven}


def external_consumers(args: argparse.Namespace) -> list[str]:
    ip, port = args.compat_ip, args.dashboard_host_port
    return [
        f"tailscale serve :8443 /api -> http://{ip}:8082/api: retarget to http://127.0.0.1:8082/api",
        f"tailscale serve :8444 -> http://{ip}:3000: retarget to http://127.0.0.1:{port} or the LAN gateway",
        "nexolab-lan-gateway (port 80): upstreams to loopback, then remove the temporary compatibility allow flag",
        "HTTPS external UI private_api_origin: http://127.0.0.1:8082",
        "nexolab-compat-address.service (nxcompat0): retire only after drop-compat is green (Phase 4)",
        f"Compose files of record still name {ip}; a later 'up' from them reverts this stage (update the catalog separately)",
        "wp2c-stage2-frontend.py rollback.compose.yaml was recorded before Stage 3 and publishes the dashboard on the "
        "compatibility address only",
    ]


def build_plan(views: dict[str, dict], args: argparse.Namespace) -> dict:
    deltas = []
    for spec in SERVICES:
        need(spec.container in views, "CONTAINER_NOT_FOUND " + spec.container)
        deltas.append(service_delta(spec, views[spec.container], args))
    keys = {spec.key for spec in PHASE_SERVICES[args.phase]}
    services = [d for d in deltas if d["key"] in keys]
    aliases = alias_analysis(views, args)
    blockers = []
    if CENTRAL_MQTT.container not in aliases["bridge_host_carriers"]:
        blockers.append(f"BRIDGE_HOST_NOT_ON_CENTRAL_MQTT {args.bridge_host}")
    if aliases["exclusive_alias_intruders"]:
        blockers.append("EXCLUSIVE_ALIAS_CARRIED_BY_OTHER_RUNNING_CONTAINER "
                        + ", ".join(aliases["exclusive_alias_intruders"]))
    bridge_unproven = [u for u in aliases["exclusive_alias_unproven"] if u.startswith(args.bridge_host + ":")]
    if bridge_unproven:
        blockers.append("BRIDGE_HOST_NOT_UNIQUE_TO_CENTRAL_MQTT " + ", ".join(bridge_unproven))
    for spec in (CENTRAL_MQTT, EDGE_MQTT):
        if args.shared_network not in views[spec.container]["networks"]:
            blockers.append(f"NOT_ON_SHARED_NETWORK {spec.container} {args.shared_network}")
    central_ports = set(views[CENTRAL_MQTT.container]["ports"])
    if central_ports != {f"{args.bridge_port}/tcp"}:
        blockers.append(f"BRIDGE_PORT_NOT_CENTRAL_CONTAINER_PORT {args.bridge_port} central={sorted(central_ports)}")
    unacknowledged = [f"{d['container']} {k}" for d in deltas for k in d["retained_compat_env"] if k not in args.retain_env]
    for delta in services:
        if not delta["ports"] and not delta["env"]:
            blockers.append(f"SERVICE_ALREADY_SWITCHED_OR_UNEXPECTED {delta['key']} (phase {args.phase})")
    if unacknowledged:
        blockers.append("UNACKNOWLEDGED_COMPAT_IP_REFERENCE " + ", ".join(unacknowledged) + " (review; --retain-env KEY)")
    return {"phase": args.phase, "compat_ip": args.compat_ip, "order": [s.key for s in PHASE_SERVICES[args.phase]],
            "services": services, "aliases": aliases, "external_consumers": external_consumers(args),
            "blockers": blockers, "env_values_redacted": any(v["redacted"] for v in views.values())}


def print_plan(plan: dict) -> None:
    print(f"STAGE3_PLAN phase={plan['phase']} compat_ip={plan['compat_ip']} order={' -> '.join(plan['order'])}",
          flush=True)
    for index, item in enumerate(plan["services"], 1):
        print(f"[{index}] {item['key']}: {item['container']} (project {item['project']}, service {item['service']}, "
              f"image {item['image_id']})")
        for port in item["ports"]:
            print(f"    publish {port['container_port']}: {port['action']} {':'.join(port['binding'])} "
                  f"(keep {':'.join(port['keep'])})")
        for key, (old, new) in sorted(item["env"].items()):
            print(f"    env {key}: {old} -> {new}")
        for key, value in item["preserved"].items():
            print(f"    preserved {key}={value}")
        for key in item["retained_compat_env"]:
            print(f"    RETAINED compat-address reference (unchanged) env {key}")
        print("    unchanged: image, volumes/mounts, networks+aliases, labels, restart, healthcheck, user, command, "
              "entrypoint, every other env entry")
    for alias, names in sorted(plan["aliases"]["ambiguous_aliases"].items()):
        print(f"HAZARD alias '{alias}' on the shared network is carried by {', '.join(names)}")
    for consumer in plan["aliases"]["ambiguous_consumers"]:
        print(f"HAZARD ambiguous-alias consumer (unchanged by Stage 3): {consumer}")
    for item in plan["aliases"]["exclusive_alias_unproven"]:
        print(f"HAZARD exclusive alias also carried by a container of unknown running state: {item}")
    print(f"BRIDGE_HOST_CARRIERS {plan['aliases']['bridge_host_carriers']}")
    if plan["env_values_redacted"]:
        print("NOTE offline model: secret env values are redacted; retained references can only be proven from "
              "docker inspect")
    if plan["phase"] == "switch":
        print("EXTERNAL consumers keep working through the compatibility address (dual publish); retarget them to "
              "loopback before drop-compat (owner step, NOT changed by this tool):")
    else:
        print("EXTERNAL consumers must already be retargeted (drop-compat requires --consumers-retargeted):")
    for line in plan["external_consumers"]:
        print("  - " + line)
    for blocker in plan["blockers"]:
        print("BLOCKER " + blocker)
    sys.stdout.flush()


# ---------------------------------------------------------------- compose model (from docker inspect)


def compose_labels(container: dict) -> dict:
    return {k: v for k, v in ((container.get("Config") or {}).get("Labels") or {}).items() if k.startswith("com.docker.compose.")}


def user_labels(container: dict, image: dict) -> dict:
    image_labels = (image.get("Config") or {}).get("Labels") or {}
    labels = (container.get("Config") or {}).get("Labels") or {}
    return {k: v for k, v in labels.items() if not k.startswith("com.docker.compose.") and image_labels.get(k) != v}


def auto_aliases(container: dict) -> set[str]:
    return {compose_labels(container).get("com.docker.compose.service", ""), container["Name"].lstrip("/"), container["Id"][:12]}


def restart_string(host: dict) -> str:
    restart = host.get("RestartPolicy") or {}
    if restart.get("Name") and restart["Name"] != "no":
        retries = restart.get("MaximumRetryCount") or 0
        return f"on-failure:{retries}" if restart["Name"] == "on-failure" and retries else restart["Name"]
    return "no"


def duration(ns: int | None) -> str | None:
    return f"{int(ns) // 1_000_000}ms" if ns else None


def service_model(container: dict, image: dict, compat_ip: str) -> dict:
    """Compose document equivalent to the inspected container (fail closed on the unknown)."""
    cfg, host, img = container["Config"], container["HostConfig"], image.get("Config") or {}
    name = container["Name"].lstrip("/")
    service = compose_labels(container).get("com.docker.compose.service")
    for key in MUST_BE_EMPTY:
        need(not host.get(key), f"UNSUPPORTED_CONTAINER_SETTING {name} {key}={host.get(key)!r}")
    need(host.get("IpcMode") in (None, "", "private", "shareable"), f"UNSUPPORTED_CONTAINER_SETTING {name} IpcMode")
    need(host.get("Runtime") in (None, "", "runc"), f"UNSUPPORTED_CONTAINER_SETTING {name} Runtime")
    networks = (container.get("NetworkSettings") or {}).get("Networks") or {}
    need(networks and host.get("NetworkMode") in networks, f"UNSUPPORTED_NETWORK_MODE {name} {host.get('NetworkMode')}")
    # Compose attaches the alphabetically first network first; it must be the recorded primary network.
    need(sorted(networks)[0] == host.get("NetworkMode"), f"PRIMARY_NETWORK_NOT_FIRST {name} {host.get('NetworkMode')}")
    scan = json.dumps([cfg.get("Cmd"), cfg.get("Entrypoint"), cfg.get("Healthcheck"), host.get("ExtraHosts")])
    need(compat_ip not in scan, f"UNHANDLED_COMPAT_IP_REFERENCE {name} command/entrypoint/healthcheck/extra_hosts")

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
    env_map(env)
    svc["environment"] = env
    labels = user_labels(container, image)
    if labels:
        svc["labels"] = labels
    extra_expose = sorted(set(cfg.get("ExposedPorts") or {}) - set(img.get("ExposedPorts") or {}) - set(host.get("PortBindings") or {}))
    if extra_expose:
        svc["expose"] = extra_expose
    svc["ports"] = [f"{hip}:{hport}:{cport}" if hip else f"{hport}:{cport}" for cport, hip, hport in bindings(container)]
    auto = auto_aliases(container)
    svc["networks"] = {}
    for net in sorted(networks):
        endpoint = networks[net] or {}
        ipam = endpoint.get("IPAMConfig") or {}
        need(not ipam.get("IPv4Address") and not ipam.get("IPv6Address"), f"UNSUPPORTED_STATIC_IP {name} {net}")
        aliases = sorted(set(endpoint.get("Aliases") or []) - auto)
        svc["networks"][net] = {"aliases": aliases} if aliases else {}
    volumes, top_volumes = [], {}
    targets = set()
    for mount in container.get("Mounts") or []:
        kind, target = mount.get("Type"), mount.get("Destination")
        need(target and target not in targets, f"DUPLICATE_MOUNT_TARGET {name} {target}")
        targets.add(target)
        if kind == "volume":
            need(mount.get("Name") and mount.get("Driver") in (None, "", "local"), f"UNSUPPORTED_VOLUME {name} {target}")
            entry = {"type": "volume", "source": mount["Name"], "target": target}
            top_volumes[mount["Name"]] = {"name": mount["Name"], "external": True}
        elif kind == "bind":
            need(mount.get("Source", "").startswith("/") and mount.get("Propagation") in (None, "", "rprivate"),
                 f"UNSUPPORTED_BIND {name} {target}")
            entry = {"type": "bind", "source": mount["Source"], "target": target, "bind": {"create_host_path": False}}
        else:
            raise Stop(f"UNSUPPORTED_MOUNT_TYPE {name} {kind} {target}")
        if not mount.get("RW", True):
            entry["read_only"] = True
        volumes.append(entry)
    for path in (img.get("Volumes") or {}):
        need(path in targets, f"IMAGE_VOLUME_NOT_MOUNTED {name} {path} (an anonymous volume would be created)")
    if volumes:
        svc["volumes"] = sorted(volumes, key=lambda v: v["target"])
    svc["restart"] = restart_string(host)
    if host.get("Init"):
        svc["init"] = True
    hc = cfg.get("Healthcheck")
    if hc and hc.get("Test"):
        if hc["Test"] == ["NONE"]:
            svc["healthcheck"] = {"disable": True}
        else:
            block: dict = {"test": hc["Test"]}
            for key, field in (("Interval", "interval"), ("Timeout", "timeout"), ("StartPeriod", "start_period"),
                               ("StartInterval", "start_interval")):
                if duration(hc.get(key)):
                    block[field] = duration(hc.get(key))
            if hc.get("Retries"):
                block["retries"] = int(hc["Retries"])
            svc["healthcheck"] = block
    if host.get("ReadonlyRootfs"):
        svc["read_only"] = True
    for key, field in (("CapAdd", "cap_add"), ("CapDrop", "cap_drop"), ("SecurityOpt", "security_opt"),
                       ("ExtraHosts", "extra_hosts"), ("Dns", "dns"), ("DnsSearch", "dns_search"), ("DnsOptions", "dns_opt"),
                       ("GroupAdd", "group_add")):
        if host.get(key):
            svc[field] = list(host[key])
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
    document: dict = {"services": {service: svc},
                      "networks": {net: {"name": net, "external": True} for net in sorted(networks)}}
    if top_volumes:
        document["volumes"] = dict(sorted(top_volumes.items()))
    return document


def candidate_document(document: dict, spec: Spec, delta: dict) -> dict:
    cand = copy.deepcopy(document)
    svc = cand["services"][spec.service]
    for port in delta["ports"]:
        entry = f"{port['binding'][0]}:{port['binding'][1]}:{port['container_port']}"
        if port["action"] == "add":
            need(entry not in svc["ports"], f"PORT_DELTA_NOT_APPLICABLE {spec.key} {entry}")
            svc["ports"].append(entry)
        else:
            need(svc["ports"].count(entry) == 1, f"PORT_DELTA_NOT_APPLICABLE {spec.key} {entry}")
            svc["ports"].remove(entry)
    for key, (old, new) in delta["env"].items():
        entry = f"{key}={old}"
        need(svc["environment"].count(entry) == 1, f"ENV_DELTA_NOT_APPLICABLE {spec.key} {key}")
        svc["environment"][svc["environment"].index(entry)] = f"{key}={new}"
    return cand


def model_changes(rollback: dict, candidate: dict, spec: Spec) -> list[str]:
    """Paths that differ between the two documents (proof that only the deltas change)."""
    out = []
    if {k: v for k, v in rollback.items() if k != "services"} != {k: v for k, v in candidate.items() if k != "services"}:
        out.append("top-level")
    rb, cd = rollback["services"][spec.service], candidate["services"][spec.service]
    for key in sorted(set(rb) | set(cd)):
        if key == "environment":
            old, new = env_map(rb[key]), env_map(cd[key])
            out += [f"environment.{k}" for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)]
        elif key == "ports":
            out += [f"ports:{p}" for p in sorted(set(rb[key]) ^ set(cd[key]))]
        elif rb.get(key) != cd.get(key):
            out.append(key)
    return out


def expected_model_changes(spec: Spec, delta: dict) -> list[str]:
    out = [f"environment.{k}" for k in sorted(delta["env"])]
    out += [f"ports:{p['binding'][0]}:{p['binding'][1]}:{p['container_port']}" for p in delta["ports"]]
    return sorted(out)


def _scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    need(isinstance(value, str), f"UNSUPPORTED_YAML_VALUE {type(value).__name__}")
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


def render_compose(document: dict, spec: Spec, title: str) -> str:
    header = (
        f"# {title}\n# Generated by wp2c-stage3-backend.py from `docker inspect` at {utc_now()}.\n"
        "# Contains runtime environment values: keep 0600, never copy off the host.\n"
        f"# Use only with: docker compose --file <this> --project-name {spec.project} up --no-deps --no-build "
        f"--pull never --force-recreate --detach {spec.service}\n"
    )
    return header + to_yaml(document) + "\n"


# ---------------------------------------------------------------- effective settings (post-switch comparison)


def _norm(value: object) -> object:
    if isinstance(value, dict):
        out = {k: _norm(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, [], {}, "", 0, False)}
    if isinstance(value, list):
        return [_norm(v) for v in value]
    return value


def effective(container: dict) -> dict:
    """Settings that must match between the recorded and the recreated container (env values hashed)."""
    cfg, host = container.get("Config") or {}, container.get("HostConfig") or {}
    auto = auto_aliases(container)
    networks = (container.get("NetworkSettings") or {}).get("Networks") or {}
    mounts = sorted([m.get("Type") or "", (m.get("Name") if m.get("Type") == "volume" else m.get("Source")) or "",
                     m.get("Destination") or "", bool(m.get("RW", True))] for m in container.get("Mounts") or [])
    return {
        "image_id": container.get("Image"),
        "config_image": cfg.get("Image"),
        "env": {k: digest(v) for k, v in env_map(list(cfg.get("Env") or [])).items()},
        "user": cfg.get("User") or "",
        "cmd": cfg.get("Cmd"),
        "entrypoint": cfg.get("Entrypoint"),
        "working_dir": cfg.get("WorkingDir") or "",
        "healthcheck": _norm(cfg.get("Healthcheck") or {}),
        "stop_signal": cfg.get("StopSignal") or "",
        "stop_timeout": cfg.get("StopTimeout"),
        "exposed_ports": sorted(cfg.get("ExposedPorts") or {}),
        "labels": {k: v for k, v in (cfg.get("Labels") or {}).items() if not k.startswith("com.docker.compose.")},
        "networks": {n: sorted(set((e or {}).get("Aliases") or []) - auto) for n, e in sorted(networks.items())},
        "mounts": mounts,
        "host_config": _norm({k: sorted_bindings(host.get(k)) if k == "PortBindings" else host.get(k)
                              for k in HOSTCONFIG_COMPARE}),
    }


def sorted_bindings(port_bindings: dict | None) -> dict:
    return {cport: sorted(items or [], key=lambda b: (b.get("HostIp") or "", b.get("HostPort") or ""))
            for cport, items in (port_bindings or {}).items()}


def expected_candidate(baseline: dict, delta: dict) -> dict:
    exp = copy.deepcopy(baseline)
    for key, (_, new) in delta["env"].items():
        exp["env"][key] = digest(new)
    port_bindings = exp["host_config"].setdefault("PortBindings", {})
    for port in delta["ports"]:
        items = port_bindings.setdefault(port["container_port"], [])
        binding = {"HostIp": port["binding"][0], "HostPort": port["binding"][1]}
        if port["action"] == "add":
            need(binding not in items, f"PORT_DELTA_ALREADY_IN_BASELINE {port}")
            items.append(binding)
        else:
            need(binding in items, f"PORT_DELTA_NOT_IN_BASELINE {port}")
            items.remove(binding)
    exp["host_config"]["PortBindings"] = sorted_bindings(port_bindings)
    return exp


def differences(expected: dict, actual: dict) -> list[str]:
    diffs = []
    for key in expected:
        if key in ("host_config", "env"):
            continue
        if expected[key] != actual.get(key):
            diffs.append(key)
    ee, ae = expected["env"], actual.get("env") or {}
    diffs += [f"env.{k}" for k in sorted(set(ee) | set(ae)) if ee.get(k) != ae.get(k)]
    eh, ah = expected["host_config"], actual.get("host_config") or {}
    diffs += [f"HostConfig.{k}" for k in sorted(set(eh) | set(ah)) if eh.get(k) != ah.get(k)]
    return diffs


# ---------------------------------------------------------------- compose config fidelity (daemon-free)


def _unescape(value: object) -> object:
    if isinstance(value, str):
        return value.replace("$$", "$")
    if isinstance(value, list):
        return [_unescape(v) for v in value]
    if isinstance(value, dict):
        return {k: _unescape(v) for k, v in value.items()}
    return value


def compose_config(path: Path, spec: Spec) -> dict:
    result = run(["docker", "compose", "--file", str(path), "--project-name", spec.project, "config", "--format", "json"],
                 timeout=60)
    try:
        return json.loads(result.stdout)
    except ValueError as error:
        raise Stop("COMPOSE_CONFIG_NOT_JSON " + path.name) from error


def config_vs_container(config: dict, document: dict, container: dict, image: dict, spec: Spec) -> list[str]:
    """Prove the rendered rollback configuration reproduces the inspected container."""
    svc = (config.get("services") or {}).get(spec.service)
    need(isinstance(svc, dict), f"COMPOSE_CONFIG_SERVICE_MISSING {spec.key}")
    model = document["services"][spec.service]
    cfg, host = container["Config"], container["HostConfig"]
    diffs = []
    if svc.get("image") != cfg.get("Image"):
        diffs.append("image")
    env = {k: "" if v is None else str(_unescape(v)) for k, v in (svc.get("environment") or {}).items()}
    if env != env_map(list(cfg.get("Env") or [])):
        diffs.append("environment")
    ports = sorted((f"{p.get('target')}/{p.get('protocol') or 'tcp'}", p.get("host_ip") or "", str(p.get("published") or ""))
                   for p in svc.get("ports") or [])
    if ports != bindings(container):
        diffs.append("ports")
    auto = auto_aliases(container)
    nets = {n: sorted(set((v or {}).get("aliases") or [])) for n, v in (svc.get("networks") or {}).items()}
    want = {n: sorted(set((e or {}).get("Aliases") or []) - auto) for n, e in container["NetworkSettings"]["Networks"].items()}
    if nets != want:
        diffs.append("networks")
    vols = sorted([v.get("type"), v.get("source"), v.get("target"), bool(v.get("read_only"))] for v in svc.get("volumes") or [])
    mounts = sorted([m["Type"], m["Name"] if m["Type"] == "volume" else m["Source"], m["Destination"], not m.get("RW", True)]
                    for m in container.get("Mounts") or [])
    if vols != mounts:
        diffs.append("volumes")
    if (svc.get("restart") or "no") != restart_string(host):
        diffs.append("restart")
    if _unescape(svc.get("labels") or {}) != user_labels(container, image):
        diffs.append("labels")
    for key in ("user", "entrypoint", "command", "working_dir"):
        if key in model and _unescape(svc.get(key)) != model[key]:
            diffs.append(key)
    if "healthcheck" in model and "test" in model["healthcheck"]:
        if _unescape((svc.get("healthcheck") or {}).get("test")) != model["healthcheck"]["test"]:
            diffs.append("healthcheck")
    for net in want:
        if not ((config.get("networks") or {}).get(net) or {}).get("external"):
            diffs.append(f"network-not-external:{net}")
    for volume in document.get("volumes") or {}:
        if not ((config.get("volumes") or {}).get(volume) or {}).get("external"):
            diffs.append(f"volume-not-external:{volume}")
    return diffs


def config_ports(svc: dict) -> list[tuple[str, str, str, str]]:
    return sorted((str(p.get("target")), p.get("protocol") or "tcp", p.get("host_ip") or "",
                   str(p.get("published") or "")) for p in svc.get("ports") or [])


def candidate_config_matches(rollback: dict, candidate: dict, spec: Spec, delta: dict) -> bool:
    """The rendered candidate equals the rendered rollback plus exactly the intended deltas."""
    exp, act = copy.deepcopy(rollback), copy.deepcopy(candidate)
    svc = exp["services"][spec.service]
    for key, (_, new) in delta["env"].items():
        svc["environment"][key] = new
    ports = config_ports(svc)
    for port in delta["ports"]:
        target, _, proto = port["container_port"].partition("/")
        entry = (target, proto or "tcp", port["binding"][0], port["binding"][1])
        if port["action"] == "add":
            need(entry not in ports, f"CONFIG_PORT_DELTA_NOT_APPLICABLE {spec.key} {entry}")
            ports.append(entry)
        else:
            need(entry in ports, f"CONFIG_PORT_DELTA_NOT_APPLICABLE {spec.key} {entry}")
            ports.remove(entry)
    svc["ports"] = sorted(ports)
    act_svc = (act.get("services") or {}).get(spec.service)
    need(isinstance(act_svc, dict), f"COMPOSE_CONFIG_SERVICE_MISSING {spec.key}")
    act_svc["ports"] = config_ports(act_svc)
    return exp == act


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


def identity_checks(args: argparse.Namespace) -> None:
    need(os.geteuid() != 0, "RUN_AS_OPERATOR_NONROOT")
    need(os.uname().nodename.split(".")[0] == args.expect_node, f"WRONG_NODE {os.uname().nodename} expected={args.expect_node}")


def disk_check(args: argparse.Namespace) -> None:
    paths = [Path(args.workspace)] + ([Path(args.docker_root)] if args.docker_root and Path(args.docker_root).exists() else [])
    for path in paths:
        need(free_bytes(path) >= args.reserve_gib * GIB, f"DISK_RESERVE_{args.reserve_gib}GIB_FAILED {path}")


def workspace(args: argparse.Namespace) -> Path:
    path = Path(args.workspace)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    need(not path.is_symlink() and path.stat().st_uid == os.geteuid(), "WORKSPACE_NOT_OWNED " + str(path))
    os.chmod(path, 0o700)
    return path


def _receipt_time(data: dict, path: Path) -> datetime:
    for key in ("completed_at", "finished_at", "created_at"):
        value = data.get(key)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise Stop(f"BACKUP_RECEIPT_TIMESTAMP_INVALID {key}") from None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def verify_backup_receipt(args: argparse.Namespace) -> dict:
    """#1428 gate: a fresh backup receipt must exist before any backend container is recreated."""
    need(args.backup_receipt, "BACKUP_RECEIPT_REQUIRED (--backup-receipt, #1428)")
    path = Path(args.backup_receipt)
    need(path.is_file() and not path.is_symlink(), "BACKUP_RECEIPT_MISSING " + str(path))
    data = read_json(path, "BACKUP_RECEIPT_NOT_JSON " + str(path))
    need(isinstance(data, dict), "BACKUP_RECEIPT_NOT_AN_OBJECT")
    status = data.get("status")
    need(isinstance(status, str) and status.strip(), "BACKUP_RECEIPT_STATUS_MISSING")
    need(not re.search(r"FAIL|ERROR|ABORT", status.upper()), "BACKUP_RECEIPT_STATUS_FAILED " + status)
    when = _receipt_time(data, path)
    age = datetime.now(timezone.utc) - when
    need(age >= timedelta(minutes=-5), "BACKUP_RECEIPT_FROM_THE_FUTURE")
    need(age <= timedelta(hours=args.max_backup_age_hours),
         f"BACKUP_RECEIPT_STALE age={age.total_seconds() / 3600:.1f}h max={args.max_backup_age_hours}h")
    return {"path": str(path), "sha256": sha256_file(path), "status": status, "timestamp": when.isoformat(),
            "age_hours": round(age.total_seconds() / 3600, 2)}


def dns_probe(container: str, host: str, expected_ip: str) -> None:
    result = run(["docker", "exec", container, "getent", "hosts", host], timeout=30, check=False)
    first = result.stdout.decode(errors="replace").split()
    need(result.returncode == 0 and first, f"DOCKER_DNS_FAILED {host} from {container} rc={result.returncode}")
    need(first[0] == expected_ip, f"DOCKER_DNS_UNEXPECTED {host} -> {first[0]} expected {expected_ip}")


# ---------------------------------------------------------------- read-only preflight


def live_state(args: argparse.Namespace) -> dict:
    """Inspect, derive every compose model in memory and prove the change set (no writes)."""
    containers = {spec.key: inspect(spec.container) for spec in SERVICES}
    images = {}
    for spec in SERVICES:
        container = containers[spec.key]
        images[spec.key] = image_inspect(container["Image"])
        need(image_inspect(container["Config"]["Image"])["Id"] == container["Image"],
             f"IMAGE_TAG_MOVED {spec.container} {container['Config']['Image']} no longer names the running image")
    views = {c["Name"].lstrip("/"): view_from_inspect(c) for c in containers.values()}
    members = network_members(args.shared_network)
    for cid, name in members.items():
        if name not in views:
            views[name] = view_from_inspect(inspect(cid))
    plan = build_plan(views, args)
    models = {}
    for delta in plan["services"]:
        spec = BY_KEY[delta["key"]]
        rollback = service_model(containers[spec.key], images[spec.key], args.compat_ip)
        candidate = candidate_document(rollback, spec, delta)
        changes = sorted(model_changes(rollback, candidate, spec))
        need(changes == expected_model_changes(spec, delta), f"MODEL_DELTA_MISMATCH {spec.key} {changes}")
        models[spec.key] = {"rollback": rollback, "candidate": candidate}
    central = containers[CENTRAL_MQTT.key]
    endpoint = ((central.get("NetworkSettings") or {}).get("Networks") or {}).get(args.shared_network) or {}
    return {"containers": containers, "images": images, "plan": plan, "models": models,
            "central_shared_ip": endpoint.get("IPAddress") or ""}


def phase_inputs(args: argparse.Namespace) -> None:
    validate_bridge_host(args.bridge_host)
    if args.phase == "drop-compat":
        validate_object_url(args.object_storage_public_url, args.compat_ip)
    else:
        need(not args.object_storage_public_url,
             "OBJECT_STORAGE_PUBLIC_URL_IS_DROP_COMPAT_ONLY (the switch keeps the current value while dual-publishing)")


def preflight(args: argparse.Namespace) -> dict:
    identity_checks(args)
    disk_check(args)
    phase_inputs(args)
    if args.phase == "drop-compat":
        need(args.consumers_retargeted,
             "CONSUMERS_NOT_RETARGETED (retarget tailscale serve, the LAN gateway upstreams and the HTTPS private origin "
             "to loopback, then pass --consumers-retargeted)")
    receipt = verify_backup_receipt(args)
    print(f"BACKUP_RECEIPT_OK status={receipt['status']} age_hours={receipt['age_hours']} sha256={receipt['sha256'][:16]}",
          flush=True)
    state = live_state(args)
    print_plan(state["plan"])
    need(not state["plan"]["blockers"], "PLAN_BLOCKERS " + "; ".join(state["plan"]["blockers"]))
    for spec in SERVICES:
        container = state["containers"][spec.key]
        need(health(container) == wanted_health(container), f"CONTAINER_UNHEALTHY {spec.container} {health(container)}")
    untouched = snapshots(args.untouched)
    for delta in state["plan"]["services"]:
        for port in delta["ports"]:
            if port["action"] == "add":
                need(loopback_port_free(int(port["binding"][1])), f"LOOPBACK_PORT_IN_USE {port['binding'][1]} ({delta['key']})")
    need(state["central_shared_ip"], "CENTRAL_MQTT_SHARED_NETWORK_IP_UNKNOWN")
    dns_probe(EDGE_MQTT.container, args.bridge_host, state["central_shared_ip"])
    print(f"BRIDGE_DNS_OK {args.bridge_host} -> {state['central_shared_ip']} from {EDGE_MQTT.container}", flush=True)
    ready = readiness()
    dash = dashboard_identity(state["containers"][DASHBOARD.key])
    need(dash.get("build_id") and dash["build_id"] != args.pre_stage2_build,
         f"STAGE2_NOT_ACTIVE dashboard build {dash.get('build_id')} (Stage 3 runs strictly after Stage 2 execute)")
    print(f"READINESS_OK last_persisted_at={ready.get('last_persisted_at')} dashboard={dash}", flush=True)
    state.update(receipt=receipt, untouched=untouched, readiness_before=ready, dashboard_identity=dash)
    return state


# ---------------------------------------------------------------- switching


def compose_up_argv(path: Path, spec: Spec) -> list[str]:
    # No --remove-orphans, no down, no volumes: only the named service is recreated.
    return ["docker", "compose", "--file", str(path), "--project-name", spec.project, "up", "--no-deps", "--no-build",
            "--pull", "never", "--force-recreate", "--detach", spec.service]


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def last_persisted() -> datetime | None:
    try:
        return parse_ts(readiness().get("last_persisted_at"))
    except Stop:
        return None


def continuity(args: argparse.Namespace, floor: datetime | None) -> str:
    deadline = time.monotonic() + args.continuity_seconds
    last = "unknown"
    while True:
        try:
            value = readiness().get("last_persisted_at")
            last = str(value)
            parsed = parse_ts(value)
            if parsed is not None and (floor is None or parsed > floor):
                return value
        except Stop as error:
            last = str(error)[:200]
        if time.monotonic() >= deadline:
            raise Stop(f"TELEMETRY_CONTINUITY_NOT_PROVEN last_persisted_at did not advance past {floor} within "
                       f"{args.continuity_seconds}s (last {last})")
        time.sleep(POLL_SECONDS)


def verify_service(spec: Spec, expected: dict, args: argparse.Namespace, ctx: dict, *, candidate: bool) -> dict:
    deadline = time.monotonic() + args.wait_seconds
    last = "not started"
    container: dict | None = None
    while time.monotonic() < deadline:
        try:
            container = inspect(spec.container)
            need(container.get("Image") == expected["image_id"], "IMAGE_NOT_EXPECTED")
            need(health(container) == wanted_health(container), f"NOT_YET_HEALTHY {health(container)}")
            break
        except Stop as error:
            last, container = str(error), None
            time.sleep(POLL_SECONDS)
    need(container is not None, f"SERVICE_NOT_HEALTHY {spec.key} {last[:300]}")
    diffs = differences(expected, effective(container))
    need(not diffs, f"RECREATED_SETTINGS_DIFFER {spec.key} {diffs}")
    while True:
        try:
            for _, host, port in bindings(container):
                need(tcp_open(host or LOOPBACK, int(port)), f"PUBLISH_NOT_LISTENING {host}:{port}")
            if spec.key in (CENTRAL_MQTT.key, TELEMETRY.key):
                readiness()
            if spec.key == DASHBOARD.key and ctx.get("dashboard_identity"):
                need(dashboard_identity(container) == ctx["dashboard_identity"], "DASHBOARD_IDENTITY_CHANGED")
            if spec.key == EDGE_MQTT.key and candidate:
                dns_probe(spec.container, args.bridge_host, ctx["central_shared_ip"])
            return container
        except Stop as error:
            if time.monotonic() >= deadline:
                raise Stop(f"SERVICE_PROBE_FAILED {spec.key} {str(error)[:300]}") from error
            time.sleep(POLL_SECONDS)


def record(run_dir: Path, report: dict, kind: str) -> Path:
    path = run_dir / f"{kind}-report-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    write_json(path, report, exclusive=True)
    print("REPORT_PATH " + str(path), flush=True)
    return path


def rollback_chain(args: argparse.Namespace, manifest: dict, run_dir: Path, keys: list[str], ctx: dict,
                   report: dict, kind: str) -> int:
    floor_values = [parse_ts((manifest.get("readiness_before") or {}).get("last_persisted_at")), last_persisted()]
    floors = [v for v in floor_values if v is not None]
    floor = max(floors) if floors else None
    errors, done = [], []
    for key in reversed(keys):
        spec, entry = BY_KEY[key], manifest["services"][key]
        try:
            run(compose_up_argv(run_dir / entry["rollback_file"], spec), timeout=300)
            verify_service(spec, entry["baseline_effective"], args, ctx, candidate=False)
            done.append(key)
            print(f"STAGE3_SERVICE_ROLLED_BACK {key}", flush=True)
        except Exception as error:  # noqa: BLE001 - continue with the remaining services, then report
            errors.append(f"{key}: {str(error)[:300]}")
            print(f"ROLLBACK_STEP_FAILED {key} {str(error)[:300]}", flush=True)
    if not errors:
        try:
            value = continuity(args, floor)
            print(f"TELEMETRY_CONTINUITY_OK last_persisted_at={value}", flush=True)
            need(snapshots(args.untouched) == ctx["untouched"], "UNTOUCHED_CONTAINER_CHANGED")
        except Exception as error:  # noqa: BLE001
            errors.append(str(error)[:300])
    report.update(rolled_back=done, finished_at_utc=utc_now())
    if errors:
        report.update(outcome="HARD_BLOCKER_ROLLBACK_UNVERIFIED", rollback_errors=errors)
        try:
            record(run_dir, report, kind)
        finally:
            print("HARD_BLOCKER_ROLLBACK_UNVERIFIED " + " | ".join(errors)[:600], flush=True)
        return 4
    report.update(outcome="ROLLED_BACK_VERIFIED")
    record(run_dir, report, kind)
    print("STAGE3_ROLLED_BACK_VERIFIED", flush=True)
    return 0


def prepare(args: argparse.Namespace, state: dict, ws: Path, runs_name: str = "runs",
            update_latest: bool = True) -> tuple[Path, dict]:
    """Write and prove the candidate + rollback Compose files of every service (no production change)."""
    runs = ws / runs_name
    runs.mkdir(mode=0o700, exist_ok=True)
    run_dir = runs / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir.mkdir(mode=0o700)
    manifest = {"work_package": WORK_PACKAGE, "phase": args.phase, "created_at_utc": utc_now(), "compat_ip": args.compat_ip,
                "bridge_host": args.bridge_host, "bridge_port": args.bridge_port,
                "order": [s.key for s in PHASE_SERVICES[args.phase]],
                "readiness_before": {"last_persisted_at": state["readiness_before"].get("last_persisted_at")},
                "dashboard_identity": state["dashboard_identity"], "central_shared_ip": state["central_shared_ip"],
                "backup_receipt": state["receipt"], "services": {}}
    for delta in state["plan"]["services"]:
        spec = BY_KEY[delta["key"]]
        container, image, models = state["containers"][spec.key], state["images"][spec.key], state["models"][spec.key]
        rb_path, cd_path = run_dir / f"{spec.key}.rollback.compose.yaml", run_dir / f"{spec.key}.candidate.compose.yaml"
        write_private(rb_path, render_compose(models["rollback"], spec, f"WP2c Stage 3 {args.phase} ROLLBACK {spec.key} = exact "
                                              f"current {container['Id'][:12]}"))
        write_private(cd_path, render_compose(models["candidate"], spec, f"WP2c Stage 3 {args.phase} CANDIDATE {spec.key}"))
        rb_cfg, cd_cfg = compose_config(rb_path, spec), compose_config(cd_path, spec)
        diffs = config_vs_container(rb_cfg, models["rollback"], container, image, spec)
        need(not diffs, f"COMPOSE_FIDELITY_FAILED {spec.key} rollback differs from the running container: {diffs}")
        need(candidate_config_matches(rb_cfg, cd_cfg, spec, delta),
             f"COMPOSE_FIDELITY_FAILED {spec.key} candidate differs from rollback beyond the intended deltas")
        baseline = effective(container)
        manifest["services"][spec.key] = {
            "container": spec.container, "project": spec.project, "service": spec.service,
            "container_id": container["Id"], "image_id": container["Image"], "config_image": container["Config"]["Image"],
            "delta": {"ports": delta["ports"], "env": delta["env"]},
            "rollback_file": rb_path.name, "candidate_file": cd_path.name,
            "compose_sha256": {rb_path.name: sha256_file(rb_path), cd_path.name: sha256_file(cd_path)},
            "baseline_effective": baseline, "candidate_effective": expected_candidate(baseline, delta),
        }
        print(f"COMPOSE_FIDELITY_PROVEN {spec.key} (rollback = running container; candidate = rollback + deltas)", flush=True)
    write_json(run_dir / "manifest.json", manifest)
    if update_latest:  # a `prove` run is never the rollback source
        write_private(ws / "LATEST", run_dir.name + "\n")
    return run_dir, manifest


def public_report(manifest: dict, state: dict) -> dict:
    return {"work_package": WORK_PACKAGE, "mode": manifest["phase"], "started_at_utc": utc_now(),
            "backup_receipt": state["receipt"], "untouched_before": state["untouched"],
            "services": {k: {"container_id": v["container_id"], "image_id": v["image_id"], "delta": v["delta"],
                             "compose_sha256": v["compose_sha256"]} for k, v in manifest["services"].items()}}


def mode_plan(args: argparse.Namespace) -> int:
    need(os.geteuid() != 0, "RUN_AS_OPERATOR_NONROOT")
    phase_inputs(args)
    if args.from_model:
        views, raw = load_model(Path(args.from_model))
        plan = build_plan(views, args)
        if raw:
            for delta in plan["services"]:
                spec, image = BY_KEY[delta["key"]], {"Config": {}}
                rollback = service_model(raw[spec.container], image, args.compat_ip)
                changes = sorted(model_changes(rollback, candidate_document(rollback, spec, delta), spec))
                need(changes == expected_model_changes(spec, delta), f"MODEL_DELTA_MISMATCH {spec.key} {changes}")
    else:
        plan = live_state(args)["plan"]
    if args.json:
        print(json.dumps(plan, indent=2, sort_keys=True), flush=True)
    else:
        print_plan(plan)
    if plan["blockers"]:
        raise Stop("PLAN_BLOCKERS " + "; ".join(plan["blockers"]))
    print("STAGE3_PLAN_OK (read-only; nothing changed)", flush=True)
    return 0


def mode_check(args: argparse.Namespace) -> int:
    fd = hold_lock(Path(args.lock_path))
    try:
        preflight(args)
    finally:
        os.close(fd)
    print("STAGE3_CHECK_PASS NO_WRITES", flush=True)
    return 0


def mode_prove(args: argparse.Namespace) -> int:
    """Render and prove every candidate and rollback Compose file against the live containers; switch nothing.

    Uses only docker inspect, docker network inspect and `docker compose config` (a pure render): no up, no exec,
    no DNS probe, no backup receipt. Files go to <workspace>/proofs (0700/0600, they hold runtime env values) and
    never become the LATEST run used by rollback. Gives real Compose evidence long before execution day."""
    fd = hold_lock(Path(args.lock_path))
    try:
        identity_checks(args)
        disk_check(args)
        phase_inputs(args)
        ws = workspace(args)
        state = live_state(args)
        print_plan(state["plan"])
        need(not state["plan"]["blockers"], "PLAN_BLOCKERS " + "; ".join(state["plan"]["blockers"]))
        need(state["central_shared_ip"], "CENTRAL_MQTT_SHARED_NETWORK_IP_UNKNOWN")
        state.update(receipt={"status": "NOT_USED_BY_PROVE"}, readiness_before=readiness(),
                     dashboard_identity=dashboard_identity(state["containers"][DASHBOARD.key]))
        run_dir, manifest = prepare(args, state, ws, runs_name="proofs", update_latest=False)
        print(f"STAGE3_PROVE_GREEN phase={args.phase} services={len(manifest['services'])} proof={run_dir} "
              "(Compose fidelity proven; nothing switched)", flush=True)
        return 0
    finally:
        os.close(fd)


def run_phase(args: argparse.Namespace) -> int:
    fd = hold_lock(Path(args.lock_path))
    try:
        ws = workspace(args)
        state = preflight(args)
        run_dir, manifest = prepare(args, state, ws)
        print(f"STAGE3_PREFLIGHT_PASS phase={args.phase} run={run_dir}", flush=True)
        ctx = {"dashboard_identity": state["dashboard_identity"], "central_shared_ip": state["central_shared_ip"],
               "untouched": state["untouched"]}
        report = public_report(manifest, state)
        kind = "execute" if args.phase == "switch" else "drop-compat"
        attempted: list[str] = []
        floor: datetime | None = None
        try:
            # Switched from here on: even a partial Compose failure requires rollback.
            for spec in PHASE_SERVICES[args.phase]:
                entry = manifest["services"][spec.key]
                if spec.key == EDGE_MQTT.key or (args.phase == "drop-compat" and not attempted):
                    # Strict floor: the newest persisted row before the bridge path changes (readiness must answer).
                    floor = parse_ts(readiness().get("last_persisted_at")) or parse_ts(
                        manifest["readiness_before"]["last_persisted_at"])
                attempted.append(spec.key)
                run(compose_up_argv(run_dir / entry["candidate_file"], spec), timeout=300)
                verify_service(spec, entry["candidate_effective"], args, ctx, candidate=True)
                print(f"STAGE3_SERVICE_SWITCHED {spec.key}", flush=True)
            value = continuity(args, floor)
            print(f"TELEMETRY_CONTINUITY_OK last_persisted_at={value}", flush=True)
            need(snapshots(args.untouched) == state["untouched"], "UNTOUCHED_CONTAINER_CHANGED")
            disk_check(args)
        except BaseException as error:  # noqa: BLE001 - every failure (even Ctrl-C) after the first switch rolls back
            print("ACTIVATION_CHECK_FAILED " + str(error)[:400], flush=True)
            report.update(error=str(error)[:600], attempted=list(attempted))
            rc = rollback_chain(args, manifest, run_dir, attempted, ctx, report, kind)
            return 3 if rc == 0 else 4
        marker = GREEN_MARKER[args.phase]
        report.update(outcome=marker, switched=attempted, last_persisted_at=value, finished_at_utc=utc_now())
        record(run_dir, report, kind)
        print(marker, flush=True)
        if args.phase == "switch":
            print("NEXT (owner, not executed by this tool): retarget these consumers to loopback, verify them, "
                  "then run drop-compat --consumers-retargeted (Phase 4):", flush=True)
            for line in state["plan"]["external_consumers"]:
                print("  - " + line, flush=True)
        else:
            print("NEXT (owner): retire nexolab-compat-address.service / nxcompat0 and repeat the acceptance matrix "
                  "including a reboot.", flush=True)
        return 0
    finally:
        os.close(fd)


def load_run(args: argparse.Namespace) -> tuple[Path, dict]:
    ws = workspace(args)
    latest = ws / "LATEST"
    name = args.run or (latest.read_text(encoding="utf-8").strip() if latest.is_file() and not latest.is_symlink() else "")
    need(name and RUN_NAME.match(name), "RUN_NOT_FOUND (no LATEST; pass --run <name>)")
    run_dir = ws / "runs" / name
    manifest = read_json(run_dir / "manifest.json", "RUN_MANIFEST_MISSING " + name)
    need(isinstance(manifest, dict) and manifest.get("phase") in PHASE_SERVICES, "RUN_MANIFEST_PHASE_UNKNOWN")
    need(set(manifest.get("services") or {}) == {s.key for s in PHASE_SERVICES[manifest["phase"]]}
         and manifest.get("order") == [s.key for s in PHASE_SERVICES[manifest["phase"]]], "RUN_MANIFEST_INCOMPLETE")
    for key, entry in manifest["services"].items():
        path = run_dir / entry["rollback_file"]
        need(path.is_file() and not path.is_symlink() and sha256_file(path) == entry["compose_sha256"][path.name],
             "ROLLBACK_COMPOSE_CHANGED " + path.name)
        need(image_inspect(entry["config_image"])["Id"] == entry["image_id"], f"ROLLBACK_IMAGE_TAG_MOVED {key}")
    return run_dir, manifest


def mode_rollback(args: argparse.Namespace) -> int:
    fd = hold_lock(Path(args.lock_path))
    try:
        identity_checks(args)
        run_dir, manifest = load_run(args)
        keys = []
        print(f"ROLLBACK_RUN {run_dir.name} phase={manifest['phase']}", flush=True)
        for spec in (BY_KEY[key] for key in manifest["order"]):
            container = inspect(spec.container)
            at_baseline = (not differences(manifest["services"][spec.key]["baseline_effective"], effective(container))
                           and health(container) == wanted_health(container))
            print(f"{'ALREADY_AT_BASELINE' if at_baseline else 'ROLLBACK_NEEDED'} {spec.key}", flush=True)
            if not at_baseline:
                keys.append(spec.key)
        ctx = {"dashboard_identity": manifest.get("dashboard_identity"), "central_shared_ip": manifest["central_shared_ip"],
               "untouched": snapshots(args.untouched)}
        report = {"work_package": WORK_PACKAGE, "mode": "explicit_rollback", "phase": manifest["phase"],
                  "run": run_dir.name, "started_at_utc": utc_now(),
                  "services_to_roll_back": keys}
        return 0 if rollback_chain(args, manifest, run_dir, keys, ctx, report, "rollback") == 0 else 4
    finally:
        os.close(fd)


# ---------------------------------------------------------------- CLI


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=("plan", "check", "prove", "execute", "drop-compat", "rollback"))
    p.add_argument("--phase", choices=tuple(PHASE_SERVICES), default="switch",
                   help="plan/check/prove only: which phase (execute = switch, drop-compat = drop-compat)")
    p.add_argument("--workspace", default=DEFAULT_WORKSPACE)
    p.add_argument("--from-model", help="plan only: offline JSON (broker docker.service-model or a docker inspect array)")
    p.add_argument("--json", action="store_true", help="plan only: print the change set as JSON")
    p.add_argument("--compat-ip", default=DEFAULT_COMPAT_IP, help="interim compatibility address to leave")
    p.add_argument("--dashboard-host-port", type=int, default=3000)
    p.add_argument("--object-storage-public-url",
                   help="drop-compat only, required there: new OBJECT_STORAGE_PUBLIC_ENDPOINT_URL (no default)")
    p.add_argument("--consumers-retargeted", action="store_true",
                   help="drop-compat: owner statement that every listed external consumer already uses loopback")
    p.add_argument("--pre-stage2-build", default=PRE_STAGE2_BUILD,
                   help="dashboard build ID before Stage 2; check refuses while the LAN dashboard still runs it")
    p.add_argument("--bridge-host", default="central-mqtt")
    p.add_argument("--bridge-port", type=int, default=1883)
    p.add_argument("--shared-network", default=DEFAULT_SHARED_NETWORK)
    p.add_argument("--retain-env", action="append", default=[], help="env key allowed to keep a compat-address reference")
    p.add_argument("--backup-receipt", help="#1428 backup receipt JSON (required for check/execute)")
    p.add_argument("--max-backup-age-hours", type=float, default=24.0)
    p.add_argument("--untouched", action="append", help="container that must stay unchanged (repeatable)")
    p.add_argument("--run", help="rollback only: run directory name under <workspace>/runs (default: LATEST)")
    p.add_argument("--expect-node", default="nexolab-edge-01")
    p.add_argument("--lock-path", default=DEFAULT_LOCK)
    p.add_argument("--reserve-gib", type=int, default=20)
    p.add_argument("--docker-root", default="/var/lib/docker")
    p.add_argument("--wait-seconds", type=int, default=180)
    p.add_argument("--continuity-seconds", type=int, default=60)
    return p


MODES = {"plan": mode_plan, "check": mode_check, "prove": mode_prove, "execute": run_phase, "drop-compat": run_phase,
         "rollback": mode_rollback}


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    args.untouched = args.untouched or list(DEFAULT_UNTOUCHED)
    if not 0 < args.dashboard_host_port < 65536 or not 0 < args.bridge_port < 65536:
        print("STOP PORT_OUT_OF_RANGE", file=sys.stderr, flush=True)
        return 2
    if os.geteuid() == 0:
        print("STOP RUN_AS_OPERATOR_NONROOT", file=sys.stderr, flush=True)
        return 2
    if args.mode in ("execute", "drop-compat"):
        wanted = "switch" if args.mode == "execute" else "drop-compat"
        if "--phase" in (argv if argv is not None else sys.argv[1:]) and args.phase != wanted:
            print(f"STOP PHASE_MISMATCH mode {args.mode} runs phase {wanted}", file=sys.stderr, flush=True)
            return 2
        args.phase = wanted
    if args.from_model and args.mode != "plan":
        print("STOP FROM_MODEL_IS_PLAN_ONLY (a sanitized model is never an execution input)", file=sys.stderr, flush=True)
        return 2
    try:
        return MODES[args.mode](args)
    except Stop as error:
        print("STOP " + str(error)[:900], file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
