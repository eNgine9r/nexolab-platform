#!/usr/bin/env python3
"""NEXOLAB P0 network-change recovery (v2): interim compatibility service address.

Owner-run as the operator account (uid 1000, docker group, sudo for `ip`,
`sysctl`, `journalctl` and copying evidence). Restores the existing LOCAL_LAN
runtime after the host moved to another network, WITHOUT changing any Compose
file, environment file, image, volume, credential or hardware configuration.

Cause (#1733): the installed runtime publishes the Telemetry API, central MQTT,
object storage and the LAN Dashboard on the former DHCP address 172.18.48.66,
and the Edge MQTT bridge, HTTPS gateway and dev guard use it as their private
origin. After the move Docker cannot bind it.

v2 changes after the unconfirmed v1 GREEN report:
- every run prints the tool SHA-256, boot ID and host (provenance);
- the alias lives on a dedicated dummy interface `nxcompat0`, not on `lo`
  (NetworkManager 1.52 tracks `lo` as a connection);
- `diagnose` adds Docker container events since boot, kernel/NM journal lines
  for the address, restart policies/network modes and a READ-ONLY PostgreSQL
  ingestion check (PK-ordered, statement timeout, read-only transaction);
- `apply` also handles `restarting` containers, then runs a stability window
  (alias still present, API ready, Edge broker actually delivering, fresh rows
  in PostgreSQL) and rolls the alias back automatically when the API never
  becomes ready;
- `--share-evidence DIR` copies the non-secret evidence to DIR for review.

    diagnose  (default, read-only)
    apply     add the alias (transient), start/rebind, verify, stability window
    verify    read-only: stability window + PostgreSQL ingestion
    rollback  remove the alias (dummy and legacy lo) and restore arp_ignore
    install-boot-compat / remove-boot-compat
              optional interim unit creating the alias before Docker at boot

Refuses on the former laboratory network itself and when another interface
holds the address. Never prunes, removes, recreates or writes to hardware.
"""

from __future__ import annotations

import fcntl
import hashlib
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
DUMMY = "nxcompat0"
LEGACY_LABEL = "lo:nxcompat"
PROJECTS = ("nexolab-central", "nexolab-edge")
ORDER = ("postgres", "minio", "object-storage", "versitygw", "mqtt", "telemetry-service", "dashboard")
PHYSICAL = ("eth0", "wlan0")
LOCK = Path("/tmp/nexolab-current-head-launch.lock")
EVIDENCE = Path.home() / "nexolab-recovery-evidence"
UNIT = Path("/etc/systemd/system/nexolab-compat-address.service")
IP = "/usr/sbin/ip"
SYSCTL = "/usr/sbin/sysctl"
STABILITY_SECONDS = int(os.environ.get("NEXOLAB_COMPAT_STABILITY_SECONDS", "120"))
UNIT_TEXT = f"""[Unit]
Description=NEXOLAB interim compatibility service address {COMPAT_IP}/32 on {DUMMY} (P0 #1733, until #1734 cutover)
DefaultDependencies=no
Before=network-pre.target docker.service
Wants=network-pre.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -ec '{IP} link show {DUMMY} >/dev/null 2>&1 || {IP} link add {DUMMY} type dummy; {IP} link set {DUMMY} up; {IP} -4 -o addr show dev {DUMMY} | grep -q " {COMPAT_IP}/32 " || {IP} addr add {COMPAT_IP}/32 dev {DUMMY}'
ExecStart=-{SYSCTL} -q -w net.ipv4.conf.eth0.arp_ignore=1
ExecStart=-{SYSCTL} -q -w net.ipv4.conf.wlan0.arp_ignore=1

[Install]
WantedBy=multi-user.target
"""
PG_READONLY_SQL = """
SET statement_timeout = '30s';
SELECT json_build_object(
  'now', now(),
  'latest', (SELECT json_agg(r) FROM (SELECT id, node_id, captured_at, received_at FROM telemetry_samples ORDER BY id DESC LIMIT 3) r),
  'recent_by_received_10min', (SELECT json_agg(b ORDER BY b.bucket) FROM (
      SELECT date_trunc('hour', received_at) + floor(date_part('minute', received_at) / 10) * interval '10 minutes' AS bucket,
             count(*) AS row_count, min(captured_at) AS min_captured, max(captured_at) AS max_captured
      FROM (SELECT received_at, captured_at FROM telemetry_samples ORDER BY id DESC LIMIT 200000) s
      GROUP BY 1) b),
  'recent_by_captured_10min', (SELECT json_agg(b ORDER BY b.bucket) FROM (
      SELECT date_trunc('hour', captured_at) + floor(date_part('minute', captured_at) / 10) * interval '10 minutes' AS bucket,
             count(*) AS row_count
      FROM (SELECT captured_at FROM telemetry_samples ORDER BY id DESC LIMIT 200000) s
      GROUP BY 1) b)
);
"""


class Blocked(Exception):
    pass


def run(*args: str, timeout: int = 60, check: bool = True, env: dict | None = None) -> str:
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False, env=env)
    if check and result.returncode:
        raise Blocked(f"COMMAND_FAILED {' '.join(args[:4])}: {result.stderr.strip()[-400:]}")
    return result.stdout.strip()


def provenance() -> dict:
    tool = Path(__file__).resolve()
    data = {
        "tool": str(tool),
        "tool_sha256": hashlib.sha256(tool.read_bytes()).hexdigest(),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "host": os.uname().nodename,
        "uid": os.getuid(),
        "at": datetime.now(UTC).isoformat(),
    }
    print(f"== provenance: sha256={data['tool_sha256']} boot={data['boot_id']} host={data['host']} at={data['at']}")
    return data


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
        if dev.startswith(("br-", "docker", "veth", "lo", "tailscale", DUMMY)):
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
        "started_at": c["State"].get("StartedAt"),
        "finished_at": c["State"].get("FinishedAt"),
        "exit_code": c["State"].get("ExitCode"),
        "health": (c["State"].get("Health") or {}).get("Status", "-"),
        "error": c["State"].get("Error", ""),
        "restarts": c.get("RestartCount", 0),
        "restart_policy": (c["HostConfig"].get("RestartPolicy") or {}).get("Name"),
        "network_mode": c["HostConfig"].get("NetworkMode"),
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
        brief: object = body[:300]
        try:
            data = json.loads(body)
            keep = ("status", "ingestion_lag_seconds", "database", "mqtt", "mqtt_connected", "queue_size",
                    "last_publish_at", "source_commit", "build_id")
            brief = {k: data[k] for k in keep if k in data}
        except ValueError:
            pass
        result[name] = {"http": status, "body": brief}
    return result


def _service(items: list[dict], project: str, service: str) -> dict | None:
    return next((c for c in items if c["project"] == project and c["service"] == service and c["state"] == "running"), None)


def edge_broker(items: list[dict]) -> dict:
    """Read-only Edge MQTT bridge state: $SYS counters and recent bridge log lines."""
    broker = _service(items, "nexolab-edge", "mqtt")
    if not broker:
        return {"edge_mqtt": "not running or not found"}
    env = json.loads(run("docker", "inspect", "--format", "{{json .Config.Env}}", broker["id"]))
    target = {k: v for k, v in (e.split("=", 1) for e in env if "=" in e) if k in ("CENTRAL_MQTT_HOST", "CENTRAL_MQTT_PORT")}
    raw = run("docker", "exec", broker["id"], "mosquitto_sub", "-h", "127.0.0.1", "-p", "1883", "-v", "-W", "15", "-C", "6",
              "-t", "$SYS/broker/store/messages/count", "-t", "$SYS/broker/publish/messages/dropped",
              "-t", "$SYS/broker/publish/messages/sent", "-t", "$SYS/broker/publish/messages/received",
              "-t", "$SYS/broker/clients/connected", "-t", "$SYS/broker/clients/disconnected", timeout=30, check=False)
    counters = {}
    for line in raw.splitlines():
        topic, _, value = line.partition(" ")
        counters[topic.rsplit("/", 2)[-2] + "/" + topic.rsplit("/", 1)[-1] if topic.count("/") > 2 else topic] = value
    logs = subprocess.run(["docker", "logs", "--since", "12h", broker["id"]], text=True, capture_output=True, timeout=60, check=False)
    lines = [ln for ln in (logs.stdout + logs.stderr).splitlines()
             if any(k in ln for k in ("edge-node-to-central", "onnecting bridge", "Socket error", "max_queued", "Outgoing messages"))]
    return {"container": broker["name"], "bridge_target": target, "sys": counters, "bridge_log_tail": lines[-10:]}


def postgres_ingestion(items: list[dict]) -> dict:
    """READ-ONLY: latest rows by primary key and 10-minute buckets of the last 200k rows."""
    pg = _service(items, "nexolab-central", "postgres")
    if not pg:
        return {"postgres": "not running or not found"}
    cmd = ['sh', '-c', 'PGOPTIONS="-c default_transaction_read_only=on" psql -X -q -At -v ON_ERROR_STOP=1 '
           '-U "$POSTGRES_USER" -d "$POSTGRES_DB"']
    result = subprocess.run(["docker", "exec", "-i", pg["id"], *cmd], input=PG_READONLY_SQL, text=True,
                            capture_output=True, timeout=90, check=False)
    if result.returncode:
        return {"postgres": "query failed", "stderr": result.stderr.strip()[-300:]}
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"postgres": "unparsed", "stdout": result.stdout[-300:]}


def history() -> dict:
    """What happened since boot: container events and kernel/NetworkManager lines for the address."""
    boot_epoch = int(time.time() - float(Path("/proc/uptime").read_text().split()[0]))
    boot = datetime.fromtimestamp(boot_epoch, UTC).isoformat()
    events = run("timeout", "20", "docker", "events", "--since", str(boot_epoch), "--until", str(int(time.time())),
                 "--filter", "type=container", "--format", "{{.Time}} {{.Action}} {{.Actor.Attributes.name}}", check=False, timeout=30)
    keep = [e for e in events.splitlines() if "nexolab" in e and any(a in e for a in (" start ", " die ", " restart ", " stop ", " kill ", " create ", " destroy "))]
    journal = run("sudo", "-n", "journalctl", "-b", "--no-pager", "-o", "short-iso", "--grep", f"{COMPAT_IP}|nxcompat|{DUMMY}",
                  check=False, timeout=60)
    return {"boot": boot, "container_events": keep[-80:], "journal_compat_lines": journal.splitlines()[-40:]}


def evidence_dir() -> Path:
    path = EVIDENCE / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path.mkdir(parents=True, mode=0o700)
    return path


def dump(path: Path, name: str, data: object) -> None:
    (path / name).write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def diagnose(save: Path | None = None, with_history: bool = True) -> dict:
    items = [summary(c) for c in containers()]
    report = {
        "at": datetime.now(UTC).isoformat(),
        "addresses": addresses(),
        "compat_ip_holders": compat_holders(),
        "physical_routes_covering_compat_ip": physical_routes_covering(),
        "default_route": run(IP, "-4", "route", "show", "default", check=False),
        "arp_ignore": {d: run(SYSCTL, "-n", f"net.ipv4.conf.{d}.arp_ignore", check=False) for d in PHYSICAL},
        "networkmanager_lo": run("nmcli", "-t", "-f", "GENERAL.STATE,GENERAL.CONNECTION", "dev", "show", "lo", check=False),
        "containers": items,
        "edge_broker": edge_broker(items),
        "postgres": postgres_ingestion(items),
        "probes": probes(),
        "boot_compat_unit": UNIT.exists(),
    }
    if with_history:
        report["history"] = history()
    if save:
        dump(save, "diagnose.json" if with_history else f"state-{int(time.time())}.json", report)
    print("== addresses:", report["addresses"])
    print("== compat ip holders:", report["compat_ip_holders"] or "none", "| physical route covering:",
          report["physical_routes_covering_compat_ip"] or "none", "| NM lo:", report["networkmanager_lo"].replace("\n", " "))
    print("== containers (name state health restarts policy netmode | configured -> published | networks | error)")
    for c in items:
        print(f"  {c['name']:42} {c['state']:10} {c['health']:9} r={c['restarts']} {c['restart_policy']} {c['network_mode']} | "
              f"{','.join(c['configured_ports']) or '-'} -> {','.join(c['published_ports']) or '-'} | "
              f"{','.join(c['networks']) or 'NO NETWORKS'} | {c['error'][:90]}")
    print("== edge broker:", json.dumps(report["edge_broker"], indent=1))
    pg = report["postgres"]
    print("== postgres latest rows:", json.dumps(pg.get("latest", pg), default=str))
    for bucket in (pg.get("recent_by_received_10min") or [])[-12:]:
        print(f"   received {bucket['bucket']}: rows={bucket['row_count']} captured {bucket['min_captured']} .. {bucket['max_captured']}")
    print("== probes:", json.dumps(report["probes"], indent=1))
    if with_history:
        print("== container events since boot:")
        for line in report["history"]["container_events"][-30:]:
            print("  ", line)
        print("== journal lines for the compatibility address:", *(report["history"]["journal_compat_lines"] or ["none"]), sep="\n   ")
    return report


def affected(items: list[dict]) -> list[dict]:
    hit = [c for c in items if COMPAT_IP in c["bound_ips"]
           or (c["project"] in PROJECTS and c["state"] in ("running", "restarting") and ports_missing(c))]
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


def add_alias() -> None:
    if subprocess.run([IP, "link", "show", DUMMY], capture_output=True, check=False).returncode:
        run("sudo", IP, "link", "add", DUMMY, "type", "dummy")
    run("sudo", IP, "link", "set", DUMMY, "up")
    if DUMMY not in compat_holders():
        run("sudo", IP, "addr", "add", f"{COMPAT_IP}/32", "dev", DUMMY)
    print(f"== {COMPAT_IP}/32 on {DUMMY} (transient until reboot unless the boot unit is installed)")


def remove_alias() -> None:
    holders = compat_holders()
    if "lo" in holders:
        run("sudo", IP, "addr", "del", f"{COMPAT_IP}/32", "dev", "lo")
    if subprocess.run([IP, "link", "show", DUMMY], capture_output=True, check=False).returncode == 0:
        run("sudo", IP, "link", "del", DUMMY)


def restore_arp(ev_root: Path = EVIDENCE) -> None:
    saved = sorted(ev_root.glob("*/arp_ignore_before.json"))
    if saved:
        for dev, value in json.loads(saved[-1].read_text()).items():
            if value.strip().isdigit() and Path(f"/proc/sys/net/ipv4/conf/{dev}").exists():
                run("sudo", SYSCTL, "-q", "-w", f"net.ipv4.conf.{dev}.arp_ignore={value.strip()}")


def _sent(items: list[dict]) -> int | None:
    value = edge_broker(items).get("sys", {}).get("messages/sent")
    return int(value) if value and value.isdigit() else None


def stability(ev: Path | None) -> tuple[bool, dict]:
    """Alias present, API ready and the Edge broker actually delivering for STABILITY_SECONDS."""
    items = [summary(c) for c in containers()]
    sent0 = _sent(items)
    pg0 = postgres_ingestion(items)
    samples = []
    deadline = time.monotonic() + STABILITY_SECONDS
    ok = True
    while time.monotonic() < deadline:
        holders = compat_holders()
        status, _ = http(f"http://{COMPAT_IP}:8082/health/ready")
        samples.append({"t": datetime.now(UTC).isoformat(), "holders": holders, "ready_http": status})
        if DUMMY not in holders and "lo" not in holders:
            print("ALIAS_REMOVED_BY_HOST during the stability window: see journal lines in diagnose")
            ok = False
            break
        if status != 200:
            ok = False
        time.sleep(15)
    items = [summary(c) for c in containers()]
    sent1 = _sent(items)
    pg1 = postgres_ingestion(items)
    latest0 = (pg0.get("latest") or [{}])[0].get("id") if isinstance(pg0.get("latest"), list) else None
    latest1 = (pg1.get("latest") or [{}])[0].get("id") if isinstance(pg1.get("latest"), list) else None
    delivering = sent0 is not None and sent1 is not None and sent1 > sent0
    ingesting = latest0 is not None and latest1 is not None and latest1 > latest0
    result = {"samples": samples, "edge_sent_before": sent0, "edge_sent_after": sent1, "edge_delivering": delivering,
              "pg_latest_id_before": latest0, "pg_latest_id_after": latest1, "pg_ingesting": ingesting,
              "pg_latest": pg1.get("latest")}
    if ev:
        dump(ev, "stability.json", result)
    print(f"== stability: alias kept={ok} edge sent {sent0}->{sent1} delivering={delivering} "
          f"postgres max id {latest0}->{latest1} ingesting={ingesting}")
    return ok and delivering and ingesting, result


def share(ev: Path, target: str | None) -> None:
    if not target:
        return
    run("sudo", "install", "-d", "-o", "nexolab-dev", "-g", "nexolab-dev", "-m", "0750", target)
    for item in sorted(ev.glob("*.json")):
        run("sudo", "install", "-o", "nexolab-dev", "-g", "nexolab-dev", "-m", "0640", str(item), f"{target}/{ev.name}-{item.name}")
    print(f"== evidence shared to {target}")


def apply(share_to: str | None = None) -> int:
    if os.getuid() != 1000:
        raise Blocked("RUN_AS_OPERATOR_UID_1000")
    holders = compat_holders()
    if [h for h in holders if h not in ("lo", DUMMY)]:
        raise Blocked(f"COMPAT_IP_HELD_BY_PHYSICAL_INTERFACE {holders}: the host is on the former network; do not alias")
    if physical_routes_covering():
        raise Blocked(f"PHYSICAL_ROUTE_COVERS_COMPAT_IP {physical_routes_covering()}: refusing to alias on the former laboratory LAN")
    handle = lock()
    ev = evidence_dir()
    dump(ev, "provenance.json", provenance())
    before = diagnose(ev)
    targets = affected(before["containers"])
    if not targets:
        share(ev, share_to)
        raise Blocked("NO_CONTAINER_PUBLISHES_ON_COMPAT_IP: nothing to recover with this procedure")
    dump(ev, "arp_ignore_before.json", before["arp_ignore"])
    print(f"== evidence: {ev}")
    if "lo" in holders:
        run("sudo", IP, "addr", "del", f"{COMPAT_IP}/32", "dev", "lo")
        print("== removed legacy v1 alias from lo")
    add_alias()
    for dev in PHYSICAL:
        if Path(f"/proc/sys/net/ipv4/conf/{dev}").exists():
            run("sudo", SYSCTL, "-q", "-w", f"net.ipv4.conf.{dev}.arp_ignore=1")
    acted = []
    for c in targets:
        if c["state"] in ("exited", "created"):
            print(f"== docker start {c['name']} (was {c['state']}: {c['error'][:80]})")
            run("docker", "start", c["id"], timeout=120)
        elif c["state"] in ("running", "restarting") and (ports_missing(c) or c["state"] == "restarting"):
            print(f"== docker restart {c['name']} ({c['state']}, missing ports {sorted(set(c['configured_ports']) - set(c['published_ports']))})")
            run("docker", "restart", "-t", "30", c["id"], timeout=180)
        else:
            print(f"== unchanged {c['name']} ({c['state']}, ports ok)")
            continue
        acted.append(c["id"])
        wait_ready([c["id"]], time.monotonic() + 90)
    pending = wait_ready(acted, time.monotonic() + 240)
    after = diagnose(None, with_history=False)
    dump(ev, "after.json", after)
    by_id = {c["id"]: c for c in after["containers"]}
    drift = [c["name"] for c in before["containers"] if c["id"] not in by_id
             or by_id[c["id"]]["image"] != c["image"] or by_id[c["id"]]["mounts"] != c["mounts"]]
    ready = after["probes"]["telemetry_ready"]
    if drift:
        handle.close()
        share(ev, share_to)
        print(f"HARD_BLOCKER_CONTAINER_IDENTITY_DRIFT {drift} (containers must never be recreated by this tool); evidence {ev}")
        return 2
    if ready["http"] != 200:
        print(f"== Telemetry API not ready ({ready}); automatic rollback of the address")
        remove_alias()
        restore_arp()
        handle.close()
        share(ev, share_to)
        print(f"NEXOLAB_NETWORK_COMPAT_RECOVERY_ROLLED_BACK pending={[p['name'] for p in pending]} evidence={ev}")
        return 1
    stable, _ = stability(ev)
    handle.close()
    share(ev, share_to)
    if not stable:
        print(f"NEXOLAB_NETWORK_COMPAT_RECOVERY_UNSTABLE (API answered but alias/delivery/ingestion not proven); alias kept; evidence {ev}")
        return 1
    print(f"NEXOLAB_NETWORK_COMPAT_RECOVERY_GREEN_STABLE containers_unchanged edge_delivering postgres_ingesting evidence={ev}")
    return 0


def verify(share_to: str | None = None) -> int:
    ev = evidence_dir()
    dump(ev, "provenance.json", provenance())
    diagnose(ev)
    stable, _ = stability(ev)
    share(ev, share_to)
    print("NEXOLAB_NETWORK_VERIFY_GREEN" if stable else "NEXOLAB_NETWORK_VERIFY_NOT_GREEN")
    return 0 if stable else 1


def rollback() -> int:
    remove_alias()
    restore_arp()
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
    print("NEXOLAB_COMPAT_BOOT_UNIT_INSTALLED (interim; WP2c removes it)")
    return 0


def remove_boot() -> int:
    if UNIT.exists():
        run("sudo", "systemctl", "disable", "nexolab-compat-address.service")
        run("sudo", "rm", "-f", "--", str(UNIT))
        run("sudo", "systemctl", "daemon-reload")
    print("NEXOLAB_COMPAT_BOOT_UNIT_REMOVED (alias stays until reboot or `rollback`)")
    return 0


def main(argv: list[str]) -> int:
    args = list(argv[1:])
    share_to = None
    if "--share-evidence" in args:
        index = args.index("--share-evidence")
        share_to = args[index + 1]
        del args[index:index + 2]
    mode = args[0] if args else "diagnose"
    try:
        if mode == "diagnose":
            ev = evidence_dir()
            dump(ev, "provenance.json", provenance())
            diagnose(ev)
            share(ev, share_to)
            return 0
        if mode == "apply":
            return apply(share_to)
        if mode == "verify":
            return verify(share_to)
        provenance()
        return {"rollback": rollback, "install-boot-compat": install_boot, "remove-boot-compat": remove_boot}[mode]()
    except KeyError:
        print(__doc__)
        return 64
    except Blocked as exc:
        print(f"RECOVERY_BLOCKED {exc}")
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv))
