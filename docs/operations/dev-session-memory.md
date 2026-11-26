# Development session memory stability (#1794)

The isolated development session (`nexolab-dev-session.service` in `user-1001.slice`) froze repeatedly. Claude and its Python child were blocked in `__mem_cgroup_handle_over_high`: the cgroup was at `memory.high` and every allocation was throttled into reclaim. Production was not affected (separate cgroups).

## Evidence (2026-11-26)

| Measure                                   | Before                       | After moving one directory off tmpfs |
| ----------------------------------------- | ---------------------------- | ------------------------------------ |
| `user-1001.slice` `memory.current`        | 905 MB                       | 748 MB                               |
| `memory.swap.current` / `memory.swap.max` | **536 MB / 512 MiB (full)**  | 87 MB / 512 MiB                      |
| `/tmp` (tmpfs) used                       | 517 MB                       | 69 MB                                |
| `memory.events` `high`                    | 2,276,852 (`max` 0, `oom` 0) | (counter is cumulative)              |
| `claude` RSS / own swap                   | ≈ 620 MB / 24 MB             | unchanged                            |

**Root cause:** a 448 MB Python virtualenv in the session scratchpad (`/tmp/claude-1001/…/scratchpad/tsvenv`).

- `/tmp` is **tmpfs**, and with `PrivateTmp=yes` it is still RAM-backed.
- tmpfs pages are charged to the creating cgroup as `shmem`. Under pressure they are swapped, and that swap counts against the slice's `MemorySwapMax=512M`.
- The forgotten files therefore filled the whole swap quota. Claude's own anonymous memory then had no swap headroom, so every step near `memory.high` throttled the session.
- The process table did not show it: almost none of that swap belonged to a process.

**Limits found:** the units configure `MemoryHigh=768M`, `MemoryMax=1280M` and `MemorySwapMax=512M` on both the slice and the service. The cgroup files showed a temporary `memory.high` of 1152M, written at runtime; it is lost on reboot or `daemon-reload`.

## Rules for the agent (in force)

1. **Nothing large on tmpfs.** Virtualenvs, build outputs, downloaded artifacts and archives go to `~/.local/venvs` or `~/.cache/…` (SSD). The scratchpad holds only small evidence files and scripts.
2. **Stream, never slurp.** Read archives with `zipfile.ZipFile.open()` and `tarfile` stream mode (`r|gz`), hash in chunks, and filter logs with `grep`/`tail` in the pipe. Never `read()` a whole artifact into memory.
3. **One heavy job at a time, at most one background agent.** Heavy builds and full test suites run in GitHub Actions; locally only targeted tests run.
4. **Check before heavy work:**
   ```bash
   python3 -I -B scripts/dev-resource-guard.py check --need-mib 300
   ```
   Exit 75 means: do not start. The output names the reason (headroom below `memory.high`, swap quota, or tmpfs bytes owned) and the largest tmpfs files.

## Owner change proposed: persistent and consistent (needs approval)

These are evidence-based proposals; nothing is applied by the agent.

**A. `TMPDIR` on disk for the session.** pip, pytest and Python `tempfile` then use the SSD. Whether Claude Code's own scratchpad follows `TMPDIR` must be confirmed after the restart (`echo $TMPDIR` and the scratchpad path).

```bash
sudo install -d -o nexolab-dev -g nexolab-dev -m 0700 /home/nexolab-dev/.cache/tmp
sudo install -d -m 0755 /etc/systemd/system/nexolab-dev-session.service.d
printf '[Service]\nEnvironment=TMPDIR=/home/nexolab-dev/.cache/tmp\n' | sudo tee /etc/systemd/system/nexolab-dev-session.service.d/20-tmpdir.conf >/dev/null
```

**B. One consistent memory budget for the dev account.**

- Keep `MemoryMax=1280M` and `MemorySwapMax=512M`.
- Set `MemoryHigh=1024M` on both the slice and the service: the service equals its parent, and both survive a reboot.

Evidence for 1024M:

- Claude alone holds about 550–620 MB anonymous memory.
- Targeted test runs add 100–250 MB.
- 768M leaves no room for page cache, so it throttles continuously even with swap free.
- 1024M keeps 256 MB of hard margin below `MemoryMax`.

```bash
sudo install -d -m 0755 /etc/systemd/system/user-1001.slice.d
printf '[Slice]\nMemoryHigh=1024M\nMemoryMax=1280M\nMemorySwapMax=512M\n' | sudo tee /etc/systemd/system/user-1001.slice.d/50-dev-memory.conf >/dev/null
printf '[Service]\nMemoryHigh=1024M\nMemoryMax=1280M\nMemorySwapMax=512M\n' | sudo tee /etc/systemd/system/nexolab-dev-session.service.d/50-dev-memory.conf >/dev/null
sudo systemctl daemon-reload
systemctl show -p MemoryHigh,MemoryMax,MemorySwapMax user-1001.slice nexolab-dev-session.service
```

`daemon-reload` applies the slice values without restarting anything. `TMPDIR` takes effect at the next session start.

**Verification:**

- `python3 -I -B scripts/dev-resource-guard.py report` before and after;
- the rate of `memory.events` `high` over a working day, which should be near zero outside heavy jobs;
- the heartbeat lines `dev_mem`/`dev_swap` in `~/p0-evidence/heartbeat/`.

**Rollback:** remove the two drop-in files (and `20-tmpdir.conf`) and run `systemctl daemon-reload`.
