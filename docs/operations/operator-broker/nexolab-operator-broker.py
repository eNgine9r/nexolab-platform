#!/usr/bin/env python3
"""NEXOLAB Operator Broker (#1758): bounded local privileged operations for the dev account.

Owner-installed, root-owned and socket-activated (nexolab-operator-broker.socket). The
isolated development account (uid 1001) sends one JSON request per connection over
/run/nexolab-operator/broker.sock; the kernel peer credentials (SO_PEERCRED) decide who
is calling. Every operation is a fixed ID with a typed argument schema and a fixed argv
(no shell, no paths, no free-form arguments). Output is bounded and redacted. Every
request, accepted or rejected, is appended to a hash-chained audit log and answered
with its receipt.

Operation classes:
  read      diagnostics only; run concurrently (bounded).
  recover   idempotent, explicitly permitted recovery of an installed NEXOLAB unit,
            with a precondition (the unit must already be down); one mutation at a time.
  approved  needs a single-use, root-owned owner approval for the exact op and args
            (created with `sudo ... approve`). The dev account cannot create one.

There is no generic exec, no Docker API proxy, no secret output and no Modbus access.
The broker refuses to start when its own file, handlers or approval directory could be
modified by anyone other than root (the agent cannot change privileged code).

Usage:
  nexolab-operator-broker.py serve                   (systemd; socket on fd 3)
  nexolab-operator-broker.py approve --op OP [--arg k=v ...] [--ttl-minutes N] [--reason TEXT]
  nexolab-operator-broker.py verify-audit [PATH]
"""
from __future__ import annotations

import argparse
import collections
import fcntl
import hashlib
import json
import os
import re
import secrets
import signal
import socket
import socketserver
import stat
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

VERSION = "1.4.0"
PROTOCOL = 1
MAX_REQUEST_BYTES = 4096
MAX_OUTPUT_BYTES = 256 * 1024
MAX_CONCURRENT = 4
CLOCK_SKEW_SECONDS = 120
REPLAY_MEMORY = 10_000
ALLOWED_UIDS_ENV = "NEXOLAB_OPERATOR_ALLOWED_UIDS"

INSTALL_DIR = Path("/usr/local/lib/nexolab-operator")
AUDIT_LOG = Path("/var/log/nexolab-operator/audit.jsonl")
REPORT_DIR = Path("/var/lib/nexolab-operator/reports")
APPROVAL_DIR = Path("/etc/nexolab-operator/approvals")
LOCK_FILE = Path("/run/nexolab-operator/mutation.lock")
SAFE_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"

# NEXOLAB and platform units whose state and filtered logs may be read. The GitLab sync
# unit is deliberately absent (its token must never be near this tool).
READABLE_UNITS = (
    "nexolab-lan-gateway.service",
    "nexolab-network-endpoint-repair.service",
    "nexolab-network-endpoint-repair.timer",
    "nexolab-compat-address.service",
    "nexolab-dev-session.service",
    "nexolab-dev-session.timer",
    "nexolab-dr-backup.service",
    "nexolab-dr-backup.timer",
    "nexolab-operator-broker.service",
    "nexolab-operator-broker.socket",
    "docker.service",
    "containerd.service",
    "NetworkManager.service",
    "wpa_supplicant.service",
    "tailscaled.service",
    "systemd-timesyncd.service",
    "systemd-journald.service",
    "ssh.service",
    # Legacy HTTPS pair (#1758 v1.1): readable so its restart loop can be diagnosed.
    "nexolab-external-frontend.service",
    "nexolab-external-nginx.service",
)
# Units the broker may (re)start, and only when they are already down. Never Docker,
# networking, Tailscale or anything holding data.
RECOVERABLE_UNITS = {
    "nexolab-lan-gateway.service": "restart-if-down",
    "nexolab-network-endpoint-repair.service": "start-oneshot",
}
KERNEL_FILTERS = {
    "power": r"under-?voltage|voltage|throttl|brownout|pmic|power",
    "thermal": r"thermal|temperature|overheat",
    "wifi": r"brcmf|wlan|ieee80211|cfg80211|country",
    "storage": r"nvme|sda|ata[0-9]|ext4|i/o error|blk_update|usb [0-9]",
    "crash": r"panic|oops|watchdog|oom|killed process|segfault|call trace|hung_task",
}
SYSTEM_FILTERS = {
    "reboot": r"reboot|shutdown|power|watchdog|panic|reached target|startup finished|systemd-shutdown",
    "network": r"NetworkManager|wpa_supplicant|dhcp|link (is )?(up|down)|carrier",
    "docker": r"dockerd|containerd|container .*(died|restart|oom)",
}
WIFI_PROFILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.:-]{0,63}$")
CONTAINER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
REQUEST_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
APPROVAL_ID = re.compile(r"^[0-9a-f]{32}$")
OP_NAME = re.compile(r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*){1,2}$")


class Rejected(Exception):
    """A request the broker refuses; the code is returned to the caller and audited."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail[:300]


# ----------------------------------------------------------------------------- validation


@dataclass(frozen=True)
class Enum:
    values: tuple[str, ...]
    default: str | None = None

    def __call__(self, value: Any) -> str:
        if type(value) is not str or value not in self.values:
            raise Rejected("invalid_argument", f"expected one of {list(self.values)}")
        return value

    def describe(self) -> dict:
        return {"type": "enum", "values": list(self.values), "default": self.default}


@dataclass(frozen=True)
class Int:
    low: int
    high: int
    default: int | None = None

    def __call__(self, value: Any) -> int:
        if type(value) is not int or not self.low <= value <= self.high:  # bool is rejected
            raise Rejected("invalid_argument", f"expected integer {self.low}..{self.high}")
        return value

    def describe(self) -> dict:
        return {"type": "int", "min": self.low, "max": self.high, "default": self.default}


@dataclass(frozen=True)
class Name:
    pattern: re.Pattern
    default: str | None = None

    def __call__(self, value: Any) -> str:
        if type(value) is not str or not self.pattern.fullmatch(value):
            raise Rejected("invalid_argument", "name does not match the allowed pattern")
        return value

    def describe(self) -> dict:
        return {"type": "name", "pattern": self.pattern.pattern, "default": self.default}


def validate_args(schema: dict[str, Any], raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise Rejected("invalid_request", "args must be an object")
    extra = sorted(set(raw) - set(schema))
    if extra:
        raise Rejected("unexpected_argument", ",".join(extra)[:100])
    clean: dict[str, Any] = {}
    for key, validator in schema.items():
        if key in raw:
            clean[key] = validator(raw[key])
        elif validator.default is not None:
            clean[key] = validator.default
        else:
            raise Rejected("missing_argument", key)
    return clean


# ----------------------------------------------------------------------------- redaction

REDACTIONS = (
    (re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.S),
     "[REDACTED PRIVATE KEY]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[REDACTED JWT]"),
    (re.compile(r"\btskey-[A-Za-z0-9_-]+"), "[REDACTED TAILSCALE KEY]"),
    (re.compile(r"\b(glpat|ghp|gho|ghs|github_pat)[-_][A-Za-z0-9_-]{10,}"), "[REDACTED TOKEN]"),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@"), r"\1[REDACTED]@"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [REDACTED]"),
    (re.compile(r"(?i)((?:[a-z0-9_.-]*)(?:password|passwd|passphrase|psk|secret|token|api[_-]?key|access[_-]?key"
                r"|private[_-]?key|credential|cookie|authorization|wep-key\d?)[a-z0-9_.-]*)(?<!flags)"
                r"([ \t]*[:=][ \t]*|[ \t]+)(?!\[REDACTED)(\"[^\"\n]*\"|'[^'\n]*'|[^\s]+)"),
     r"\1\2[REDACTED]"),
)
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def redact_tree(value: Any) -> tuple[Any, int]:
    """Redact every string inside a JSON-compatible result without breaking its structure."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        items = [redact_tree(v) for v in value]
        return [v for v, _ in items], sum(n for _, n in items)
    if isinstance(value, dict):
        items = {k: redact_tree(v) for k, v in value.items()}
        return {k: v for k, (v, _) in items.items()}, sum(n for _, n in items.values())
    return value, 0


def redact(text: str) -> tuple[str, int]:
    count = 0
    for pattern, replacement in REDACTIONS:
        text, n = pattern.subn(replacement, text)
        count += n
    return CONTROL.sub("?", text), count


# ----------------------------------------------------------------------------- trust checks


def assert_trusted(path: Path, trusted_uid: int, *, directory: bool | None = None) -> None:
    """Refuse a file or directory (and its parents) that anyone but the trusted owner could change."""
    try:
        st = path.lstat()
    except FileNotFoundError:
        raise Rejected("untrusted_handler", f"missing {path}") from None
    if stat.S_ISLNK(st.st_mode):
        raise Rejected("untrusted_handler", f"symlink {path}")
    if directory is True and not stat.S_ISDIR(st.st_mode):
        raise Rejected("untrusted_handler", f"not a directory {path}")
    if directory is False and not stat.S_ISREG(st.st_mode):
        raise Rejected("untrusted_handler", f"not a regular file {path}")
    if st.st_uid != trusted_uid or st.st_mode & 0o022:
        raise Rejected("untrusted_handler", f"owner/mode of {path}")
    for parent in path.parents:
        pst = parent.lstat()
        sticky_root = pst.st_uid == 0 and pst.st_mode & stat.S_ISVTX
        if stat.S_ISLNK(pst.st_mode):
            raise Rejected("untrusted_handler", f"symlinked parent {parent}")
        if pst.st_uid not in (0, trusted_uid) or (pst.st_mode & 0o022 and not sticky_root):
            raise Rejected("untrusted_handler", f"writable parent {parent}")


# ----------------------------------------------------------------------------- execution


@dataclass
class RunResult:
    exit: int | None
    output: str
    truncated: bool
    timed_out: bool


def run(argv: list[str], timeout: float, *, max_bytes: int = MAX_OUTPUT_BYTES, stdin: bytes | None = None,
        keep: str = "head") -> RunResult:
    """Run a fixed argv without a shell, a clean environment, a timeout and an output cap.

    keep="tail" retains the LAST max_bytes (logs: the newest lines matter)."""
    if not argv or not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
        raise Rejected("internal_error", "argv must be a list of strings")
    env = {"PATH": SAFE_PATH, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "SYSTEMD_PAGER": "", "SYSTEMD_COLORS": "0",
           "NO_COLOR": "1", "TERM": "dumb"}
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd="/",
                                start_new_session=True, close_fds=True)
    except FileNotFoundError:
        return RunResult(127, f"{argv[0]}: not installed\n", False, False)
    chunks: list[bytes] = []
    size = 0
    truncated = False

    def reader() -> None:
        nonlocal size, truncated
        assert proc.stdout is not None
        while True:
            block = proc.stdout.read(65536)
            if not block:
                return
            if keep == "tail":
                chunks.append(block)
                size += len(block)
                while size - len(chunks[0]) >= max_bytes:
                    size -= len(chunks.pop(0))
                    truncated = True
                continue
            if size < max_bytes:
                chunks.append(block[: max_bytes - size])
            size += len(block)
            if size > max_bytes:
                truncated = True

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    if stdin is not None:
        assert proc.stdin is not None
        proc.stdin.write(stdin)
        proc.stdin.close()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
    thread.join(timeout=5)
    data = b"".join(chunks)
    if keep == "tail" and len(data) > max_bytes:
        data = data[-max_bytes:]
        truncated = True
    return RunResult(None if timed_out else proc.returncode, data.decode("utf-8", "replace"), truncated, timed_out)


# ----------------------------------------------------------------------------- operations


@dataclass(frozen=True)
class Operation:
    name: str
    kind: str  # read | recover | approved
    summary: str
    handler: Callable[["Broker", dict], dict]
    schema: dict[str, Any] = field(default_factory=dict)
    timeout: float = 30.0
    heavy: bool = False

    def describe(self) -> dict:
        return {"op": self.name, "kind": self.kind, "summary": self.summary, "timeout_s": self.timeout,
                "args": {k: v.describe() for k, v in self.schema.items()}}


def steps(broker: "Broker", commands: list[tuple[str, list[str]]], timeout: float) -> dict:
    """Run named fixed commands; the whole op shares one deadline."""
    deadline = time.monotonic() + timeout
    sections = []
    for title, argv in commands:
        left = deadline - time.monotonic()
        if left <= 0:
            sections.append({"step": title, "exit": None, "timed_out": True, "output": ""})
            break
        result = broker.runner(argv, left)
        sections.append({"step": title, "exit": result.exit, "timed_out": result.timed_out,
                         "truncated": result.truncated, "output": result.output})
    return {"steps": sections}


def filtered(broker: "Broker", argv: list[str], pattern: str, lines: int, timeout: float) -> dict:
    result = broker.runner(argv, timeout, keep="tail")  # newest matching lines, never the boot preamble
    expr = re.compile(pattern, re.I)
    kept = [line for line in result.output.splitlines() if expr.search(line)]
    return {"steps": [{"step": " ".join(argv[:2]), "exit": result.exit, "timed_out": result.timed_out,
                       "truncated": result.truncated, "matched": len(kept),
                       "output": "\n".join(kept[-lines:])}]}


def op_list(broker: "Broker", _args: dict) -> dict:
    return {"version": VERSION, "protocol": PROTOCOL, "operations": [o.describe() for o in broker.ops.values()]}


def op_system_summary(broker: "Broker", _args: dict) -> dict:
    return steps(broker, [
        ("uptime", ["uptime"]),
        ("boot", ["who", "-b"]),
        ("memory", ["free", "-m"]),
        ("disk", ["df", "-h", "-x", "tmpfs", "-x", "devtmpfs", "-x", "overlay"]),
        ("temperature", ["cat", "/sys/class/thermal/thermal_zone0/temp"]),
        ("throttled", ["vcgencmd", "get_throttled"]),
        ("failed-units", ["systemctl", "--failed", "--no-legend", "--plain"]),
        ("time", ["timedatectl", "show", "-p", "NTPSynchronized", "-p", "TimeUSec", "-p", "Timezone"]),
    ], 30)


def op_system_power(broker: "Broker", _args: dict) -> dict:
    return steps(broker, [
        ("throttled", ["vcgencmd", "get_throttled"]),
        ("temperature", ["vcgencmd", "measure_temp"]),
        ("core-volts", ["vcgencmd", "measure_volts", "core"]),
        ("arm-clock", ["vcgencmd", "measure_clock", "arm"]),
        ("pmic", ["vcgencmd", "pmic_read_adc", "EXT5V_V"]),
        ("usb-current", ["vcgencmd", "get_config", "usb_max_current_enable"]),
    ], 30)


def op_system_boots(broker: "Broker", _args: dict) -> dict:
    return steps(broker, [
        ("boots", ["journalctl", "--list-boots", "--no-pager", "-q"]),
        ("previous-boot-tail", ["journalctl", "-b", "-1", "-n", "60", "--no-pager", "-o", "short-iso", "-q"]),
    ], 30)


DT_POWER = Path("/proc/device-tree/chosen/power")
DT_POWER_FIELDS = ("power_reset", "rpi_power_supply", "max_current", "usb_over_current_detected", "sd_overcurrent",
                   "usb_max_current_enable")


def op_system_reset_reason(broker: "Broker", _args: dict) -> dict:
    """Why the last boot happened: SoC reset status, PMIC/supply data from the firmware device tree."""
    result = steps(broker, [
        ("rsts", ["vcgencmd", "get_rsts"]),
        ("bootloader", ["vcgencmd", "bootloader_version"]),
        ("watchdog", ["systemctl", "show", "-p", "RuntimeWatchdogUSec,RebootWatchdogUSec", "--no-pager"]),
        ("boots", ["journalctl", "--list-boots", "--no-pager", "-q"]),
    ], 30)
    values = []
    for name in DT_POWER_FIELDS:
        try:
            values.append(f"{name}=0x{(DT_POWER / name).read_bytes().hex()}")
        except OSError as exc:
            values.append(f"{name}=unavailable ({type(exc).__name__})")
    result["steps"].append({"step": "device-tree-power", "exit": 0, "timed_out": False, "output": "\n".join(values)})
    return result


def op_logs_boot_end(broker: "Broker", args: dict) -> dict:
    """The last lines a previous boot wrote: a clean shutdown sequence versus an abrupt stop."""
    return steps(broker, [(f"boot {args['boot']} end", [
        "journalctl", "-b", args["boot"], "-n", str(args["lines"]), "--no-pager", "-o", "short-iso", "-q"])], 30)


def op_logs_unit(broker: "Broker", args: dict) -> dict:
    return steps(broker, [(args["unit"], [
        "journalctl", "-u", args["unit"], "-b", args["boot"], "-n", str(args["lines"]), "-p", args["priority"],
        "--no-pager", "-o", "short-iso", "-q"])], 30)


def op_logs_kernel(broker: "Broker", args: dict) -> dict:
    return filtered(broker, ["journalctl", "-k", "-b", args["boot"], "--no-pager", "-o", "short-iso", "-q"],
                    KERNEL_FILTERS[args["filter"]], args["lines"], 30)


def op_logs_system(broker: "Broker", args: dict) -> dict:
    return filtered(broker, ["journalctl", "-b", args["boot"], "-n", "50000", "--no-pager", "-o", "short-iso", "-q"],
                    SYSTEM_FILTERS[args["filter"]], args["lines"], 45)


def op_service_status(broker: "Broker", args: dict) -> dict:
    return steps(broker, [(args["unit"], [
        "systemctl", "show", args["unit"], "--no-pager", "-p",
        "LoadState,ActiveState,SubState,UnitFileState,Result,NRestarts,ExecMainStatus,ExecMainStartTimestamp,"
        "ActiveEnterTimestamp,InactiveEnterTimestamp,MemoryCurrent,TasksCurrent,FragmentPath,DropInPaths"])], 15)


def op_service_list(broker: "Broker", _args: dict) -> dict:
    return steps(broker, [("nexolab-units", [
        "systemctl", "list-units", "--all", "--no-legend", "--plain", "--no-pager", "nexolab-*", "docker.service",
        "tailscaled.service", "NetworkManager.service", "wpa_supplicant.service"]),
        ("timers", ["systemctl", "list-timers", "--all", "--no-legend", "--no-pager", "nexolab-*"])], 15)


DOCKER_PS_FORMAT = "{{.Names}}\t{{.Image}}\t{{.State}}\t{{.Status}}\t{{.Ports}}\t{{.Networks}}"
DOCKER_INSPECT_FORMAT = (
    "name={{.Name}}\nimage={{.Config.Image}}\nimage_id={{.Image}}\nstate={{.State.Status}}\n"
    "health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}\nrestart_count={{.RestartCount}}\n"
    "started_at={{.State.StartedAt}}\nfinished_at={{.State.FinishedAt}}\nexit_code={{.State.ExitCode}}\n"
    "oom_killed={{.State.OOMKilled}}\nrestart_policy={{.HostConfig.RestartPolicy.Name}}\n"
    "network_mode={{.HostConfig.NetworkMode}}\n"
    "{{range $n, $e := .NetworkSettings.Networks}}network={{$n}} ip={{$e.IPAddress}} aliases={{join $e.Aliases \",\"}}\n{{end}}"
    "{{range $p, $b := .HostConfig.PortBindings}}{{range $b}}port={{$p}} host={{.HostIp}}:{{.HostPort}}\n{{end}}{{end}}"
    "{{range .Mounts}}mount={{.Type}} name={{.Name}} destination={{.Destination}} rw={{.RW}}\n{{end}}"
    "label.compose_project={{index .Config.Labels \"com.docker.compose.project\"}}\n"
    "label.compose_service={{index .Config.Labels \"com.docker.compose.service\"}}\n"
)


# #1769: Docker diagnostics are scoped to NEXOLAB workloads only. Other products on the
# host (their names, images, networks and logs) never reach the development account.
NEXOLAB_CONTAINER = re.compile(r"^nexolab-[a-z0-9][a-z0-9_.-]{0,62}$")
NEXOLAB_PROJECT = re.compile(r"^(nexolab(-[a-z0-9][a-z0-9_-]*)?)?$")  # empty = not Compose-managed
NEXOLAB_NETWORK = re.compile(r"^nexolab[a-z0-9_.-]*$")
NEXOLAB_IMAGE_REPO = re.compile(r"^nexolab/[a-z0-9][a-z0-9_.-]*$")
SCOPE_FORMAT = "{{.Names}}\t{{.Label \"com.docker.compose.project\"}}\t{{.Image}}"


def nexolab_containers(broker: "Broker") -> dict[str, str]:
    """NEXOLAB container name -> image reference; everything else is invisible."""
    result = broker.runner(["docker", "ps", "-a", "--no-trunc", "--format", SCOPE_FORMAT], 20)
    allowed: dict[str, str] = {}
    for line in result.output.splitlines():
        name, _, rest = line.partition("\t")
        project, _, image = rest.partition("\t")
        if NEXOLAB_CONTAINER.fullmatch(name.strip()) and NEXOLAB_PROJECT.fullmatch(project.strip()):
            allowed[name.strip()] = image.strip()
    return allowed


def container_names(broker: "Broker") -> set[str]:
    return set(nexolab_containers(broker))


def existing_container(broker: "Broker", name: str) -> str:
    if name not in container_names(broker):
        raise Rejected("unknown_container", "not a NEXOLAB container")
    return name


def scoped_lines(result: RunResult, keep: Callable[[str], bool], title: str) -> dict:
    lines = [line for line in result.output.splitlines() if keep(line)]
    return {"step": title, "exit": result.exit, "timed_out": result.timed_out, "truncated": result.truncated,
            "output": "\n".join(lines)}


def op_docker_containers(broker: "Broker", _args: dict) -> dict:
    allowed = container_names(broker)
    result = broker.runner(["docker", "ps", "-a", "--no-trunc", "--format", DOCKER_PS_FORMAT], 30)
    return {"steps": [scoped_lines(result, lambda line: line.split("\t", 1)[0] in allowed, "containers")]}


def op_docker_container(broker: "Broker", args: dict) -> dict:
    name = existing_container(broker, args["name"])
    return steps(broker, [(name, ["docker", "inspect", "--type", "container", "--format", DOCKER_INSPECT_FORMAT,
                                  "--", name])], 20)


def op_docker_logs(broker: "Broker", args: dict) -> dict:
    name = existing_container(broker, args["name"])
    return steps(broker, [(name, ["docker", "logs", "--timestamps", "--tail", str(args["lines"]),
                                  "--since", f"{args['since_minutes']}m", "--", name])], 30)


def op_docker_networks(broker: "Broker", _args: dict) -> dict:
    allowed = container_names(broker)
    networks = broker.runner(["docker", "network", "ls", "--no-trunc", "--format",
                              "{{.Name}}\t{{.Driver}}\t{{.Scope}}\t{{.ID}}"], 30)
    attachments = broker.runner(["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Networks}}"], 30)
    return {"steps": [
        scoped_lines(networks, lambda line: bool(NEXOLAB_NETWORK.fullmatch(line.split("\t", 1)[0])), "networks"),
        scoped_lines(attachments, lambda line: line.split("\t", 1)[0] in allowed, "attachments"),
    ]}


def op_docker_images(broker: "Broker", _args: dict) -> dict:
    in_use = nexolab_containers(broker)
    used_refs = set(in_use.values())

    def nexolab_image(line: str) -> bool:
        ref = line.split("\t", 1)[0]
        return bool(NEXOLAB_IMAGE_REPO.fullmatch(ref.rsplit(":", 1)[0])) or ref in used_refs

    images = broker.runner(["docker", "image", "ls", "--digests", "--no-trunc", "--format",
                            "{{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.Digest}}\t{{.CreatedSince}}\t{{.Size}}"], 45)
    return {"steps": [
        scoped_lines(images, nexolab_image, "images"),
        {"step": "in-use", "exit": 0, "timed_out": False,
         "output": "\n".join(f"{name}\t{image}" for name, image in sorted(in_use.items()))},
    ]}


ENV_VALUE_ALLOWED = re.compile(r"^(?:[A-Z0-9_]*_(?:HOST|PORT|URL|BASE_URL|ADDRESS|CLIENT_ID|MODE|ENABLED|PROFILE|TOPIC|"
                               r"NETWORK|ORIGIN|BIND_ADDRESS|INTERVAL|SECONDS|TIMEOUT|LEVEL)|TZ|NODE_ENV|NEXOLAB_[A-Z_]+_STAGE)$")
ENV_SECRET_NAME = re.compile(r"(?i)pass|secret|token|key|credential|cookie|auth|salt|cert|private|session")
RUNTIME_MODEL_FORMAT = (
    "{{json .Name}}\t{{json .Config.Image}}\t{{json .Image}}\t{{json .HostConfig.RestartPolicy.Name}}\t"
    "{{json .HostConfig.NetworkMode}}\t{{json .HostConfig.PortBindings}}\t{{json .NetworkSettings.Networks}}\t"
    "{{json .Mounts}}\t{{json .Config.Env}}\t{{json .Config.Labels}}\t{{json .Config.Healthcheck}}"
)
LABELS_KEPT = ("com.docker.compose.project", "com.docker.compose.service", "com.docker.compose.project.config_files",
               "com.docker.compose.project.working_dir", "com.docker.compose.container-number",
               "org.opencontainers.image.revision")


def sanitize_env(entries: list[str] | None) -> list[str]:
    """Keys always; values only for allow-listed, non-secret configuration keys."""
    out = []
    for entry in entries or []:
        key, sep, value = entry.partition("=")
        if sep and ENV_VALUE_ALLOWED.fullmatch(key) and not ENV_SECRET_NAME.search(key):
            out.append(f"{key}={value}")
        else:
            out.append(f"{key}=<set>" if sep else key)
    return sorted(out)


def op_docker_runtime_model(broker: "Broker", _args: dict) -> dict:
    """WP2c Phase 0 (#1734): the effective NEXOLAB container model, without secret values."""
    names = sorted(container_names(broker))
    model = []
    for name in names:
        result = broker.runner(["docker", "inspect", "--type", "container", "--format", RUNTIME_MODEL_FORMAT,
                                "--", name], 20)
        fields = result.output.strip().split("\t")
        if result.exit != 0 or len(fields) != 11:
            model.append({"name": name, "error": "inspect_failed"})
            continue
        try:
            (cname, image, image_id, restart, net_mode, ports, networks, mounts, env, labels,
             health) = (json.loads(f) for f in fields)
        except ValueError:
            model.append({"name": name, "error": "inspect_unparseable"})
            continue
        model.append({
            "name": cname.lstrip("/"), "image": image, "image_id": image_id, "restart_policy": restart,
            "network_mode": net_mode, "port_bindings": ports or {},
            "networks": {n: {"aliases": (v or {}).get("Aliases"), "ip": (v or {}).get("IPAddress")}
                         for n, v in (networks or {}).items()},
            "mounts": [{"type": m.get("Type"), "name": m.get("Name"), "destination": m.get("Destination"),
                        "rw": m.get("RW")} for m in (mounts or [])],
            "env": sanitize_env(env),
            "labels": {k: v for k, v in (labels or {}).items() if k in LABELS_KEPT},
            "healthcheck": (health or {}).get("Test"),
        })
    nets = broker.runner(["docker", "network", "ls", "--format", "{{.Name}}"], 20)
    network_model = []
    for net in sorted(n for n in nets.output.split() if NEXOLAB_NETWORK.fullmatch(n)):
        info = broker.runner(["docker", "network", "inspect", "--format",
                              "{{json .Driver}}\t{{json .IPAM.Config}}\t{{json .Labels}}", "--", net], 20)
        parts = info.output.strip().split("\t")
        try:
            driver, ipam, labels = (json.loads(p) for p in parts)
        except ValueError:
            network_model.append({"name": net, "error": "inspect_failed"})
            continue
        network_model.append({"name": net, "driver": driver, "ipam": ipam,
                              "compose_project": (labels or {}).get("com.docker.compose.project")})
    return {"containers": model, "networks": network_model}


def op_docker_disk(broker: "Broker", _args: dict) -> dict:
    return steps(broker, [("df", ["docker", "system", "df"])], 120)


def op_network_summary(broker: "Broker", _args: dict) -> dict:
    return steps(broker, [
        ("addresses", ["ip", "-br", "addr"]),
        ("links", ["ip", "-br", "link"]),
        ("routes", ["ip", "-4", "route"]),
        ("routes6", ["ip", "-6", "route"]),
        ("rules", ["ip", "rule"]),
        ("dns", ["cat", "/etc/resolv.conf"]),
        ("devices", ["nmcli", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"]),
        ("connections", ["nmcli", "-f", "NAME,TYPE,DEVICE,AUTOCONNECT,AUTOCONNECT-PRIORITY", "connection", "show"]),
        ("listeners", ["ss", "-ltnH"]),
        ("dhcp-eth0", ["nmcli", "-f", "DHCP4,IP4", "device", "show", "eth0"]),
    ], 30)


WIFI_PROFILE_FIELDS = (
    "connection.id,802-11-wireless.ssid,802-11-wireless.hidden,802-11-wireless.band,802-11-wireless.channel,"
    "802-11-wireless.bssid,802-11-wireless.cloned-mac-address,802-11-wireless.powersave,"
    "802-11-wireless-security.key-mgmt,802-11-wireless-security.pmf,802-11-wireless-security.proto,"
    "802-11-wireless-security.pairwise,802-11-wireless-security.group,802-11-wireless-security.psk-flags,"
    "connection.autoconnect,connection.autoconnect-priority,connection.autoconnect-retries,ipv4.method,"
    "ipv4.route-metric,ipv6.method"
)  # nmcli secrets mode is never used; the PSK field itself is not requested


def wifi_profiles(broker: "Broker") -> list[str]:
    out = broker.runner(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"], 10).output
    names = []
    for line in out.splitlines():
        name, _, kind = line.rpartition(":")
        if kind == "802-11-wireless" and WIFI_PROFILE_NAME.fullmatch(name.replace("\\:", ":")):
            names.append(name.replace("\\:", ":"))
    return names[:5]


def op_wifi_diagnose(broker: "Broker", _args: dict) -> dict:
    profiles = [(f"profile {name}", ["nmcli", "-f", WIFI_PROFILE_FIELDS, "connection", "show", "id", name])
                for name in wifi_profiles(broker)]
    result = steps(broker, [
        ("radio", ["nmcli", "radio", "wifi"]),
        ("device", ["nmcli", "-f", "GENERAL.STATE,GENERAL.REASON,GENERAL.HWADDR,WIFI-PROPERTIES", "device", "show",
                    "wlan0"]),
        ("profiles", ["nmcli", "-f", "NAME,TYPE,AUTOCONNECT", "connection", "show"]),
        *profiles,
        ("scan-cached", ["nmcli", "-f", "IN-USE,SSID,BSSID,MODE,CHAN,FREQ,RATE,SIGNAL,SECURITY,WPA-FLAGS,RSN-FLAGS",
                         "device", "wifi", "list", "--rescan", "no"]),
        ("link", ["iw", "dev", "wlan0", "link"]),
        ("regulatory", ["iw", "reg", "get"]),
        ("power-save", ["iw", "dev", "wlan0", "get", "power_save"]),
        ("driver", ["ethtool", "-i", "wlan0"]),
    ], 30)
    wpa = filtered(broker, ["journalctl", "-b", "-u", "wpa_supplicant", "--no-pager", "-o", "short-iso", "-q"],
                   r"reason|status_code|ASSOC-REJECT|WRONG_KEY|TEMP-DISABLED|SAE|PMF|CTRL-EVENT|auth", 40, 20)
    nm = filtered(broker, ["journalctl", "-b", "-u", "NetworkManager", "--no-pager", "-o", "short-iso", "-q"],
                  r"wlan0|wifi|802-11", 40, 20)
    kernel = filtered(broker, ["journalctl", "-k", "-b", "--no-pager", "-o", "short-iso", "-q"],
                      KERNEL_FILTERS["wifi"], 40, 20)
    for title, part in (("wpa_supplicant", wpa), ("networkmanager", nm), ("kernel", kernel)):
        part["steps"][0]["step"] = title
        result["steps"].extend(part["steps"])
    return result




def op_storage_summary(broker: "Broker", _args: dict) -> dict:
    return steps(broker, [
        ("filesystems", ["df", "-h", "-x", "tmpfs", "-x", "devtmpfs", "-x", "overlay"]),
        ("inodes", ["df", "-i", "/"]),
        ("block", ["lsblk", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL"]),
        ("journal", ["journalctl", "--disk-usage"]),
    ], 60)


def op_storage_inventory(broker: "Broker", _args: dict) -> dict:
    script = broker.install_dir / "handlers" / "nexolab-storage-inventory.sh"
    assert_trusted(script, broker.trusted_uid, directory=False)
    broker.report_dir.mkdir(parents=True, exist_ok=True)
    before = set(broker.report_dir.glob("nexolab-storage-inventory-*.txt"))
    result = broker.runner(["bash", str(script), str(broker.report_dir)], 1500)
    produced = sorted(set(broker.report_dir.glob("nexolab-storage-inventory-*.txt")) - before)
    if not produced:
        return {"steps": [{"step": "inventory", "exit": result.exit, "timed_out": result.timed_out,
                           "output": result.output[-4000:]}], "report": None}
    report = produced[-1]
    os.chmod(report, 0o600)  # #1769: the raw report stays root-only; only a sanitized excerpt leaves
    data = report.read_bytes()
    return {"steps": [{"step": "inventory", "exit": result.exit, "timed_out": result.timed_out,
                       "output": sanitize_inventory(data.decode("utf-8", "replace"))}],
            "report": {"path": str(report), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                       "mode": "0600 root (raw report not exposed)"}}


INVENTORY_SECTIONS = (
    "Filesystems", "Memory and load", "Largest top-level areas (root filesystem only)", "Commander workspaces",
    "Docker disk usage", "Journal", "Cleanup candidates (estimates only; nothing deleted)",
)
WORKSPACE_PATH = re.compile(r"(commander-workspaces/)([^/\s']+)")
NEXOLAB_WORKSPACE = re.compile(r"^(nexolab|unified-update)[A-Za-z0-9_.-]*$")


def sanitize_inventory(text: str, max_chars: int = 60_000) -> str:
    """Allow-listed sections only; non-NEXOLAB workspace names are masked; redaction runs later."""
    kept: list[str] = []
    for chunk in re.split(r"(?m)^(?====== )", text):
        header = re.match(r"===== (.*?) =====", chunk)
        if header and header.group(1) in INVENTORY_SECTIONS:
            kept.append(chunk.rstrip())
    joined = "\n\n".join(kept)
    joined = WORKSPACE_PATH.sub(lambda m: m.group(1) + (m.group(2) if NEXOLAB_WORKSPACE.fullmatch(m.group(2))
                                                         else "<non-nexolab-workspace>"), joined)
    return joined[:max_chars]


def unit_state(broker: "Broker", unit: str) -> dict:
    out = broker.runner(["systemctl", "show", unit, "--no-pager", "-p", "LoadState,ActiveState,SubState,UnitFileState,Result"],
                        10).output
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def op_service_recover(broker: "Broker", args: dict) -> dict:
    unit = args["unit"]
    before = unit_state(broker, unit)
    if before.get("LoadState") != "loaded":
        raise Rejected("precondition_failed", f"{unit} is not installed")
    policy = RECOVERABLE_UNITS[unit]
    if policy == "restart-if-down":
        if before.get("UnitFileState") != "enabled":
            raise Rejected("precondition_failed", f"{unit} is not enabled; recovery never enables units")
        if before.get("ActiveState") not in ("failed", "inactive"):
            raise Rejected("precondition_failed", f"{unit} is {before.get('ActiveState')}; only a down unit is recovered")
        action = ["systemctl", "restart", "--no-block", unit]
    else:  # start-oneshot: the same idempotent run its timer performs
        if before.get("ActiveState") == "activating":
            raise Rejected("busy", f"{unit} is already running")
        action = ["systemctl", "start", "--no-block", unit]
    started = broker.runner(action, 20)
    deadline = time.monotonic() + 45
    after = unit_state(broker, unit)
    while after.get("ActiveState") == "activating" and time.monotonic() < deadline:
        time.sleep(1)
        after = unit_state(broker, unit)
    return {"unit": unit, "before": before, "after": after, "exit": started.exit,
            "recovered": after.get("ActiveState") == "active" or (policy == "start-oneshot" and after.get(
                "ActiveState") in ("inactive", "active") and after.get("Result", "success") == "success")}


# ----------------------------------------------------------------------------- approved handlers
# Each run needs a single-use owner approval for the exact op (see `approve`). They re-verify
# their preconditions at run time, never force anything, and report before/after evidence.


def free_bytes(path: str = "/") -> int:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def docker_lines(broker: "Broker", argv: list[str], timeout: float = 60) -> list[str]:
    result = broker.runner(argv, timeout)
    if result.exit != 0:
        raise Rejected("precondition_failed", f"{' '.join(argv[:3])} failed")
    return [line.strip() for line in result.output.splitlines() if line.strip()]


BUILD_CACHE_PRUNE = {
    "older-than-7d": ["docker", "builder", "prune", "--force", "--filter", "until=168h"],
    # Every unused build-cache record (regenerable; images, containers and volumes are not build cache).
    "all-unused": ["docker", "builder", "prune", "--all", "--force"],
}


def op_storage_cleanup_regenerable(broker: "Broker", args: dict) -> dict:
    """Owner-approved T1 cleanup: only regenerable data. Volumes and every tagged or used image stay.

    The approval binds `build_cache`, so "all-unused" needs the owner to approve exactly that."""
    before_free = free_bytes()
    volumes_before = docker_lines(broker, ["docker", "volume", "ls", "-q"])
    used = set(docker_lines(broker, ["docker", "ps", "-aq", "--no-trunc"]))
    used_images = set()
    for cid in used:
        used_images.update(docker_lines(broker, ["docker", "inspect", "--type", "container", "--format",
                                                 "{{.Image}}", "--", cid], 20))
    report: list[dict] = []
    prune = broker.runner(BUILD_CACHE_PRUNE[args.get("build_cache", "older-than-7d")], 600)
    report.append({"step": f"build cache ({args.get('build_cache', 'older-than-7d')})", "exit": prune.exit,
                   "output": prune.output[-600:]})
    removed, skipped = [], []
    for image_id in docker_lines(broker, ["docker", "images", "--filter", "dangling=true", "--no-trunc", "-q"]):
        tags = broker.runner(["docker", "image", "inspect", "--format", "{{json .RepoTags}}", "--", image_id], 20)
        try:
            tag_list = json.loads(tags.output) if tags.exit == 0 else None
        except ValueError:
            tag_list = None
        if tag_list != [] or image_id in used_images:  # containerd lists TAGGED images as dangling (#1710)
            skipped.append(image_id)
            continue
        result = broker.runner(["docker", "image", "rm", "--", image_id], 120)  # never -f
        (removed if result.exit == 0 else skipped).append(image_id)
    report.append({"step": "untagged unused images", "removed": removed, "skipped_protected": skipped})
    vacuum = broker.runner(["journalctl", "--vacuum-size=200M"], 120)
    report.append({"step": "journal to 200M", "exit": vacuum.exit, "output": vacuum.output[-400:]})
    volumes_after = docker_lines(broker, ["docker", "volume", "ls", "-q"])
    if sorted(volumes_after) != sorted(volumes_before):
        raise Rejected("internal_error", "volume set changed during cleanup")  # must never happen
    return {"steps": report, "free_before_gib": round(before_free / 1024**3, 2),
            "free_after_gib": round(free_bytes() / 1024**3, 2), "volumes_unchanged": True,
            "in_use_images_kept": len(used_images)}


LEGACY_HTTPS_UNITS = ("nexolab-external-frontend.service", "nexolab-external-nginx.service")
ETC_UNIT_DIR = Path("/etc/systemd/system")
LIVE_HTTPS_IDENTITY = "http://127.0.0.1:3105/api/runtime-identity"


def live_https_identity() -> dict:
    import urllib.request
    try:
        with urllib.request.urlopen(LIVE_HTTPS_IDENTITY, timeout=5) as res:
            data = json.load(res)
    except Exception as exc:  # noqa: BLE001
        raise Rejected("precondition_failed", f"live HTTPS UI identity unavailable: {type(exc).__name__}") from None
    return {k: data.get(k) for k in ("source_commit", "build_id")}


def op_service_retire_legacy_https(broker: "Broker", _args: dict) -> dict:
    """Stop the prepared-only legacy HTTPS pair that restart-loops; the live :3105 UI is unaffected."""
    fragment = Path(unit_state_props(broker, LEGACY_HTTPS_UNITS[0], "FragmentPath").get("FragmentPath", ""))
    try:
        header = fragment.read_text(encoding="utf-8", errors="replace")[:400]
    except OSError:
        header = ""
    if "PREPARED ONLY" not in header:
        raise Rejected("precondition_failed", "frontend unit is not the prepared-only legacy unit")
    if unit_state(broker, LEGACY_HTTPS_UNITS[1]).get("ActiveState") == "active":
        raise Rejected("precondition_failed", "legacy nginx is active; it is not the restart-loop case")
    if unit_state(broker, LEGACY_HTTPS_UNITS[0]).get("ActiveState") == "active":
        raise Rejected("precondition_failed", "legacy frontend is running; it is not the restart-loop case")
    identity_before = live_https_identity()
    before = {u: unit_state_props(broker, u, "ActiveState,SubState,UnitFileState,NRestarts") for u in LEGACY_HTTPS_UNITS}
    actions = []
    for argv in (["systemctl", "disable", "--now", LEGACY_HTTPS_UNITS[1]],
                 ["systemctl", "stop", LEGACY_HTTPS_UNITS[0]]):
        result = broker.runner(argv, 60)
        actions.append({"argv": argv[1:], "exit": result.exit})
    # `mask` cannot replace a real unit file in /etc/systemd/system (v1.1 site run: exit 1). Such a
    # static unit stays down once nothing enabled pulls it in, so report that instead (#1775).
    if fragment.parent == ETC_UNIT_DIR and fragment.is_file() and not fragment.is_symlink():
        pulled_by = unit_state_props(broker, LEGACY_HTTPS_UNITS[0], "WantedBy,RequiredBy,BoundBy,UnitFileState")
        actions.append({"argv": ["mask", LEGACY_HTTPS_UNITS[0]], "skipped": "unit file is a real file in /etc",
                        "pulled_in_by": pulled_by})
    else:
        result = broker.runner(["systemctl", "mask", LEGACY_HTTPS_UNITS[0]], 60)
        actions.append({"argv": ["mask", LEGACY_HTTPS_UNITS[0]], "exit": result.exit})
    time.sleep(12)
    after = {u: unit_state_props(broker, u, "ActiveState,SubState,UnitFileState,NRestarts") for u in LEGACY_HTTPS_UNITS}
    identity_after = live_https_identity()
    loop_stopped = after[LEGACY_HTTPS_UNITS[0]].get("ActiveState") in ("inactive", "failed")
    return {"before": before, "after": after, "actions": actions, "loop_stopped": loop_stopped,
            "live_https_identity_unchanged": identity_before == identity_after, "live_https_identity": identity_after,
            "undo": "approved op service.restore-legacy-https"}


def op_service_restore_legacy_https(broker: "Broker", _args: dict) -> dict:
    """Undo of retire-legacy-https: unmask and re-enable exactly as before (the loop will return)."""
    actions = []
    for argv in (["systemctl", "unmask", LEGACY_HTTPS_UNITS[0]], ["systemctl", "enable", LEGACY_HTTPS_UNITS[1]]):
        result = broker.runner(argv, 60)
        actions.append({"argv": argv[1:], "exit": result.exit})
    return {"actions": actions,
            "after": {u: unit_state_props(broker, u, "ActiveState,UnitFileState") for u in LEGACY_HTTPS_UNITS}}


# ----------------------------------------------------------------------------- deployment (#1775)
# deploy.lan-frontend runs the PINNED WP2c Stage 2 tool (#1734, handlers/) as the owner account in a
# transient unit. The owner's approval binds the phase, the artifact SHA-256 and the identity of the
# dashboard currently running, so the development account can neither change what is deployed nor
# what it replaces. The artifact is copied into root-controlled staging and hashed while copying; the
# tool only ever sees that verified copy.

DEPLOY_USER_ENV = "NEXOLAB_OPERATOR_DEPLOY_USER"
DEPLOY_DIR = Path("/var/lib/nexolab-operator-deploy")
STAGE2_TOOL = "wp2c-stage2-frontend.py"
STAGE2_WORKSPACE = "commander-workspaces/nexolab-wp2c-stage2"
MAX_ARTIFACT_BYTES = 2 * 1024**3
SHA256_OR_NONE = re.compile(r"^([0-9a-f]{64}|none)$")
SOURCE_SHA = re.compile(r"^[0-9a-f]{40}$")
BUILD_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
STAGE2_MARKERS = re.compile(r"^(STAGE2_[A-Z_]+|HARD_BLOCKER_[A-Z_]+|STOP [^\n]{0,300})", re.M)
STAGE2_RUNTIME_LIMIT = {"prepare": 3000, "execute": 1200, "rollback": 900}


def deploy_account(broker: "Broker") -> tuple[str, Path, int]:
    import pwd
    name = os.environ.get(DEPLOY_USER_ENV, "nexolab")
    try:
        entry = pwd.getpwnam(name)
    except KeyError:
        raise Rejected("precondition_failed", f"deployment account {name} does not exist") from None
    if entry.pw_uid == 0 or entry.pw_uid in broker.allowed_uids:
        raise Rejected("precondition_failed", "deployment account must be the owner, not root or the dev account")
    return name, Path(entry.pw_dir), entry.pw_gid


def inbox_dir(broker: "Broker") -> Path:
    import pwd
    uid = min(broker.allowed_uids)
    return Path(pwd.getpwuid(uid).pw_dir) / "operator-inbox"


def stage_artifact(broker: "Broker", sha256: str, group_gid: int) -> Path:
    """Copy <inbox>/<sha256>.zip into root-controlled staging, hashing the bytes that are written."""
    if not SHA256_OR_NONE.fullmatch(sha256) or sha256 == "none":
        raise Rejected("invalid_argument", "artifact_sha256 must be a SHA-256 for this phase")
    source = inbox_dir(broker) / f"{sha256}.zip"
    target = DEPLOY_DIR / f"{sha256}.zip"
    if not DEPLOY_DIR.is_dir() or DEPLOY_DIR.is_symlink():
        raise Rejected("precondition_failed", f"{DEPLOY_DIR} missing (installer creates it)")
    if target.exists():
        digest = hashlib.sha256()
        with open(target, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        if digest.hexdigest() == sha256:
            return target
        target.unlink()
    try:
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        raise Rejected("precondition_failed", f"artifact {source.name} not found in the operator inbox") from None
    partial = DEPLOY_DIR / f".{sha256}.partial"
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or not 0 < st.st_size <= MAX_ARTIFACT_BYTES:
            raise Rejected("precondition_failed", "artifact is not a regular file of an allowed size")
        digest = hashlib.sha256()
        out = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        with os.fdopen(fd, "rb", closefd=False) as src, os.fdopen(out, "wb") as dst:
            for block in iter(lambda: src.read(1 << 20), b""):
                digest.update(block)
                dst.write(block)
        if digest.hexdigest() != sha256:
            raise Rejected("approval_mismatch", "artifact bytes do not match the approved SHA-256")
        if os.geteuid() == 0:
            os.chown(partial, 0, group_gid)
        os.chmod(partial, 0o640)
        os.replace(partial, target)
        return target
    finally:
        os.close(fd)
        if partial.exists():
            partial.unlink()


def staged_artifact_sha(workspace: Path) -> str | None:
    """zip_sha256 recorded by the tool's `stage` (None when nothing is staged yet)."""
    try:
        fd = os.open(workspace / "stage.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    except OSError:
        raise Rejected("precondition_failed", "stage.json is not a readable regular file") from None
    with os.fdopen(fd, "rb") as handle:
        try:
            facts = json.loads(handle.read(256 * 1024))
        except ValueError:
            raise Rejected("precondition_failed", "stage.json is not valid JSON") from None
    value = facts.get("zip_sha256") if isinstance(facts, dict) else None
    if not isinstance(value, str) or not SHA256_OR_NONE.fullmatch(value) or value == "none":
        raise Rejected("precondition_failed", "stage.json has no artifact SHA-256")
    return value


def run_as_owner(broker: "Broker", user: str, argv: list[str], limit: int) -> RunResult:
    """Run a pinned handler as the owner account (docker group) in a bounded transient unit."""
    unit = ["systemd-run", "--quiet", "--wait", "--pipe", "--collect", f"--uid={user}",
            "--working-directory=/", "-p", "NoNewPrivileges=yes", "-p", f"RuntimeMaxSec={limit}",
            "-p", "Nice=10", "-p", "IOSchedulingClass=best-effort", "-p", "IOSchedulingPriority=7"]
    return broker.runner(unit + argv, limit + 60, keep="tail")


def op_deploy_lan_frontend(broker: "Broker", args: dict) -> dict:
    """Owner-approved WP2c Stage 2: prepare (stage, offline build, preview, check), execute or rollback."""
    phase = args["phase"]
    user, home, gid = deploy_account(broker)
    tool = broker.install_dir / "handlers" / STAGE2_TOOL
    assert_trusted(tool, broker.trusted_uid, directory=False)
    base = ["/usr/bin/python3", "-I", "-B", str(tool), "--workspace", str(home / STAGE2_WORKSPACE)]
    identity = ["--rollback-source", args["expect_current_source"], "--rollback-build", args["expect_current_build"]]
    runs: list[tuple[str, list[str]]] = []
    staged = staged_artifact_sha(home / STAGE2_WORKSPACE)
    if phase in ("prepare", "execute") and staged not in (None, args["artifact_sha256"]):
        raise Rejected("approval_mismatch", "the workspace is staged with a different artifact than approved")
    if phase == "execute" and staged is None:
        raise Rejected("precondition_failed", "nothing staged: run phase=prepare first")
    if phase == "prepare":
        artifact = stage_artifact(broker, args["artifact_sha256"], gid)
        if staged is None:
            runs.append(("stage", ["stage", "--artifact-zip", str(artifact), "--expect-zip-sha256",
                                   args["artifact_sha256"]]))
        if not (home / STAGE2_WORKSPACE / "build.json").exists():  # resumable: the tool never rebuilds a tag
            runs.append(("build", ["build", *identity]))
        runs += [("preview", ["preview", *identity]), ("check", ["check", *identity])]
    elif phase == "execute":
        stage_artifact(broker, args["artifact_sha256"], gid)  # execute re-proves the approved artifact
        runs.append(("execute", ["execute", *identity]))
    else:
        runs.append(("rollback", ["rollback"]))
    deadline = time.monotonic() + STAGE2_RUNTIME_LIMIT[phase]
    report, ok = [], True
    for title, extra in runs:
        left = int(deadline - time.monotonic())
        if left < 60:
            report.append({"step": title, "exit": None, "timed_out": True, "markers": []})
            ok = False
            break
        result = run_as_owner(broker, user, base + extra, left)
        report.append({"step": title, "exit": result.exit, "timed_out": result.timed_out,
                       "markers": STAGE2_MARKERS.findall(result.output)[-12:], "output": result.output[-6000:]})
        if result.exit != 0:
            ok = False
            break
    return {"phase": phase, "ok": ok, "steps": report, "deploy_user": user,
            "production_changed": phase in ("execute", "rollback"),
            "next": {"prepare": "owner approves phase=execute with the same artifact and identity",
                     "execute": "verify through the gateway; undo with phase=rollback",
                     "rollback": "verify the previous dashboard identity"}[phase]}


# ----------------------------------------------------------------------------- v1.3 (#1778)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_REF = re.compile(r"^nexolab[a-z0-9_.-]*/?[a-z0-9_./-]*:[A-Za-z0-9_.-]{1,128}$")
PROTECTED_IMAGE = re.compile(r"protected|recovery|rollback|disaster-recovery|baseline|-base:", re.I)
MAX_MANIFEST_IMAGES = 60


def read_inbox_json(broker: "Broker", sha256: str, max_bytes: int = 256 * 1024) -> Any:
    """Read <inbox>/<sha256>.json without following links and prove the bytes match the approved hash."""
    if not SHA256.fullmatch(sha256):
        raise Rejected("invalid_argument", "manifest_sha256 must be a SHA-256")
    path = inbox_dir(broker) / f"{sha256}.json"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        raise Rejected("precondition_failed", f"manifest {path.name} not found in the operator inbox") from None
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise Rejected("precondition_failed", "manifest is not a regular file")
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise Rejected("precondition_failed", "manifest too large")
    if hashlib.sha256(data).hexdigest() != sha256:
        raise Rejected("approval_mismatch", "manifest bytes do not match the approved SHA-256")
    try:
        return json.loads(data)
    except ValueError:
        raise Rejected("precondition_failed", "manifest is not valid JSON") from None


def used_image_ids(broker: "Broker") -> set[str]:
    used = set()
    for cid in docker_lines(broker, ["docker", "ps", "-aq", "--no-trunc"]):
        used.update(docker_lines(broker, ["docker", "inspect", "--type", "container", "--format", "{{.Image}}",
                                          "--", cid], 20))
    return used


def op_storage_remove_images(broker: "Broker", args: dict) -> dict:
    """Owner-approved removal of the exact NEXOLAB images listed in a hash-bound manifest (never -f)."""
    manifest = read_inbox_json(broker, args["manifest_sha256"])
    images = manifest.get("images") if isinstance(manifest, dict) else None
    if not isinstance(images, list) or not 0 < len(images) <= MAX_MANIFEST_IMAGES:
        raise Rejected("precondition_failed", f"manifest needs 1..{MAX_MANIFEST_IMAGES} images")
    entries = []
    for item in images:
        ref, image_id = (item.get("ref"), item.get("id")) if isinstance(item, dict) else (None, None)
        if not (isinstance(ref, str) and IMAGE_REF.fullmatch(ref) and isinstance(image_id, str)
                and IMAGE_ID.fullmatch(image_id)):
            raise Rejected("precondition_failed", "manifest entry needs a NEXOLAB image ref and a sha256 id")
        if PROTECTED_IMAGE.search(ref):
            raise Rejected("precondition_failed", f"protected image refused: {ref}")
        entries.append((ref, image_id))
    # Every removal re-runs the root-side reference scan (#1782): images named in the owner's protected-images
    # file or referenced as rollback/previous/recovery/restore are never removed, whatever the manifest says.
    evidence = image_references(entries)
    if not evidence["complete"]:
        raise Rejected("precondition_failed", "reference scan incomplete; nothing removed")
    guarded = {e["ref"]: e for e in evidence["images"] if e["in_protected_images_file"] or e["rollback_references"]}
    before_free = free_bytes()
    volumes_before = docker_lines(broker, ["docker", "volume", "ls", "-q"])
    used = used_image_ids(broker)
    results = []
    for ref, image_id in entries:
        if ref in guarded:
            results.append({"ref": ref, "status": "skipped_protected_or_rollback_record",
                            "rollback_references": guarded[ref]["rollback_references"],
                            "in_protected_images_file": guarded[ref]["in_protected_images_file"]})
            continue
        current = broker.runner(["docker", "image", "inspect", "--format", "{{.Id}}", "--", ref], 20)
        if current.exit != 0:
            results.append({"ref": ref, "status": "absent"})
            continue
        if current.output.strip() != image_id:
            results.append({"ref": ref, "status": "skipped_tag_moved", "now": current.output.strip()[:80]})
            continue
        if image_id in used:
            results.append({"ref": ref, "status": "skipped_in_use"})
            continue
        removed = broker.runner(["docker", "image", "rm", "--", ref], 120)  # never -f
        status = "error"
        if removed.exit == 0:
            status = "deleted" if "Deleted:" in removed.output else "untagged"
        results.append({"ref": ref, "status": status, "exit": removed.exit})
    if sorted(docker_lines(broker, ["docker", "volume", "ls", "-q"])) != sorted(volumes_before):
        raise Rejected("internal_error", "volume set changed during image removal")  # must never happen
    return {"results": results, "volumes_unchanged": True, "in_use_images_kept": len(used),
            "free_before_gib": round(before_free / 1024**3, 2), "free_after_gib": round(free_bytes() / 1024**3, 2)}


# ----------------------------------------------------------------------------- image reference evidence (#1782)
# Root-side search of the NEXOLAB release, recovery and backup records for each image of a manifest, so a
# removal list is reconciled against records the development account cannot read. Read-only and bounded.
REFERENCE_ROOTS = (
    Path("/etc/nexolab-storage"),
    Path("/etc/systemd/system"),
    Path("/home/nexolab/.config/systemd/user"),
    Path("/home/nexolab/nexolab-platform/.project"),
    Path("/home/nexolab/nexolab-platform/runtime/deployments"),
    Path("/home/nexolab/nexolab-platform/runtime/recovery"),
    Path("/home/nexolab/commander-workspaces"),
    Path("/var/lib/nexolab/version-management"),
    Path("/var/backups/nexolab"),
    Path("/opt/nexolab"),
)
PROTECTED_IMAGES_FILE = Path("/etc/nexolab-storage/protected-images")
REFERENCE_SKIP_DIRS = {"node_modules", ".git", ".next", "__pycache__", ".venv", "venv", ".cache", ".pytest_cache",
                       "image-context", "artifact", ".artifact.staging"}
REFERENCE_SUFFIXES = {".json", ".yaml", ".yml", ".env", ".txt", ".md", ".sh", ".conf", ".service", ".timer",
                      ".toml", ".ini", ".log", ".jsonl", ".py", ""}
REFERENCE_MAX_FILE = 4 * 1024 * 1024
REFERENCE_MAX_FILES = 150_000
REFERENCE_DEADLINE = 900.0
ROLLBACK_WORDS = re.compile(r"rollback|roll_back|previous|protected|recovery|restore|baseline|retain|keep", re.I)


def protected_image_ids() -> set[str]:
    try:
        st = PROTECTED_IMAGES_FILE.lstat()
    except FileNotFoundError:
        return set()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
        raise Rejected("precondition_failed", f"{PROTECTED_IMAGES_FILE} is not a root-owned regular file")
    ids = set()
    for line in PROTECTED_IMAGES_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.split("#", 1)[0].strip()
        if IMAGE_ID.fullmatch(line):
            ids.add(line)
    return ids


def image_references(entries: list[tuple[str, str]], roots: tuple[Path, ...] = REFERENCE_ROOTS) -> dict:
    """Search bounded text records for full ID, 12-char ID, ref and tag of each image (never follows links)."""
    needles: dict[str, set[int]] = {}
    for index, (ref, image_id) in enumerate(entries):
        hex_id = image_id.split(":", 1)[1]
        for needle in (hex_id, hex_id[:12], ref, ref.rsplit(":", 1)[1]):
            if len(needle) >= 12:
                needles.setdefault(needle, set()).add(index)
    pattern = re.compile("|".join(re.escape(n) for n in sorted(needles, key=len, reverse=True)))
    found: list[list[dict]] = [[] for _ in entries]
    scanned, skipped_large, deadline = 0, 0, time.monotonic() + REFERENCE_DEADLINE
    complete = True
    for root in roots:
        if not root.is_dir() or root.is_symlink():
            continue
        for current, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in REFERENCE_SKIP_DIRS)
            for name in sorted(files):
                if scanned >= REFERENCE_MAX_FILES or time.monotonic() > deadline:
                    complete = False
                    break
                path = Path(current) / name
                if path.suffix.lower() not in REFERENCE_SUFFIXES:
                    continue
                try:
                    st = path.lstat()
                    if not stat.S_ISREG(st.st_mode):
                        continue
                    if st.st_size > REFERENCE_MAX_FILE:
                        skipped_large += 1
                        continue
                    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
                    with os.fdopen(fd, "rb") as handle:
                        data = handle.read(REFERENCE_MAX_FILE)
                except OSError:
                    continue
                scanned += 1
                if b"\0" in data[:4096]:
                    continue
                text = data.decode("utf-8", "replace")
                for line in text.splitlines():
                    hits = {i for match in pattern.finditer(line) for i in needles[match.group(0)]}
                    for i in hits:
                        if len(found[i]) < 40:
                            snippet, _ = redact(line.strip()[:240])
                            found[i].append({"path": str(path), "line": snippet,
                                             "rollback_context": bool(ROLLBACK_WORDS.search(line))})
            else:
                continue
            break
    protected = protected_image_ids()
    report = []
    for (ref, image_id), refs in zip(entries, found):
        report.append({"ref": ref, "id": image_id, "references": len(refs),
                       "rollback_references": sum(r["rollback_context"] for r in refs),
                       "in_protected_images_file": image_id in protected, "evidence": refs})
    return {"images": report, "files_scanned": scanned, "skipped_large_files": skipped_large,
            "complete": complete, "roots": [str(r) for r in roots if r.is_dir()]}


def op_storage_image_references(broker: "Broker", args: dict) -> dict:
    """Read-only: reconcile a manifest against root-only release, recovery, backup and protection records."""
    manifest = read_inbox_json(broker, args["manifest_sha256"])
    images = manifest.get("images") if isinstance(manifest, dict) else None
    if not isinstance(images, list) or not 0 < len(images) <= MAX_MANIFEST_IMAGES:
        raise Rejected("precondition_failed", f"manifest needs 1..{MAX_MANIFEST_IMAGES} images")
    entries = []
    for item in images:
        ref, image_id = (item.get("ref"), item.get("id")) if isinstance(item, dict) else (None, None)
        if not (isinstance(ref, str) and IMAGE_REF.fullmatch(ref) and isinstance(image_id, str)
                and IMAGE_ID.fullmatch(image_id)):
            raise Rejected("precondition_failed", "manifest entry needs a NEXOLAB image ref and a sha256 id")
        entries.append((ref, image_id))
    result = image_references(entries)
    result["used_by_containers"] = sorted(set(i for _, i in entries) & used_image_ids(broker))
    return result


NMCLI_FIELD_SPLIT = re.compile(r"(?<!\\):")


def nm_connections(broker: "Broker") -> list[dict]:
    out = broker.runner(["nmcli", "-t", "-f", "NAME,UUID,TYPE,ACTIVE,DEVICE", "connection", "show"], 10).output
    rows = []
    for line in out.splitlines():
        parts = NMCLI_FIELD_SPLIT.split(line)
        if len(parts) == 5:
            rows.append({"name": parts[0].replace("\\:", ":"), "uuid": parts[1], "type": parts[2],
                         "active": parts[3] == "yes", "device": parts[4]})
    return rows


def wifi_profile(broker: "Broker", name: str) -> dict:
    matches = [c for c in nm_connections(broker) if c["name"] == name]
    if len(matches) != 1:
        raise Rejected("precondition_failed", f"expected exactly one profile named {name}, found {len(matches)}")
    if matches[0]["type"] != "802-11-wireless":
        raise Rejected("precondition_failed", "only Wi-Fi profiles are handled")
    return matches[0]


def default_route_device(broker: "Broker") -> str:
    out = broker.runner(["ip", "-4", "route", "show", "default"], 10).output
    best = None
    for line in out.splitlines():
        dev = re.search(r"\bdev (\S+)", line)
        metric = re.search(r"\bmetric (\d+)", line)
        if dev:
            value = int(metric.group(1)) if metric else 0
            if best is None or value < best[0]:
                best = (value, dev.group(1))
    return best[1] if best else ""


def op_wifi_connect_test(broker: "Broker", args: dict) -> dict:
    """One bounded association attempt; the MAC setting is in-memory only and restored; Ethernet stays primary."""
    profile = wifi_profile(broker, args["profile"])
    if default_route_device(broker) != "eth0":
        raise Rejected("precondition_failed", "Ethernet must hold the default route before a Wi-Fi test")
    state = unit_state_props(broker, "NetworkManager.service", "ActiveState")
    if state.get("ActiveState") != "active":
        raise Rejected("precondition_failed", "NetworkManager is not active")
    device = broker.runner(["nmcli", "-g", "GENERAL.STATE", "device", "show", "wlan0"], 10).output.strip()
    if device.startswith("100"):
        raise Rejected("precondition_failed", "wlan0 is already connected")
    uuid = profile["uuid"]
    previous = broker.runner(["nmcli", "-g", "802-11-wireless.cloned-mac-address", "connection", "show", "uuid",
                              uuid], 10).output.strip()
    actions = []
    if args["mac"] == "random":
        r = broker.runner(["nmcli", "connection", "modify", "--temporary", "uuid", uuid,
                           "802-11-wireless.cloned-mac-address", "random"], 15)
        actions.append({"step": "temporary random MAC", "exit": r.exit})
    started = time.time()
    up = broker.runner(["nmcli", "--wait", "45", "connection", "up", "uuid", uuid, "ifname", "wlan0"], 60)
    time.sleep(3)
    evidence = steps(broker, [
        ("device", ["nmcli", "-f", "GENERAL.STATE,GENERAL.REASON,GENERAL.HWADDR,IP4.ADDRESS,IP4.GATEWAY", "device",
                    "show", "wlan0"]),
        ("link", ["iw", "dev", "wlan0", "link"]),
        ("routes", ["ip", "-4", "route", "show", "default"]),
    ], 20)
    supplicant = filtered(broker, ["journalctl", "-u", "wpa_supplicant", "--since", f"@{int(started) - 2}",
                                   "--no-pager", "-o", "short-iso", "-q"],
                          r"reason|status_code|ASSOC|WRONG_KEY|TEMP-DISABLED|CONNECTED|DISCONNECTED|auth", 40, 15)
    connected = up.exit == 0
    if args["mac"] == "random":
        if connected:  # diagnosis only: never leave the profile up on a random MAC
            down = broker.runner(["nmcli", "connection", "down", "uuid", uuid], 30)
            actions.append({"step": "down after random-MAC test", "exit": down.exit})
        r = broker.runner(["nmcli", "connection", "modify", "--temporary", "uuid", uuid,
                           "802-11-wireless.cloned-mac-address", previous if previous not in ("--",) else ""], 15)
        actions.append({"step": "restore MAC setting", "exit": r.exit, "value": previous or "(default)"})
    after_route = default_route_device(broker)
    return {"profile": profile["name"], "mac": args["mac"], "connected": connected, "nmcli_exit": up.exit,
            "nmcli_output": up.output[-1500:], "actions": actions, "evidence": evidence["steps"],
            "supplicant": supplicant["steps"][0]["output"], "ethernet_primary_after": after_route == "eth0",
            "kept_up": connected and args["mac"] == "permanent"}


def op_wifi_profile_remove(broker: "Broker", args: dict) -> dict:
    """Owner-approved deletion of one inactive Wi-Fi profile (irreversible: the owner re-creates it if needed)."""
    profile = wifi_profile(broker, args["profile"])
    if profile["active"]:
        raise Rejected("precondition_failed", "refusing to delete the active connection")
    result = broker.runner(["nmcli", "connection", "delete", "uuid", profile["uuid"]], 30)
    remaining = [c["name"] for c in nm_connections(broker) if c["type"] == "802-11-wireless"]
    return {"deleted": profile["name"], "exit": result.exit, "remaining_wifi_profiles": remaining,
            "gone": profile["name"] not in remaining}


# ----------------------------------------------------------------------------- DR backup (#1775, #1428)
DR_UNIT = "nexolab-dr-backup.service"
DR_TIMER = "nexolab-dr-backup.timer"
DR_CONFIG = Path("/etc/nexolab/dr-backup.json")
DR_DIR = Path("/var/backups/nexolab/dr")
DR_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")


def op_backup_health(broker: "Broker", _args: dict) -> dict:
    """Read-only DR state: units, config presence (never contents), bundles, free space vs reserve."""
    props = "LoadState,ActiveState,SubState,Result,UnitFileState,ExecMainStatus,ExecMainExitTimestamp"
    units = {DR_UNIT: unit_state_props(broker, DR_UNIT, props),
             DR_TIMER: unit_state_props(broker, DR_TIMER, "LoadState,ActiveState,UnitFileState,LastTriggerUSec,"
                                                          "NextElapseUSecRealtime")}
    bundles = []
    if DR_DIR.is_dir():
        entries = sorted(DR_DIR.iterdir(), key=lambda e: e.lstat().st_mtime, reverse=True)
        for entry in entries[:30]:
            st = entry.lstat()
            if DR_NAME.fullmatch(entry.name) and stat.S_ISREG(st.st_mode):
                bundles.append({"name": entry.name, "bytes": st.st_size, "mode": oct(stat.S_IMODE(st.st_mode)),
                                "mtime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime))})
    free = free_bytes()
    return {"units": units, "config_present": DR_CONFIG.is_file(), "backup_dir_present": DR_DIR.is_dir(),
            "bundles": bundles, "free_gib": round(free / 1024**3, 2), "reserve_gib": 20,
            "statement": "A captured bundle is CAPTURED_RESTORE_UNVERIFIED until an isolated restore (#1632) passes."}


def op_backup_start(broker: "Broker", _args: dict) -> dict:
    """Owner-approved: start the owner-installed DR backup once (same as its timer), never install it."""
    state = unit_state_props(broker, DR_UNIT, "LoadState,ActiveState,FragmentPath")
    if state.get("LoadState") != "loaded":
        raise Rejected("precondition_failed", f"{DR_UNIT} is not installed (owner activation of #1630 first)")
    if not DR_CONFIG.is_file():
        raise Rejected("precondition_failed", f"{DR_CONFIG} missing (owner provisions keys and config)")
    if state.get("ActiveState") in ("active", "activating"):
        raise Rejected("busy", f"{DR_UNIT} is already running")
    if free_bytes() < 28 * 1024**3:
        raise Rejected("precondition_failed", "less than 28 GiB free (8 GiB bundle + 20 GiB reserve)")
    started = broker.runner(["systemctl", "start", "--no-block", DR_UNIT], 20)
    time.sleep(5)
    return {"exit": started.exit, "after": unit_state_props(broker, DR_UNIT, "ActiveState,SubState,Result"),
            "follow_with": "backup.health and logs.unit unit=nexolab-dr-backup.service"}


def unit_state_props(broker: "Broker", unit: str, props: str) -> dict:
    out = broker.runner(["systemctl", "show", unit, "--no-pager", "-p", props], 10).output
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def production_ops() -> dict[str, Operation]:
    unit = Enum(READABLE_UNITS)
    boot = Enum(("0", "-1", "-2"), "0")
    lines = Int(1, 400, 100)
    ops = [
        Operation("broker.list", "read", "Operations, kinds and argument schemas", op_list),
        Operation("system.summary", "read", "Uptime, memory, disk, temperature, throttling, failed units, time",
                  op_system_summary),
        Operation("system.power", "read", "Throttling/undervoltage flags, temperature, voltages, 5 V input",
                  op_system_power),
        Operation("system.boots", "read", "Boot list and the last lines of the previous boot", op_system_boots),
        Operation("logs.unit", "read", "Journal of an allow-listed unit (redacted)", op_logs_unit,
                  {"unit": unit, "boot": boot, "lines": lines,
                   "priority": Enum(("debug", "info", "notice", "warning", "err"), "info")}),
        Operation("logs.kernel", "read", "Kernel messages matching a fixed category", op_logs_kernel,
                  {"filter": Enum(tuple(KERNEL_FILTERS)), "boot": boot, "lines": lines}),
        Operation("logs.system", "read", "System journal matching a fixed category", op_logs_system,
                  {"filter": Enum(tuple(SYSTEM_FILTERS)), "boot": boot, "lines": lines}, timeout=60),
        Operation("service.status", "read", "State of an allow-listed unit", op_service_status, {"unit": unit}),
        Operation("service.list", "read", "NEXOLAB and platform units and timers", op_service_list),
        Operation("docker.containers", "read", "Containers with image, state, health, ports, networks",
                  op_docker_containers),
        Operation("docker.container", "read", "Sanitized identity/health/network/mount metadata (no env)",
                  op_docker_container, {"name": Name(CONTAINER_NAME)}),
        Operation("docker.logs", "read", "Recent container log lines (redacted)", op_docker_logs,
                  {"name": Name(CONTAINER_NAME), "lines": Int(1, 400, 100), "since_minutes": Int(1, 1440, 60)}),
        Operation("docker.networks", "read", "Docker networks and attachments", op_docker_networks),
        Operation("docker.images", "read", "Images with digests and which containers use them", op_docker_images,
                  timeout=60),
        Operation("docker.disk", "read", "docker system df", op_docker_disk, timeout=130, heavy=True),
        Operation("network.summary", "read", "Addresses, links, routes, DNS, NM devices, listeners, DHCP",
                  op_network_summary),
        Operation("wifi.diagnose", "read", "Wi-Fi profile (no secrets), scan cache, link, regdom, driver, reasons",
                  op_wifi_diagnose, timeout=90),
        Operation("storage.summary", "read", "Filesystems, inodes, block devices, journal usage",
                  op_storage_summary, timeout=60),
        Operation("storage.inventory", "read", "Full read-only #1710 inventory report (pinned handler)",
                  op_storage_inventory, timeout=1600, heavy=True),
        Operation("system.reset-reason", "read", "SoC reset status, PMIC/supply device-tree data, watchdog, boots",
                  op_system_reset_reason),
        Operation("logs.boot-end", "read", "Last journal lines of a previous boot (clean shutdown vs abrupt stop)",
                  op_logs_boot_end, {"boot": Enum(("-1", "-2", "-3", "-4", "-5")), "lines": Int(1, 400, 120)}),
        Operation("docker.service-model", "read", "WP2c Phase 0: NEXOLAB container/network model without secret values",
                  op_docker_runtime_model, timeout=120),
        Operation("storage.cleanup-regenerable", "approved",
                  "Owner-approved T1: build cache (>7 days or all unused), untagged unused images, journal to 200M",
                  op_storage_cleanup_regenerable, {"build_cache": Enum(tuple(BUILD_CACHE_PRUNE), "older-than-7d")},
                  timeout=1200, heavy=True),
        Operation("service.retire-legacy-https", "approved",
                  "Owner-approved: stop and mask the prepared-only legacy HTTPS pair that restart-loops",
                  op_service_retire_legacy_https, timeout=120),
        Operation("service.restore-legacy-https", "approved", "Owner-approved undo of retire-legacy-https",
                  op_service_restore_legacy_https, timeout=120),
        Operation("deploy.lan-frontend", "approved",
                  "Owner-approved WP2c Stage 2 LAN dashboard: prepare | execute | rollback (pinned tool, bound artifact)",
                  op_deploy_lan_frontend,
                  {"phase": Enum(("prepare", "execute", "rollback")),
                   "artifact_sha256": Name(SHA256_OR_NONE, "none"),
                   "expect_current_source": Name(SOURCE_SHA),
                   "expect_current_build": Name(BUILD_ID)}, timeout=3100),
        Operation("storage.remove-images", "approved",
                  "Owner-approved: remove the exact unused NEXOLAB images of a hash-bound inbox manifest (never -f)",
                  op_storage_remove_images, {"manifest_sha256": Name(SHA256)}, timeout=1800, heavy=True),
        Operation("storage.image-references", "read",
                  "Reconcile an inbox image manifest against root-only release/rollback/recovery/backup records",
                  op_storage_image_references, {"manifest_sha256": Name(SHA256)}, timeout=1000, heavy=True),
        Operation("wifi.connect-test", "approved",
                  "Owner-approved: one bounded Wi-Fi association attempt (in-memory MAC mode, Ethernet stays primary)",
                  op_wifi_connect_test, {"profile": Name(WIFI_PROFILE_NAME), "mac": Enum(("permanent", "random"))},
                  timeout=150),
        Operation("wifi.profile-remove", "approved", "Owner-approved: remove one inactive Wi-Fi profile",
                  op_wifi_profile_remove, {"profile": Name(WIFI_PROFILE_NAME)}, timeout=60),
        Operation("backup.health", "read", "DR backup units, config presence, bundle list, free space vs reserve",
                  op_backup_health),
        Operation("backup.start", "approved", "Owner-approved: start the installed DR backup unit once (#1630)",
                  op_backup_start, timeout=60),
        Operation("service.recover", "recover", "Restart an enabled NEXOLAB unit that is down / run endpoint repair",
                  op_service_recover, {"unit": Enum(tuple(RECOVERABLE_UNITS))}, timeout=90),
    ]
    return {o.name: o for o in ops}


# ----------------------------------------------------------------------------- audit


class Audit:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.seq = 0
        self.prev = "0" * 64
        self.seen: collections.OrderedDict[str, float] = collections.OrderedDict()
        if path.exists():
            with path.open("rb") as handle:
                for raw in collections.deque(handle, maxlen=REPLAY_MEMORY):
                    try:
                        entry = json.loads(raw)
                    except ValueError:
                        continue
                    self.seq, self.prev = entry.get("seq", self.seq), entry.get("hash", self.prev)
                    if entry.get("request_id"):
                        self.remember(entry["request_id"], entry.get("ts", 0.0))

    def remember(self, request_id: str, ts: float) -> None:
        self.seen[request_id] = ts
        while len(self.seen) > REPLAY_MEMORY:
            self.seen.popitem(last=False)

    def claim(self, request_id: str) -> None:
        with self.lock:
            if request_id in self.seen:
                raise Rejected("replay", request_id)
            self.remember(request_id, time.time())

    def append(self, record: dict) -> dict:
        with self.lock:
            self.seq += 1
            entry = {"seq": self.seq, "ts": round(time.time(), 3), "prev": self.prev, **record}
            body = json.dumps(entry, sort_keys=True, separators=(",", ":"))
            entry["hash"] = hashlib.sha256(body.encode()).hexdigest()
            line = json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n"
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
            try:
                os.write(fd, line.encode())
                os.fsync(fd)
            finally:
                os.close(fd)
            self.prev = entry["hash"]
            return {"seq": entry["seq"], "hash": entry["hash"]}


def verify_audit(path: Path) -> tuple[bool, int, str]:
    prev, count = "0" * 64, 0
    with path.open("rb") as handle:
        for number, raw in enumerate(handle, 1):
            entry = json.loads(raw)
            claimed = entry.pop("hash")
            if entry.get("prev") != prev:
                return False, number, "broken chain"
            body = json.dumps(entry, sort_keys=True, separators=(",", ":"))
            if hashlib.sha256(body.encode()).hexdigest() != claimed:
                return False, number, "hash mismatch"
            prev, count = claimed, number
    return True, count, prev


# ----------------------------------------------------------------------------- approvals


def consume_approval(broker: "Broker", approval_id: Any, op: str, args: dict) -> dict:
    if type(approval_id) is not str or not APPROVAL_ID.fullmatch(approval_id):
        raise Rejected("approval_required", "this operation needs an owner approval id")
    assert_trusted(broker.approval_dir, broker.trusted_uid, directory=True)
    path = broker.approval_dir / f"{approval_id}.json"
    try:
        assert_trusted(path, broker.trusted_uid, directory=False)
    except Rejected:
        raise Rejected("approval_invalid", "approval missing, used or not owner-controlled") from None
    if stat.S_IMODE(path.lstat().st_mode) & 0o077:
        raise Rejected("approval_invalid", "approval file must be mode 0600")
    try:
        approval = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise Rejected("approval_invalid", "unreadable approval") from None
    if approval.get("approval_id") != approval_id or approval.get("op") != op or approval.get("args") != args:
        raise Rejected("approval_mismatch", "approval is for a different operation or arguments")
    if not isinstance(approval.get("expires_at"), (int, float)) or approval["expires_at"] < time.time():
        raise Rejected("approval_expired", approval_id)
    used = path.with_name(f"{approval_id}.used-{int(time.time())}")
    os.rename(path, used)  # single use: consumed before the handler runs
    return {"approval_id": approval_id, "approved_by": approval.get("approved_by"), "reason": approval.get("reason")}


def cmd_approve(ns: argparse.Namespace) -> int:
    if os.geteuid() != 0:
        print("approve must run as root (owner via sudo); the development account cannot approve", file=sys.stderr)
        return 77
    ops = production_ops()
    if ns.op not in ops or ops[ns.op].kind != "approved":
        print(f"unknown or not approval-gated operation: {ns.op}", file=sys.stderr)
        return 64
    raw: dict[str, Any] = {}
    for item in ns.arg or []:
        key, _, value = item.partition("=")
        raw[key] = int(value) if re.fullmatch(r"-?\d{1,9}", value) else value  # hashes stay strings
    try:
        args = validate_args(ops[ns.op].schema, raw)
    except Rejected as exc:
        print(f"invalid arguments: {exc.code} {exc.detail}", file=sys.stderr)
        return 64
    approval_id = secrets.token_hex(16)
    record = {"approval_id": approval_id, "op": ns.op, "args": args,
              "expires_at": time.time() + ns.ttl_minutes * 60,
              "approved_by": os.environ.get("SUDO_USER", "root"), "reason": ns.reason[:300]}
    APPROVAL_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = APPROVAL_DIR / f"{approval_id}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(record, handle, sort_keys=True)
    print(json.dumps({"approval_id": approval_id, "op": ns.op, "args": args,
                      "expires_in_minutes": ns.ttl_minutes}, sort_keys=True))
    return 0


# ----------------------------------------------------------------------------- server


class Broker:
    def __init__(self, *, ops: dict[str, Operation], allowed_uids: set[int], trusted_uid: int, install_dir: Path,
                 audit_path: Path, approval_dir: Path, report_dir: Path, lock_file: Path,
                 runner: Callable[[list[str], float], RunResult] = run) -> None:
        self.ops = ops
        self.allowed_uids = allowed_uids
        self.trusted_uid = trusted_uid
        self.install_dir = install_dir
        self.approval_dir = approval_dir
        self.report_dir = report_dir
        self.lock_file = lock_file
        self.runner = runner
        self.audit = Audit(audit_path)
        self.slots = threading.BoundedSemaphore(MAX_CONCURRENT)
        self.heavy = threading.Lock()
        self.mutation = threading.Lock()

    def self_check(self) -> None:
        assert_trusted(Path(__file__).resolve(), self.trusted_uid, directory=False)
        assert_trusted(self.install_dir, self.trusted_uid, directory=True)
        for child in sorted(self.install_dir.rglob("*")):
            assert_trusted(child, self.trusted_uid, directory=child.is_dir() and not child.is_symlink())
        if self.approval_dir.exists():
            assert_trusted(self.approval_dir, self.trusted_uid, directory=True)

    def handle(self, raw: bytes, peer: tuple[int, int, int]) -> dict:
        pid, uid, _gid = peer
        record: dict[str, Any] = {"peer_uid": uid, "peer_pid": pid}
        started = time.monotonic()
        try:
            if uid not in self.allowed_uids:
                raise Rejected("unauthorized_peer", f"uid {uid}")
            if len(raw) > MAX_REQUEST_BYTES:
                raise Rejected("request_too_large")
            try:
                request = json.loads(raw)
            except ValueError:
                raise Rejected("invalid_request", "not JSON") from None
            if not isinstance(request, dict):
                raise Rejected("invalid_request", "not an object")
            unknown = set(request) - {"v", "op", "args", "request_id", "ts", "approval_id"}
            if unknown:
                raise Rejected("invalid_request", f"unknown fields {sorted(unknown)}")
            if request.get("v") != PROTOCOL:
                raise Rejected("unsupported_protocol")
            op_name = request.get("op")
            if type(op_name) is not str or not OP_NAME.fullmatch(op_name):
                raise Rejected("invalid_request", "op")
            record["op"] = op_name
            request_id = request.get("request_id")
            if type(request_id) is not str or not REQUEST_ID.fullmatch(request_id):
                raise Rejected("invalid_request", "request_id must be a lowercase UUID4")
            record["request_id"] = request_id
            ts = request.get("ts")
            if type(ts) not in (int, float) or abs(time.time() - ts) > CLOCK_SKEW_SECONDS:
                raise Rejected("stale_request", "timestamp outside the replay window")
            op = self.ops.get(op_name)
            if op is None:
                raise Rejected("unknown_operation", op_name)
            args = validate_args(op.schema, request.get("args", {}))
            record["args"] = args
            self.audit.claim(request_id)
            if not self.slots.acquire(blocking=False):
                raise Rejected("busy", "too many concurrent requests")
            try:
                result = self.execute(op, args, request.get("approval_id"), record)
            finally:
                self.slots.release()
            result, redactions = redact_tree(result)
            encoded = json.dumps(result, sort_keys=True).encode()
            if len(encoded) > 2 * MAX_OUTPUT_BYTES:
                result = {"truncated_response": encoded[: MAX_OUTPUT_BYTES].decode("utf-8", "replace")}
                encoded = json.dumps(result).encode()
            record.update(status="ok", redactions=redactions, output_sha256=hashlib.sha256(encoded).hexdigest(),
                          output_bytes=len(encoded))
            response = {"ok": True, "op": op_name, "request_id": request_id, "result": result}
        except Rejected as exc:
            record.update(status="rejected", error=exc.code, detail=redact(exc.detail)[0])
            response = {"ok": False, "error": exc.code, "detail": record["detail"],
                        "request_id": record.get("request_id"), "op": record.get("op")}
        except Exception as exc:  # noqa: BLE001 - never leak a traceback to the caller
            record.update(status="error", error="internal_error", detail=type(exc).__name__)
            response = {"ok": False, "error": "internal_error", "request_id": record.get("request_id")}
        record["duration_ms"] = int((time.monotonic() - started) * 1000)
        response["receipt"] = self.audit.append(record)
        return response

    def execute(self, op: Operation, args: dict, approval_id: Any, record: dict) -> dict:
        if op.kind == "read":
            if op.heavy:
                if not self.heavy.acquire(blocking=False):
                    raise Rejected("busy", "another heavy diagnostic is running")
                try:
                    return op.handler(self, args)
                finally:
                    self.heavy.release()
            return op.handler(self, args)
        if op.kind not in ("recover", "approved"):
            raise Rejected("internal_error", "unknown operation kind")
        self.self_check()  # privileged code must still be owner-controlled before any change
        if not self.mutation.acquire(blocking=False):
            raise Rejected("busy", "another state-changing operation is running")
        try:
            self.lock_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.lock_file, "a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise Rejected("busy", "mutation lock held") from None
                if op.kind == "approved":
                    record["approval"] = consume_approval(self, approval_id, op.name, args)
                return op.handler(self, args)
        finally:
            self.mutation.release()


def peer_credentials(sock: socket.socket) -> tuple[int, int, int]:
    data = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    return struct.unpack("3i", data)


def read_request(sock: socket.socket) -> bytes:
    sock.settimeout(10)
    data = b""
    while b"\n" not in data and len(data) <= MAX_REQUEST_BYTES:
        chunk = sock.recv(MAX_REQUEST_BYTES + 1)
        if not chunk:
            break
        data += chunk
    if b"\n" not in data and len(data) > MAX_REQUEST_BYTES:
        drained = 0  # let an oversized sender finish, so it can read the rejection
        try:
            while drained < 1024 * 1024 and (chunk := sock.recv(65536)):
                drained += len(chunk)
        except OSError:
            pass
    return data.split(b"\n", 1)[0] if b"\n" in data else data


def make_server(broker: Broker, listener: socket.socket) -> socketserver.ThreadingUnixStreamServer:
    class Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            try:
                peer = peer_credentials(self.request)
                raw = read_request(self.request)
            except (OSError, struct.error):
                return
            response = broker.handle(raw, peer)
            try:
                self.request.settimeout(30)
                self.request.sendall(json.dumps(response, sort_keys=True).encode() + b"\n")
            except OSError:
                pass

    server = socketserver.ThreadingUnixStreamServer(listener.getsockname(), Handler, bind_and_activate=False)
    server.socket.close()
    server.socket = listener
    server.daemon_threads = True
    return server


def systemd_listener() -> socket.socket | None:
    if os.environ.get("LISTEN_PID") == str(os.getpid()) and os.environ.get("LISTEN_FDS") == "1":
        return socket.socket(fileno=3)
    return None


def cmd_serve(ns: argparse.Namespace) -> int:
    test_mode = ns.test_socket is not None
    if test_mode and os.geteuid() == 0:
        print("test options are refused when running as root", file=sys.stderr)
        return 77
    allowed = {int(u) for u in (ns.allowed_uids or os.environ.get(ALLOWED_UIDS_ENV, "")).split(",") if u.strip()}
    if not allowed or (not test_mode and 0 in allowed):
        print("no allowed peer uid configured (root is never a client)", file=sys.stderr)
        return 78
    ops = production_ops()
    if test_mode:
        from importlib import util  # test-only operations, never loaded by the installed unit
        spec = util.spec_from_file_location("broker_test_ops", ns.test_ops)
        module = util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        ops.update(module.operations(sys.modules[__name__]))
    root = Path(ns.state_root) if ns.state_root else None
    broker = Broker(
        ops=ops, allowed_uids=allowed, trusted_uid=os.geteuid() if test_mode else 0,
        install_dir=Path(ns.install_dir) if ns.install_dir else INSTALL_DIR,
        audit_path=root / "audit.jsonl" if root else AUDIT_LOG,
        approval_dir=root / "approvals" if root else APPROVAL_DIR,
        report_dir=root / "reports" if root else REPORT_DIR,
        lock_file=root / "mutation.lock" if root else LOCK_FILE)
    try:
        broker.self_check()
    except Rejected as exc:
        print(f"REFUSING TO START: {exc.code} {exc.detail}", file=sys.stderr)
        return 78
    if test_mode:
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(ns.test_socket)
        listener.listen(16)
    else:
        listener = systemd_listener()
        if listener is None:
            print("expected a systemd socket on fd 3 (nexolab-operator-broker.socket)", file=sys.stderr)
            return 78
    server = make_server(broker, listener)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    print(f"nexolab-operator-broker {VERSION} ready ops={len(ops)} allowed_uids={sorted(allowed)}", flush=True)
    server.serve_forever(poll_interval=0.5)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--allowed-uids")
    serve.add_argument("--install-dir")
    serve.add_argument("--state-root", help=argparse.SUPPRESS)
    serve.add_argument("--test-socket", help=argparse.SUPPRESS)
    serve.add_argument("--test-ops", help=argparse.SUPPRESS)
    approve = sub.add_parser("approve")
    approve.add_argument("--op", required=True)
    approve.add_argument("--arg", action="append")
    approve.add_argument("--ttl-minutes", type=int, default=60, choices=range(1, 24 * 60 + 1), metavar="1..1440")
    approve.add_argument("--reason", default="")
    check = sub.add_parser("verify-audit")
    check.add_argument("path", nargs="?", default=str(AUDIT_LOG))
    ns = parser.parse_args(argv)
    if ns.command == "serve":
        if (ns.state_root or ns.test_ops) and not ns.test_socket:
            parser.error("--state-root/--test-ops are test-only and require --test-socket")
        return cmd_serve(ns)
    if ns.command == "approve":
        return cmd_approve(ns)
    ok, count, last = verify_audit(Path(ns.path))
    print(json.dumps({"ok": ok, "entries": count, "last": last}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
