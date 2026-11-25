#!/usr/bin/env python3
"""NEXOLAB P0 network-change recovery: interim compatibility service address.

Owner-run as the operator account (uid 1000, docker group, sudo for `ip` and
`sysctl` only). Restores the existing LOCAL_LAN runtime after the host moved
to another network, WITHOUT changing any Compose file, environment file,
image, volume, network, credential or hardware configuration.

Cause: the installed runtime publishes the Telemetry API, central MQTT,
object storage and the LAN Dashboard on the former DHCP address
172.18.48.66, and the Edge MQTT bridge, HTTPS gateway and dev guard use it as
their private API/MQTT origin. After the move that address no longer exists,
so Docker cannot bind it ("cannot assign requested address").

Recovery: add 172.18.48.66/32 as a host-local alias on `lo` (label
lo:nxcompat), then `docker start` only the existing containers that failed to
bind it and `docker restart` only running containers whose published ports
on it are missing. Containers are never recreated; IDs, images and mounts
are verified unchanged. Host-local consumers (Edge bridge, HTTPS/Tailscale
UI, lab.nexolab, Pi kiosk, dev guard) work again. Browsers on OTHER LAN
clients cannot reach a host-local alias: the LAN build has that address
compiled in, which the network-independent WP2 removes.

    diagnose  (default, read-only)
    apply     add the alias (transient, lost on reboot), start/rebind, verify
    rollback  remove the alias and restore the recorded arp_ignore values
    install-boot-compat / remove-boot-compat
              optional interim systemd unit adding the alias before Docker at
              boot, until WP2 replaces it

Refuses to act on the former laboratory network itself (when a physical
interface route already covers 172.18.48.66) and when another interface
holds that address. Never prunes, removes, recreates or writes to hardware.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from ipaddress import ip_address, ip_network
from pathlib import Path

COMPAT_IP = "172.18.48.66"
LABEL = "lo:nxcompat"
PROJECTS = ("nexolab-central", "nexolab-edge")
ORDER = ("postgres", "minio", "object-storage", "versitygw", "mqtt", "telemetry-service", "dashboard")
PHYSICAL = ("eth0", "wlan0")
LOCK = Path("/tmp/nexolab-current-head-launch.lock")
EVIDENCE = Path.home() / "nexolab-recovery-evidence"
UNIT = Path("/etc/systemd/system/nexolab-compat-address.service")
IP = "/usr/sbin/ip"
SYSCTL = "/usr/sbin/sysctl"
UNIT_TEXT = f"""[Unit]
Description=NEXOLAB interim compatibility service address {COMPAT_IP}/32 on lo (P0 network recovery, until WP2)
DefaultDependencies=no
Before=network-pre.target docker.service
Wants=network-pre.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -ec '{IP} -4 -o addr show dev lo | grep -q " {COMPAT_IP}/32 " || {IP} addr add {COMPAT_IP}/32 dev lo label {LABEL}'
ExecStart=-{SYSCTL} -q -w net.ipv4.conf.eth0.arp_ignore=1
ExecStart=-{SYSCTL} -q -w net.ipv4.conf.wlan0.arp_ignore=1

[Install]
WantedBy=multi-user.target
"""


class Blocked(Exception):
    pass


def run(*args: str, timeout: int = 60, check: bool = True) -> str:
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
    if check and result.returncode:
        raise Blocked(f"COMMAND_FAILED {' '.join(args[:4])}: {result.stderr.strip()[-400:]}")
    return result.stdout.strip()


def addresses() -> list[tuple[str, str]]:
    out = []
    for line in run(IP, "-4", "-o", "addr", "show").splitlines():
        parts = line.split()
        out.append((parts[1], parts[3]))
    return out


def compat_holders() -> list[str]:
    return [dev for dev, cidr in addresses() if cidr.split("/")[0] == COMPAT_IP]


def physical_routes_covering() -> list[str]:
    hits = []
    for line in run(IP, "-4", "route", "show", "table", "main").splitlines():
        parts = line.split()
        if not parts or parts[0] == "default" or "dev" not in parts:
            continue
        dev = parts[parts.index("dev") + 1]
        if dev.startswith(("br-", "docker", "veth", "lo", "tailscale")):
            continue
        try:
            if ip_address(COMPAT_IP) in ip_network(parts[0], strict=False):
                hits.append(line)
        except ValueError:
            continue
    return hits


def containers() -> list[dict]:
    ids = run("docker", "ps", "-aq", "--filter", "name=nexolab").split()
    return json.loads(run("docker", "inspect", *ids)) if ids else []


def summary(c: dict) -> dict:
    labels = c["Config"].get("Labels") or {}
    binds = c["HostConfig"].get("PortBindings") or {}
    actual = c["NetworkSettings"].get("Ports") or {}
    return {
        "id": c["Id"],
        "name": c["Name"].lstrip("/"),
        "project": labels.get("com.docker.compose.project", ""),
        "service": labels.get("com.docker.compose.service", ""),
        "image": c["Image"],
        "state": c["State"]["Status"],
        "health": (c["State"].get("Health") or {}).get("Status", "-"),
        "error": c["State"].get("Error", ""),
        "restarts": c.get("RestartCount", 0),
        "bound_ips": sorted({b.get("HostIp", "") for v in binds.values() for b in (v or [])}),
        "configured_ports": sorted(f"{b.get('HostIp')}:{b.get('HostPort')}->{p}" for p, v in binds.items() for b in (v or [])),
        "published_ports": sorted(f"{b.get('HostIp')}:{b.get('HostPort')}->{p}" for p, v in actual.items() for b in (v or [])),
        "networks": sorted((c["NetworkSettings"].get("Networks") or {}).keys()),
        "mounts": sorted(f"{m.get('Name') or m.get('Source')}:{m.get('Destination')}" for m in c.get("Mounts", [])),
    }


def http(url: str, timeout: int = 6) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as res:
            return res.status, res.read(4000).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - diagnostic only
        return 0, f"{exc.__class__.__name__}: {str(exc)[:160]}"


def probes() -> dict:
    result = {}
    for name, url in (
        ("telemetry_ready", f"http://{COMPAT_IP}:8082/health/ready"),
        ("device_agent", "http://127.0.0.1:8081/health"),
        ("lan_dashboard_identity", f"http://{COMPAT_IP}:3000/api/runtime-identity"),
        ("https_ui_identity", "http://127.0.0.1:3105/api/runtime-identity"),
        ("lab_ui_identity", "http://127.0.0.1:3104/api/runtime-identity"),
    ):
        status, body = http(url)
        brief = body[:300]
        try:
            data = json.loads(body)
            keep = ("status", "ingestion_lag_seconds", "database", "mqtt", "mqtt_connected", "queue_size",
                    "last_publish_at", "source_commit", "build_id")
            brief = {k: data[k] for k in keep if k in data}
        except ValueError:
            pass
        result[name] = {"http": status, "body": brief}
    return result


def edge_broker(items: list[dict]) -> dict:
    """Read-only Edge MQTT bridge state: $SYS counters and recent bridge log lines."""
    broker = next((c for c in items if c["project"] == "nexolab-edge" and c["service"] == "mqtt" and c["state"] == "running"), None)
    if not broker:
        return {"edge_mqtt": "not running or not found"}
    env = json.loads(run("docker", "inspect", "--format", "{{json .Config.Env}}", broker["id"]))
    target = {k: v for k, v in (e.split("=", 1) for e in env if "=" in e) if k in ("CENTRAL_MQTT_HOST", "CENTRAL_MQTT_PORT")}
    sys_topics = run("docker", "exec", broker["id"], "mosquitto_sub", "-h", "127.0.0.1", "-p", "1883", "-v", "-W", "15", "-C", "4",
                     "-t", "$SYS/broker/store/messages/count", "-t", "$SYS/broker/publish/messages/dropped",
                     "-t", "$SYS/broker/clients/connected", "-t", "$SYS/broker/messages/stored", timeout=30, check=False)
    logs = subprocess.run(["docker", "logs", "--since", "12h", broker["id"]], text=True, capture_output=True, timeout=60, check=False)
    lines = [ln for ln in (logs.stdout + logs.stderr).splitlines()
             if any(k in ln for k in ("edge-node-to-central", "onnecting bridge", "ridge", "Socket error", "max_queued"))]
    return {"container": broker["name"], "bridge_target": target, "sys": sys_topics.splitlines(), "bridge_log_tail": lines[-8:]}


def evidence_dir() -> Path:
    path = EVIDENCE / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path.mkdir(parents=True, mode=0o700)
    return path


def dump(path: Path, name: str, data: object) -> None:
    (path / name).write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def diagnose(save: Path | None = None) -> dict:
    items = [summary(c) for c in containers()]
    report = {
        "at": datetime.now(UTC).isoformat(),
        "addresses": addresses(),
        "compat_ip_holders": compat_holders(),
        "physical_routes_covering_compat_ip": physical_routes_covering(),
        "default_route": run(IP, "-4", "route", "show", "default", check=False),
        "arp_ignore": {d: run(SYSCTL, "-n", f"net.ipv4.conf.{d}.arp_ignore", check=False) for d in PHYSICAL},
        "containers": items,
        "edge_broker": edge_broker(items),
        "probes": probes(),
        "boot_compat_unit": UNIT.exists(),
    }
    if save:
        dump(save, "diagnose.json", report)
    print("== addresses:", report["addresses"])
    print("== compat ip holders:", report["compat_ip_holders"] or "none", "| physical route covering:", report["physical_routes_covering_compat_ip"] or "none")
    print("== containers (name state health restarts | configured -> published | networks | error)")
    for c in items:
        print(f"  {c['name']:42} {c['state']:9} {c['health']:9} r={c['restarts']} | {','.join(c['configured_ports']) or '-'} -> "
              f"{','.join(c['published_ports']) or '-'} | {','.join(c['networks']) or 'NO NETWORKS'} | {c['error'][:90]}")
    print("== edge broker:", json.dumps(report["edge_broker"], indent=1))
    print("== probes:", json.dumps(report["probes"], indent=1))
    return report


def affected(items: list[dict]) -> list[dict]:
    hit = [c for c in items if COMPAT_IP in c["bound_ips"]
           or (c["project"] in PROJECTS and c["state"] == "running" and ports_missing(c))]
    foreign = [c["name"] for c in hit if c["project"] not in PROJECTS]
    if foreign:
        raise Blocked(f"UNEXPECTED_PROJECT_BINDS_COMPAT_IP {foreign}")
    rank = {s: i for i, s in enumerate(ORDER)}
    return sorted(hit, key=lambda c: next((rank[s] for s in ORDER if s in c["service"]), len(ORDER)))


def ports_missing(c: dict) -> bool:
    return set(c["configured_ports"]) - set(c["published_ports"]) != set()


def lock():
    if not LOCK.exists():
        fd = os.open(LOCK, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    st = LOCK.lstat()
    if LOCK.is_symlink() or st.st_uid != os.getuid() or st.st_mode & 0o077 or st.st_nlink != 1:
        raise Blocked(f"UNSAFE_LOCK {LOCK}")
    handle = LOCK.open("a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise Blocked("DEPLOYMENT_LOCK_BUSY: another release/recovery is running") from exc
    return handle


def wait_ready(ids: list[str], deadline: float) -> list[dict]:
    while True:
        now = {c["id"]: c for c in (summary(x) for x in containers())}
        missing = [{"name": i, "state": "missing"} for i in ids if i not in now]
        pending = missing + [now[i] for i in ids if i in now and (now[i]["state"] != "running"
                             or now[i]["health"] not in ("healthy", "-") or ports_missing(now[i]))]
        if not pending or time.monotonic() > deadline:
            return pending
        time.sleep(5)


def apply() -> int:
    if os.getuid() != 1000:
        raise Blocked("RUN_AS_OPERATOR_UID_1000")
    holders = compat_holders()
    if [h for h in holders if h != "lo"]:
        raise Blocked(f"COMPAT_IP_HELD_BY_PHYSICAL_INTERFACE {holders}: the host is on the former network; do not alias")
    if physical_routes_covering():
        raise Blocked(f"PHYSICAL_ROUTE_COVERS_COMPAT_IP {physical_routes_covering()}: refusing to alias on the former laboratory LAN")
    handle = lock()
    ev = evidence_dir()
    before = diagnose(ev)
    targets = affected(before["containers"])
    if not targets:
        raise Blocked("NO_CONTAINER_PUBLISHES_ON_COMPAT_IP: nothing to recover with this procedure")
    arp_before = before["arp_ignore"]
    dump(ev, "arp_ignore_before.json", arp_before)
    print(f"== evidence: {ev}")
    if "lo" not in holders:
        run("sudo", IP, "addr", "add", f"{COMPAT_IP}/32", "dev", "lo", "label", LABEL)
        print(f"== added {COMPAT_IP}/32 on lo ({LABEL}); transient until reboot unless the boot unit is installed")
    for dev in PHYSICAL:
        if Path(f"/proc/sys/net/ipv4/conf/{dev}").exists():
            run("sudo", SYSCTL, "-q", "-w", f"net.ipv4.conf.{dev}.arp_ignore=1")
    acted = []
    for c in targets:
        if c["state"] in ("exited", "created"):
            print(f"== docker start {c['name']} (was {c['state']}: {c['error'][:80]})")
            run("docker", "start", c["id"], timeout=120)
            acted.append(c["id"])
            wait_ready([c["id"]], time.monotonic() + 90)
        elif c["state"] == "running" and ports_missing(c):
            print(f"== docker restart {c['name']} (running without published ports {sorted(set(c['configured_ports']) - set(c['published_ports']))})")
            run("docker", "restart", "-t", "30", c["id"], timeout=180)
            acted.append(c["id"])
            wait_ready([c["id"]], time.monotonic() + 90)
        else:
            print(f"== unchanged {c['name']} ({c['state']}, ports ok)")
    pending = wait_ready(acted, time.monotonic() + 240)
    after = diagnose(None)
    dump(ev, "after.json", after)
    by_id = {c["id"]: c for c in after["containers"]}
    drift = [c["name"] for c in before["containers"] if c["id"] not in by_id
             or by_id[c["id"]]["image"] != c["image"] or by_id[c["id"]]["mounts"] != c["mounts"]]
    ready = after["probes"]["telemetry_ready"]
    handle.close()
    if drift:
        print(f"HARD_BLOCKER_CONTAINER_IDENTITY_DRIFT {drift} (containers must never be recreated by this tool); evidence {ev}")
        return 2
    if pending or ready["http"] != 200:
        print(f"NEXOLAB_NETWORK_COMPAT_RECOVERY_PARTIAL pending={[p['name'] for p in pending]} telemetry_ready={ready}")
        print(f"Alias kept (harmless). Send this output and {ev}. Rollback: python3 -I -B <tool> rollback")
        return 1
    time.sleep(30)
    second = probes()["telemetry_ready"]
    dump(ev, "lag_30s_later.json", second)
    print(f"== ingestion lag now {ready['body']} -> 30 s later {second['body']} (backlog drains after the Edge bridge reconnects)")
    print(f"NEXOLAB_NETWORK_COMPAT_RECOVERY_GREEN containers_unchanged evidence={ev}")
    return 0


def rollback() -> int:
    holders = compat_holders()
    if "lo" in holders:
        run("sudo", IP, "addr", "del", f"{COMPAT_IP}/32", "dev", "lo")
        print(f"== removed {COMPAT_IP}/32 from lo")
    saved = sorted(EVIDENCE.glob("*/arp_ignore_before.json"))
    if saved:
        for dev, value in json.loads(saved[-1].read_text()).items():
            if value.strip().isdigit() and Path(f"/proc/sys/net/ipv4/conf/{dev}").exists():
                run("sudo", SYSCTL, "-q", "-w", f"net.ipv4.conf.{dev}.arp_ignore={value.strip()}")
        print(f"== arp_ignore restored from {saved[-1]}")
    print("NEXOLAB_NETWORK_COMPAT_ROLLBACK_DONE (containers left as they are; nothing was recreated)")
    return 0


def install_boot() -> int:
    tmp = Path.home() / ".nexolab-compat-address.service"
    tmp.write_text(UNIT_TEXT, encoding="utf-8")
    run("sudo", "install", "-o", "root", "-g", "root", "-m", "0644", str(tmp), str(UNIT))
    tmp.unlink()
    run("sudo", "systemctl", "daemon-reload")
    run("sudo", "systemctl", "enable", "nexolab-compat-address.service")
    run("sudo", "systemctl", "start", "nexolab-compat-address.service")
    print(run("systemctl", "is-enabled", "nexolab-compat-address.service", check=False), compat_holders())
    print("NEXOLAB_COMPAT_BOOT_UNIT_INSTALLED (interim; WP2 removes it)")
    return 0


def remove_boot() -> int:
    if UNIT.exists():
        run("sudo", "systemctl", "disable", "nexolab-compat-address.service")
        run("sudo", "rm", "-f", "--", str(UNIT))
        run("sudo", "systemctl", "daemon-reload")
    print("NEXOLAB_COMPAT_BOOT_UNIT_REMOVED (alias stays until reboot or `rollback`)")
    return 0


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "diagnose"
    try:
        if mode == "diagnose":
            diagnose()
            return 0
        return {"apply": apply, "rollback": rollback, "install-boot-compat": install_boot,
                "remove-boot-compat": remove_boot}[mode]()
    except KeyError:
        print(__doc__)
        return 64
    except Blocked as exc:
        print(f"RECOVERY_BLOCKED {exc}")
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv))
