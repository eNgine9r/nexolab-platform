# Storage and resource audit, cleanup manifest and policy (#1710)

Host: `nexolab-edge-01` (Raspberry Pi 5, 4 GiB RAM, 234 GiB SSD). Audit date: 2026-11-23. Performed from the isolated `nexolab-dev` account, read-only towards production.

## Summary

- The SSD holds 199 GiB of data; only about 10 GiB is visible to the development account. About 189 GiB is in owner-only areas: `/home/nexolab` (Commander workspaces, deployment checkout, frontend releases, runtime evidence), `/var/lib/docker` (images and volumes, including PostgreSQL) and `/var/backups/nexolab`.
- The development workspace is small (629 MiB, of which 547 MiB is the Claude Code and Node.js tooling). Safe development cleanup reclaimed only about 3.5 MiB; this is not where the space is.
- Reaching 40–50 GiB free is plausible only through owner actions on **regenerable caches inside retired Commander workspaces**, superseded frontend releases and images, the APT cache and Docker build cache. Telemetry retention (#1551) must wait for a proven backup (#1428).
- The repository is lean (1,817 tracked files, 17.8 MiB packed, `git fsck` clean). One hazardous obsolete script was found (see "Repository audit").

## Baseline and after (development side)

| Measure                   | Before (08:13Z, pre-reboot) | After (08:22Z, post-reboot)  |
| ------------------------- | --------------------------- | ---------------------------- |
| SSD used / available      | 199 GiB / 24 GiB (90 %)     | 199 GiB / 24 GiB (90 %)      |
| RAM used / available      | 2328 / 1716 MiB             | 2075 / 1969 MiB              |
| Swap used                 | 894 MiB                     | 129 MiB                      |
| Load average (1/5/15)     | 0.57 / 0.72 / 0.78          | 0.70 / 0.61 / 0.26           |
| Development slice memory  | 638 MiB (peak 770)          | 646 MiB                      |
| Development home          | 629 MiB                     | 626 MiB                      |
| Device Agent              | degraded (Embraco unit 2)   | ok, sampling, MQTT connected |
| Telemetry readiness / lag | ready / 0.19 s              | ready / 0.15 s               |

The host rebooted unexpectedly at 08:15:55Z. The RAM and swap improvement is a reboot effect, not a cleanup result. Production recovered without intervention.

## Classification

### Development workspace (`/home/nexolab-dev`, fully inspected)

| Item                                     | Size      | Class  | Action / reason                                       |
| ---------------------------------------- | --------- | ------ | ----------------------------------------------------- |
| `~/.local/share/claude/versions/2.1.323` | 346 MiB   | KEEP   | active Claude Code binary (single version)            |
| `~/.local/node` (Node 22.23.1)           | 201 MiB   | KEEP   | local format checks; checksum-verified                |
| `~/.local/tools/prettier`                | 9.7 MiB   | KEEP   | Prettier 3.9.9 pinned to the lockfile                 |
| `~/nexolab-platform` clone               | 42 MiB    | KEEP   | working repository                                    |
| `~/.claude` (projects, plugins, backups) | 28 MiB    | KEEP   | session history and recovery                          |
| `~/.npm/_cacache`                        | 3.5 MiB   | CLEAN  | **removed** with `npm cache clean --force`            |
| merged local branches (3)                | refs only | CLEAN  | **removed** with `git branch -d` after ancestry check |
| private `/tmp` caches                    | < 1 MiB   | CLEAN  | discarded by the reboot (`PrivateTmp`)                |
| one dangling commit (stash test)         | < 1 KiB   | KEEP   | left for normal `git gc` expiry                       |
| 811 remote-tracking branches             | refs only | REVIEW | GitHub branch hygiene is an owner decision            |

### Visible system areas

| Item                      | Size    | Class         | Note                                                        |
| ------------------------- | ------- | ------------- | ----------------------------------------------------------- |
| `/usr`                    | 5.7 GiB | KEEP          | operating system                                            |
| `/var/cache/apt/archives` | 879 MiB | CLEAN (owner) | 360 downloaded `.deb` files; no NEXOLAB procedure uses them |
| `/var/log/journal`        | 257 MiB | KEEP          | already bounded                                             |
| `/boot`                   | 167 MiB | KEEP          | boot                                                        |

### Owner-only areas (sizes from #1551, 2026-11-10; refresh with the inventory script)

| Item                                                            | Size     | Class                                             |
| --------------------------------------------------------------- | -------- | ------------------------------------------------- |
| PostgreSQL (`telemetry_samples` 17 GB, session contexts 2.6 GB) | ~19.6 GB | PROTECTED until #1428, then #1551                 |
| Commander workspaces                                            | ~59 GB   | REVIEW (regenerable caches inside are candidates) |
| Frontend releases                                               | ~12 GB   | current and rollback PROTECTED; older REVIEW      |
| Runtime deployments and evidence                                | ~9.8 GB  | PROTECTED (evidence)                              |
| Docker images, build cache                                      | unknown  | protected IDs below; others REVIEW                |
| Docker volumes                                                  | unknown  | PROTECTED, never pruned                           |
| `/var/backups/nexolab`                                          | unknown  | PROTECTED                                         |
| microSD fallback root (`/dev/mmcblk0p2`)                        | 52 GiB   | separate media, #1555; not SSD space              |

### Protected identities (never remove)

From `.project/LAST_CHECKPOINT.json` baselines:

- Device Agent deployed image `sha256:b96be6cb7ca8a9c71eb94976fe787b35b7a9d5cd2b426c6966a868ca5cc3d15e`;
- Device Agent rollback image `sha256:bcfcbb5320017d3f4a205c748f642002ddb70b7fd466a9ebc34e1c780c10244b`;
- SDM120 candidate Device Agent image `sha256:4964c1d4a43ec20e1f53962968e26b7a5e802841eead4abf7a7dd5360649dff1`;
- dashboard release `nexolab/dashboard:issue-1638-f0295409-arm64@sha256:c6c5ae80…` and rollback `nexolab/dashboard:issue-1522-469485b0-arm64@sha256:ec4d14d3…`, plus `external-ui/469485b0…`;
- evidence: `runtime/evidence/issue-1117-*`, `operation-evidence/reconcile-51dc3ae6-…`, `runtime/object-storage-migration/authority.json`, `commander-workspaces/nexolab-1638-release-f0295409/` (holds `site-activation-report-1638.json`);
- every image used by any container (any state), every Docker volume, PostgreSQL data, edge SQLite and outboxes, MQTT persistence, keys and `.env` files, `/var/backups/nexolab`.

## Owner-run read-only inventory

`docs/operations/storage/nexolab-storage-inventory.sh` collects the facts needed to turn REVIEW items into decisions. It is read-only: sizes, names, Git metadata, Docker metadata and two `SELECT` queries; no deletion, pruning, restart or secret contents. Scans are niced, bounded by a timeout and stay on the root filesystem.

```bash
sudo bash docs/operations/storage/nexolab-storage-inventory.sh /home/nexolab
```

The report lists, among others: Commander workspace sizes with Git state (dirty files, unpushed commits, stashes), regenerable cache directories, directories used by running processes and systemd units, Docker images with digests, images used by containers, dangling images, volumes and build cache, and the largest PostgreSQL relations.

## Owner cleanup manifest

Run each step only after reading the inventory report. Re-check production health (`/health`, `/health/ready`) after each step. Never use `docker system prune -a`, `docker volume prune`, `docker compose down -v`, `git clean` or `git reset --hard`.

| Step | Target                                                     | Class          | Expected reclaim        | Gate                                                      |
| ---- | ---------------------------------------------------------- | -------------- | ----------------------- | --------------------------------------------------------- |
| M1   | APT downloaded packages                                    | CLEAN          | ~0.9 GiB                | no `apt`/`dpkg` running                                   |
| M2   | Docker build cache older than 7 days                       | CLEAN          | from inventory          | none; images, containers and volumes are untouched        |
| M3   | operator npm content cache                                 | CLEAN          | from inventory          | no `npm` process running                                  |
| M4   | dangling images not used and not protected                 | REVIEW → CLEAN | from inventory          | candidate list computed below, reviewed ID by ID          |
| M5   | `node_modules`, `.next` in retired Commander workspaces    | REVIEW         | largest share of ~59 GB | workspace not in use, not referenced by evidence or units |
| M6   | superseded tagged `nexolab/*` images and frontend releases | REVIEW         | from inventory          | not current, not rollback, not referenced                 |
| M7   | runtime deployments and evidence                           | PROTECTED      | –                       | move off-device only after #1428/#1631 media exists       |
| M8   | telemetry older than 30 days                               | PROTECTED      | ~10–15 GB               | #1551 after a verified restore (#1428)                    |

M1–M3:

```bash
sudo apt-get clean                                        # M1
sudo docker builder prune --force --filter until=168h     # M2 (build cache only)
pgrep -u nexolab -f npm || sudo -u nexolab npm cache clean --force   # M3
```

M4, compute candidates (prints IDs, deletes nothing):

```bash
comm -23 \
  <(sudo docker images -q --filter dangling=true --no-trunc | sort -u) \
  <( (sudo docker ps -aq | xargs -r sudo docker inspect --format '{{.Image}}'; \
      printf '%s\n' \
        sha256:b96be6cb7ca8a9c71eb94976fe787b35b7a9d5cd2b426c6966a868ca5cc3d15e \
        sha256:bcfcbb5320017d3f4a205c748f642002ddb70b7fd466a9ebc34e1c780c10244b \
        sha256:4964c1d4a43ec20e1f53962968e26b7a5e802841eead4abf7a7dd5360649dff1) | sort -u)
# then, for each reviewed ID:  sudo docker image rm <ID>
```

M5, per retired workspace `W` (listed explicitly, never a glob): confirm in the report that `W` has `dirty=0`, `unpushed=0`, `stashes=0`, is not a process working directory, is not named in a systemd unit and is not an evidence path above; then remove only the regenerable caches:

```bash
sudo -u nexolab rm -rf --one-file-system "$W/node_modules" "$W/.next"
```

Whole-workspace retirement is a separate owner decision, preferably after an off-device archive exists (#1631).

M6: list `sudo docker images 'nexolab/*'` and the frontend release directories; keep the current release, its rollback and anything referenced by systemd units, compose environment files or rollback manifests; remove the rest one tag or directory at a time.

## RAM and CPU findings

Post-reboot resident memory by process group (approximate, shared pages counted per process):

| Group                                                             | RSS      | Owner       | Finding                                                              |
| ----------------------------------------------------------------- | -------- | ----------- | -------------------------------------------------------------------- |
| Claude Code                                                       | ~440 MiB | development | largest single process; bounded by the slice (768/1280 MiB)          |
| PostgreSQL (10 processes)                                         | ~416 MiB | production  | expected                                                             |
| Node (Commander, funnel gateway, proxy, remote admin)             | ~337 MiB | operator    | auxiliary; review need per process (R4)                              |
| Grafana, Prometheus, Alertmanager                                 | ~400 MiB | production  | optional observability (R1)                                          |
| Next.js servers (3)                                               | ~220 MiB | production  | LAN :3000, HTTPS :3105 and one more; pre-reboot there were five (R4) |
| Telemetry service (uvicorn)                                       | ~189 MiB | production  | expected                                                             |
| Desktop session (labwc, panel, portals, VNC, file manager, audio) | ~340 MiB | operator    | needed only for the local kiosk/remote desktop (R2)                  |
| Docker engine, shims, proxies                                     | ~340 MiB | system      | expected                                                             |
| `packagekitd`                                                     | ~46 MiB  | system      | idle package daemon (R3)                                             |

CPU is not a constraint (load below 1 on 4 cores). Development is capped at one core with `CPUWeight=20` and `IOWeight=20`, so production wins contention.

Recommendations (each a separate owner-approved Work Package; nothing was changed):

- **R1** decide whether Grafana, Prometheus and Alertmanager must run continuously (~400 MiB) or on demand.
- **R2** decide whether the full desktop session is required (#1426 local kiosk) or a lighter kiosk is enough (~340 MiB).
- **R3** mask `packagekit` if graphical package management is not used.
- **R4** confirm the purpose of each Next.js and Node process. Listeners `127.0.0.1:3107`, `:3108` and `:3119` existed before the reboot and did not return; they are not repository-managed and should stay off unless needed.

## Repository audit

- Size: 1,817 tracked files, 17.8 MiB packed, no large binaries; the largest files are project state (`.project/*`, ~1.4 MiB) and `package-lock.json`.
- `git fsck --connectivity-only`: clean apart from one dangling commit from a stash test.
- Script reference scan (`scripts/`, excluding tests): four files are referenced nowhere else.
  - `scripts/repair-postgres-role-password.sh`, `scripts/resume-central-api-raspberry-pi.sh`: incident recovery tools from #162. **KEEP** — unreferenced is not obsolete for recovery tooling.
  - `scripts/run-chart-benchmark.mjs`: drives `tests/chart-benchmark/`, used by the #1620 density benchmark. **KEEP**.
  - `scripts/deploy-disabled-auth-websocket-fix.sh`: one-off July deployment that copies the WebSocket client from the `ops/raspberry-pi-current-head-launch` branch over the working tree, builds and restarts `nexolab-dashboard.service`. Running it today would deploy July code to production. **Obsolete and hazardous**; removed in a separate focused PR.
- Broader dead-code analysis of `src/` and `services/` (unused components, modules, dependencies) needs the full Node toolchain and is proposed as a CI-run follow-up, not done on the Pi.

## Storage and resource policy

1. **Floors.** Keep at least 20 GiB free on `/` at all times. Below 30 GiB, run the read-only inventory and plan cleanup. Below 20 GiB, stop development (the session start script refuses to start Claude) and record a blocker.
2. **Development caches.** No `node_modules`, `.next` or browser binaries in the development clone; `npm ci`, builds and browser tests run in GitHub Actions. Clean the npm cache after any local `npm install`. Keep a single Claude Code version.
3. **Build artifacts.** Release artifacts are produced by CI and downloaded once, verified by digest. Do not keep duplicate copies of the same artifact in several workspaces.
4. **Release retention.** Keep the current release, its declared rollback and the artifacts referenced by evidence. Older releases are removed only after the next release has passed its acceptance and rollback check.
5. **Workspace retirement.** A workspace is retired only when its Git state is clean, nothing is unpushed or stashed, no process or unit uses it and no evidence path points into it. Remove regenerable caches first; archive off-device before removing the workspace itself.
6. **Docker.** Targeted removal by ID or tag only. Never `system prune -a`, `volume prune` or `compose down -v`. Prune build cache older than 7 days when needed.
7. **Logs.** Keep journald bounded (currently 257 MiB) and evidence logs within their evidence directories.
8. **Monitoring.** The development session start script checks free disk and host memory at every start. The owner runs the inventory script monthly or below 30 GiB, and attaches the summary to the storage issue.
9. **Data.** Telemetry, SQLite, MQTT persistence, keys and backups are never deleted to free space. Retention follows #1551 only after #1428.
