#!/usr/bin/env python3
"""NEXOLAB #1786 (#1428 DR-A): render the site DR backup config from the live containers. Read-only.

Run by the owner on the Raspberry Pi as root (it reads Docker volume sizes):

  sudo python3 -I -B scripts/nexolab-dr-site-config.py \
      --template infrastructure/systemd/nexolab-dr-backup.example.json \
      --install-dir /usr/local/lib/nexolab-dr --output /etc/nexolab/dr-backup.json

Every ``CONFIRM-`` value of the template is resolved from ``docker inspect`` of the running containers:
store paths come from the host source of the exact mount destination, the PostgreSQL user and database from
the container's ``POSTGRES_USER``/``POSTGRES_DB``, the local-auth key paths from the telemetry container's
key mounts. Nothing is guessed: an unresolved value, a missing path or a store larger than its cap stops the
run (exit 78) without writing. The output is created exclusively with mode 0600. The only Docker verb used is
``inspect``; no data is read except file sizes, and no secret value is printed or written.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

EXIT_BLOCKED = 78
POSTGRES = "nexolab-central-postgres-1"
TELEMETRY = "nexolab-central-telemetry-service-1"
# store id -> (container, mount destination, file inside the mount or None for the whole directory)
DIRECTORY_STORES = {
    "object-storage": ("nexolab-central-minio-1", "/data", None),
    "mqtt-dynamic-security": ("nexolab-central-mqtt-1", "/mosquitto/data", None),
    "edge-mqtt-persistence": ("nexolab-edge-mqtt-1", "/mosquitto/data", None),
    "edge-sqlite-outbox": ("nexolab-edge-device-agent-1", "/var/lib/nexolab", "DATABASE_PATH:/var/lib/nexolab/edge.db"),
    "central-ingestion-spool": (TELEMETRY, "/app/data/telemetry-ingestion",
                                "INGESTION_SPOOL_PATH:/app/data/telemetry-ingestion/spool.db"),
}
KEY_MOUNTS = {
    "local-auth-private-key": re.compile(r"local[_-]auth[_-]private[_-]key"),
    "local-auth-public-key": re.compile(r"local[_-]auth[_-]public[_-]key"),
}
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


class Blocked(Exception):
    pass


def need(condition: object, reason: str) -> None:
    if not condition:
        raise Blocked(reason)


def docker_inspect(names: list[str]) -> dict[str, dict]:
    result = subprocess.run(["docker", "inspect", "--type", "container", "--", *names], capture_output=True, text=True,
                            timeout=60, check=False)
    need(result.returncode == 0, "DOCKER_INSPECT_FAILED " + result.stderr.strip()[-300:])
    return {item["Name"].lstrip("/"): item for item in json.loads(result.stdout)}


def env_of(container: dict) -> dict[str, str]:
    return dict(item.split("=", 1) for item in (container.get("Config") or {}).get("Env") or [] if "=" in item)


def mount_source(container: dict, destination: str) -> str:
    matches = [m for m in container.get("Mounts") or [] if m.get("Destination") == destination]
    need(len(matches) == 1, f"MOUNT_NOT_FOUND {container['Name']} {destination}")
    need(matches[0].get("RW") is True or matches[0].get("Type") == "volume",
         f"UNEXPECTED_MOUNT {container['Name']} {destination}")
    return matches[0]["Source"]


def in_container_file(container: dict, spec: str) -> str:
    key, _, default = spec.partition(":")
    value = env_of(container).get(key) or default
    if not value.startswith("/"):  # relative paths resolve against the working directory
        value = str(Path((container.get("Config") or {}).get("WorkingDir") or "/") / value)
    return value


def tree_bytes(path: Path) -> int:
    st = path.lstat()
    if stat.S_ISREG(st.st_mode):
        return st.st_size
    total = 0
    for current, dirs, files in os.walk(path, followlinks=False):
        for name in files:
            try:
                fst = (Path(current) / name).lstat()
            except OSError:
                continue
            if stat.S_ISREG(fst.st_mode):
                total += fst.st_size
    return total


def render(template: dict, containers: dict[str, dict], install_dir: Path, size_of=tree_bytes) -> tuple[dict, list[dict]]:
    config = copy.deepcopy(template)
    config.pop("_comment", None)
    config["source_commit_file"] = str(install_dir / "SOURCE_COMMIT")
    report = []
    for store in config["stores"]:
        sid = store["id"]
        if sid in DIRECTORY_STORES:
            name, destination, inner = DIRECTORY_STORES[sid]
            need(name in containers, f"CONTAINER_MISSING {name}")
            container = containers[name]
            source = mount_source(container, destination)
            if inner:
                file_in_container = in_container_file(container, inner)
                need(file_in_container.startswith(destination + "/"),
                     f"FILE_OUTSIDE_MOUNT {sid} {file_in_container} not under {destination}")
                store["path"] = source.rstrip("/") + file_in_container[len(destination):]
            else:
                store["path"] = source
        elif sid == "postgresql":
            need(POSTGRES in containers, f"CONTAINER_MISSING {POSTGRES}")
            env = env_of(containers[POSTGRES])
            user, db = env.get("POSTGRES_USER", "postgres"), env.get("POSTGRES_DB") or env.get("POSTGRES_USER", "postgres")
            need(IDENT.fullmatch(user) and IDENT.fullmatch(db), "POSTGRES_IDENT_UNSAFE")
            argv = store["argv"]
            argv[2] = POSTGRES
            argv[argv.index("-U") + 1] = user
            argv[argv.index("-d") + 1] = db
        elif sid in KEY_MOUNTS:
            need(TELEMETRY in containers, f"CONTAINER_MISSING {TELEMETRY}")
            dests = [m["Destination"] for m in containers[TELEMETRY].get("Mounts") or []
                     if KEY_MOUNTS[sid].search(m.get("Destination") or "")]
            need(len(dests) == 1, f"KEY_MOUNT_NOT_UNIQUE {sid} {dests}")
            store["argv"] = ["docker", "exec", TELEMETRY, "cat", dests[0]]
        else:
            raise Blocked("UNKNOWN_STORE " + sid)
        text = json.dumps(store)
        need("CONFIRM-" not in text, f"UNRESOLVED_VALUE {sid}")
        entry = {"id": sid, "max_bytes": store["max_bytes"]}
        if "path" in store:
            path = Path(store["path"])
            need(path.exists() and not path.is_symlink(), f"PATH_MISSING {sid} {path}")
            entry.update(path=str(path), bytes=size_of(path))
            need(entry["bytes"] <= store["max_bytes"], f"STORE_OVER_CAP {sid} {entry['bytes']} > {store['max_bytes']}")
        report.append(entry)
    need("CONFIRM-" not in json.dumps(config), "UNRESOLVED_VALUE")
    return config, report


def write_exclusive(path: Path, data: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--install-dir", type=Path, default=Path("/usr/local/lib/nexolab-dr"))
    parser.add_argument("--output", type=Path, help="write the config here (0600, must not exist); omit to only report")
    parser.add_argument("--inspect-json", type=Path, help="test/offline: docker inspect output instead of the daemon")
    args = parser.parse_args(argv)
    try:
        template = json.loads(args.template.read_text(encoding="utf-8"))
        names = sorted({c for c, _, _ in DIRECTORY_STORES.values()} | {POSTGRES, TELEMETRY})
        if args.inspect_json:
            containers = {i["Name"].lstrip("/"): i for i in json.loads(args.inspect_json.read_text(encoding="utf-8"))}
        else:
            need(os.geteuid() == 0, "RUN_AS_ROOT (volume sizes are root-only; nothing is modified)")
            containers = docker_inspect(names)
        config, report = render(template, containers, args.install_dir)
        for entry in report:
            size = f" {entry['bytes']}/{entry['max_bytes']} bytes" if "bytes" in entry else ""
            print(f"STORE_OK {entry['id']}{size} {entry.get('path', '')}".rstrip(), flush=True)
        if args.output:
            write_exclusive(args.output, json.dumps(config, indent=2) + "\n")
            print(f"DR_SITE_CONFIG_WRITTEN {args.output} (0600)", flush=True)
        else:
            print("DR_SITE_CONFIG_RESOLVED (report only; nothing written)", flush=True)
        return 0
    except Blocked as error:
        print("BLOCKED " + str(error)[:500], file=sys.stderr, flush=True)
        return EXIT_BLOCKED
    except FileExistsError:
        print(f"BLOCKED OUTPUT_EXISTS {args.output} (never overwritten)", file=sys.stderr, flush=True)
        return EXIT_BLOCKED


if __name__ == "__main__":
    sys.exit(main())
