#!/usr/bin/env python3
"""NEXOLAB #1794: development-session memory guard (read-only).

Reports the memory headroom of the caller's systemd slice and the tmpfs bytes the caller owns, and refuses heavy
work when that would push the session into ``memory.high`` throttling (the recurring freeze: tasks blocked in
``__mem_cgroup_handle_over_high``). tmpfs pages (``/tmp``, the Claude scratchpad, ``/dev/shm``) are charged to the
cgroup as shmem and, once swapped, consume the slice's ``MemorySwapMax``; a forgotten virtualenv there is enough.

  python3 -I -B scripts/dev-resource-guard.py report            # JSON
  python3 -I -B scripts/dev-resource-guard.py check --need-mib 300

``check`` exits 0 when the work fits, 75 (EX_TEMPFAIL) when it does not, and prints the reasons. Nothing is
changed; the tmpfs scan is bounded and never follows links.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import time
from pathlib import Path

MIB = 1024 * 1024
EX_TEMPFAIL = 75
TMPFS_DIRS = ("/tmp", "/dev/shm", "/var/tmp")
SCAN_LIMIT = 200_000


def read_value(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="ascii").strip()
    except OSError:
        return None
    return None if text == "max" else int(text)


def own_cgroup(proc_cgroup: Path = Path("/proc/self/cgroup")) -> str:
    for line in proc_cgroup.read_text(encoding="utf-8").splitlines():
        if line.startswith("0::"):
            return line[3:]
    raise SystemExit("cgroup v2 required")


def limiting_cgroup(root: Path, relative: str) -> Path:
    """The ancestor-or-self with the least headroom below its memory.high (or memory.max): every level throttles,
    so the tightest one decides (the session service and its parent user slice both carry limits)."""
    path, best, best_room = root / relative.lstrip("/"), None, None
    while True:
        limit = read_value(path / "memory.high")
        limit = limit if limit is not None else read_value(path / "memory.max")
        if limit is not None:
            room = limit - (read_value(path / "memory.current") or 0)
            if best_room is None or room < best_room:
                best, best_room = path, room
        if path == root or path.parent == path:
            return best or root / relative.lstrip("/")
        path = path.parent


def events(path: Path) -> dict[str, int]:
    try:
        return {k: int(v) for k, v in (line.split() for line in (path / "memory.events").read_text().splitlines())}
    except (OSError, ValueError):
        return {}


def tmpfs_bytes(uid: int, dirs: tuple[str, ...] = TMPFS_DIRS) -> tuple[int, list[tuple[int, str]], bool]:
    total, largest, scanned, complete = 0, [], 0, True
    for top in dirs:
        if not os.path.isdir(top):
            continue
        for current, subdirs, files in os.walk(top, followlinks=False, onerror=lambda _e: None):
            for name in files:
                scanned += 1
                if scanned > SCAN_LIMIT:
                    return total, sorted(largest, reverse=True)[:5], False
                try:
                    st = os.lstat(os.path.join(current, name))
                except OSError:
                    continue
                if st.st_uid == uid and stat.S_ISREG(st.st_mode):
                    used = st.st_blocks * 512
                    total += used
                    largest.append((used, os.path.join(current, name)))
                    largest = sorted(largest, reverse=True)[:5]
    return total, largest, complete


def report(root: Path = Path("/sys/fs/cgroup"), proc_cgroup: Path = Path("/proc/self/cgroup"),
           dirs: tuple[str, ...] = TMPFS_DIRS) -> dict:
    cg = limiting_cgroup(root, own_cgroup(proc_cgroup))
    high, maximum = read_value(cg / "memory.high"), read_value(cg / "memory.max")
    current = read_value(cg / "memory.current") or 0
    swap_max, swap_current = read_value(cg / "memory.swap.max"), read_value(cg / "memory.swap.current") or 0
    tmp_total, tmp_largest, tmp_complete = tmpfs_bytes(os.getuid(), dirs)
    limit = high if high is not None else maximum
    return {
        "cgroup": "/" + str(cg.relative_to(root)) if cg != root else "/",
        "memory_current_mib": current // MIB,
        "memory_high_mib": None if high is None else high // MIB,
        "memory_max_mib": None if maximum is None else maximum // MIB,
        "headroom_mib": None if limit is None else max(0, limit - current) // MIB,
        "swap_current_mib": swap_current // MIB,
        "swap_max_mib": None if swap_max is None else swap_max // MIB,
        "swap_free_mib": None if swap_max is None else max(0, swap_max - swap_current) // MIB,
        "events": events(cg),
        "tmpfs_owned_mib": tmp_total // MIB,
        "tmpfs_largest": [{"mib": round(b / MIB, 1), "path": p} for b, p in tmp_largest],
        "tmpfs_scan_complete": tmp_complete,
        "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def verdict(data: dict, need_mib: int, min_swap_free_mib: int, max_tmpfs_mib: int) -> list[str]:
    reasons = []
    if data["headroom_mib"] is not None and data["headroom_mib"] < need_mib:
        reasons.append(f"HEADROOM {data['headroom_mib']} MiB < needed {need_mib} MiB below memory.high")
    if data["swap_free_mib"] is not None and data["swap_free_mib"] < min_swap_free_mib:
        reasons.append(f"SWAP_QUOTA {data['swap_free_mib']} MiB free < {min_swap_free_mib} MiB")
    if data["tmpfs_owned_mib"] > max_tmpfs_mib:
        reasons.append(f"TMPFS_OWNED {data['tmpfs_owned_mib']} MiB > {max_tmpfs_mib} MiB (RAM-backed; move to ~/.cache)")
    return reasons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("mode", choices=("report", "check"))
    parser.add_argument("--need-mib", type=int, default=256, help="memory the next task needs below memory.high")
    parser.add_argument("--min-swap-free-mib", type=int, default=128)
    parser.add_argument("--max-tmpfs-mib", type=int, default=150)
    parser.add_argument("--cgroup-root", type=Path, default=Path("/sys/fs/cgroup"))
    parser.add_argument("--proc-cgroup", type=Path, default=Path("/proc/self/cgroup"))
    parser.add_argument("--tmpfs-dir", action="append", help="test/override: directories to scan (repeatable)")
    args = parser.parse_args(argv)
    data = report(args.cgroup_root, args.proc_cgroup, tuple(args.tmpfs_dir) if args.tmpfs_dir else TMPFS_DIRS)
    if args.mode == "report":
        print(json.dumps(data, indent=2))
        return 0
    reasons = verdict(data, args.need_mib, args.min_swap_free_mib, args.max_tmpfs_mib)
    summary = (f"headroom={data['headroom_mib']}MiB swap_free={data['swap_free_mib']}MiB "
               f"tmpfs_owned={data['tmpfs_owned_mib']}MiB high_events={data['events'].get('high', 0)}")
    if reasons:
        print("RESOURCE_GUARD_REFUSED " + summary, flush=True)
        for reason in reasons:
            print("  " + reason, flush=True)
        for item in data["tmpfs_largest"]:
            print(f"  largest tmpfs file: {item['mib']} MiB {item['path']}", flush=True)
        return EX_TEMPFAIL
    print("RESOURCE_GUARD_OK " + summary, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
