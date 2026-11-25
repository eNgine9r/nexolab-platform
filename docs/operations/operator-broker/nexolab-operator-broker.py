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

VERSION = "1.0.0"
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
                r"|private[_-]?key|credential|cookie|authorization|wep-key\d?)[a-z0-9_.-]*)"
                r"(\s*[:=]\s*|\s+)(?!\[REDACTED)(\"[^\"]*\"|'[^']*'|\S+)"),
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


def run(argv: list[str], timeout: float, *, max_bytes: int = MAX_OUTPUT_BYTES, stdin: bytes | None = None) -> RunResult:
    """Run a fixed argv without a shell, a clean environment, a timeout and an output cap."""
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
    return RunResult(None if timed_out else proc.returncode, b"".join(chunks).decode("utf-8", "replace"),
                     truncated, timed_out)


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
    result = broker.runner(argv, timeout)
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


def op_logs_unit(broker: "Broker", args: dict) -> dict:
    return steps(broker, [(args["unit"], [
        "journalctl", "-u", args["unit"], "-b", args["boot"], "-n", str(args["lines"]), "-p", args["priority"],
        "--no-pager", "-o", "short-iso", "-q"])], 30)


def op_logs_kernel(broker: "Broker", args: dict) -> dict:
    return filtered(broker, ["journalctl", "-k", "-b", args["boot"], "--no-pager", "-o", "short-iso", "-q"],
                    KERNEL_FILTERS[args["filter"]], args["lines"], 30)


def op_logs_system(broker: "Broker", args: dict) -> dict:
    return filtered(broker, ["journalctl", "-b", args["boot"], "-n", "20000", "--no-pager", "-o", "short-iso", "-q"],
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
        raw[key] = int(value) if re.fullmatch(r"-?\d+", value) else value
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
