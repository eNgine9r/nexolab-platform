# Storage reclamation plan and automatic housekeeping (#1710, #1551)

Target: at least **50 GiB free** on `/` of `nexolab-edge-01` (234 GiB SSD; 23 GiB free on 2026-11-23), without losing production data, evidence, the current release or its rollback.

Monitoring after installation: **warning below 40 GiB, critical below 20 GiB** (`nexolab-storage-guard.timer`, every 15 minutes).

## Where the space is (owner inventories 2026-11-10/21/23)

| Area                                                         | Size                                | Class                                    | Handled by                            |
| ------------------------------------------------------------ | ----------------------------------- | ---------------------------------------- | ------------------------------------- |
| PostgreSQL (`telemetry_samples` ~21 GB of ~24 GB)            | ~24 GB                              | PROTECTED until #1428                    | #1551 retention + reclamation runbook |
| Commander workspaces (`nexolab-platform` 34.6 GiB of 58 GiB) | ~58 GiB                             | REVIEW (old release workspaces)          | owner, step 4                         |
| `runtime/frontend-releases`                                  | ~12 GiB                             | current + rollback PROTECTED, rest CLEAN | automatic housekeeping                |
| `runtime/deployments`                                        | ~9.8 GiB                            | PROTECTED (deployment evidence)          | off-device archive only after #1631   |
| `runtime/evidence`, external frontend releases               | ~3.8 GiB                            | PROTECTED                                | —                                     |
| Docker images                                                | ~26 GB, ~14 GB labelled reclaimable | dangling CLEAN; superseded tags REVIEW   | housekeeping (dangling); owner (tags) |
| Docker volumes                                               | ~32 GB                              | PROTECTED (includes PostgreSQL)          | never pruned                          |
| APT downloaded packages                                      | ~0.9 GiB                            | CLEAN                                    | automatic housekeeping                |

## Expected result

| Stage                                                                                    | Reclaim (estimate) | Free after (from 23 GiB) |
| ---------------------------------------------------------------------------------------- | -----------------: | -----------------------: |
| 1–2 Automatic housekeeping (APT, build cache, dangling images, releases beyond newest 3) |           5–10 GiB |               ~28–33 GiB |
| 3 Inventory-listed caches in idle, clean Commander workspaces (M5)                       |           3–10 GiB |               ~31–43 GiB |
| 4 Superseded tagged images and retired Commander release workspaces (owner review)       |          15–30 GiB |           **~46–73 GiB** |
| 5 PostgreSQL 30-day retention + one `VACUUM FULL` window (after #1428)                   |           14–18 GB |           **~60–90 GiB** |

The ranges are estimates from earlier inventories; the read-only inventory (`nexolab-storage-inventory.sh`) and the housekeeping report give the exact figures on the day. Stages 1–3 need no data decision; 50 GiB is reached reliably only with stage 4 or 5.

## Stage 0 — read-only inventory

Run the checksum-pinned inventory (see `storage-resource-audit-1710.md`). It ends with a candidate list (M1–M5) and an estimated total. Nothing is deleted.

## Stage 1 — install guard and housekeeping in report mode

Owner, from a checkout of `main` (or the checksum-pinned download used for the other owner tools):

```bash
sudo install -d -o root -g root -m 0755 /usr/local/lib/nexolab-storage /etc/nexolab-storage
sudo install -o root -g root -m 0755 docs/operations/storage/nexolab-storage-housekeeping.py /usr/local/lib/nexolab-storage/
sudo install -o root -g root -m 0644 docs/operations/storage/housekeeping.env.example /etc/nexolab-storage/housekeeping.env
sudo install -o root -g root -m 0644 docs/operations/storage/protected-images.example /etc/nexolab-storage/protected-images
sudo install -o root -g root -m 0644 docs/operations/storage/protected-paths.example /etc/nexolab-storage/protected-paths
sudo install -o root -g root -m 0644 docs/operations/storage/nexolab-storage-guard.service docs/operations/storage/nexolab-storage-guard.timer \
  docs/operations/storage/nexolab-storage-housekeeping.service docs/operations/storage/nexolab-storage-housekeeping.timer /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/nexolab-storage-*.service /etc/systemd/system/nexolab-storage-*.timer
sudo systemctl daemon-reload
sudo systemctl enable --now nexolab-storage-guard.timer
sudo systemctl start nexolab-storage-housekeeping.service      # report mode: prints the plan only
journalctl -u nexolab-storage-housekeeping.service -o cat --no-pager | tail -60
```

Before stage 2, add the **recorded frontend rollback release** to `/etc/nexolab-storage/protected-paths` if it is not among the newest three releases (`sudo systemctl show nexolab-dashboard.service -p WorkingDirectory` gives the current one; the rollback is recorded in the latest deployment evidence).

## Stage 2 — apply automatic housekeeping

After reviewing the report (every `planned:` line, every `kept:` reason):

```bash
sudo sed -i 's/^STORAGE_HOUSEKEEPING_MODE=report$/STORAGE_HOUSEKEEPING_MODE=apply/' /etc/nexolab-storage/housekeeping.env
sudo systemctl start nexolab-storage-housekeeping.service
journalctl -u nexolab-storage-housekeeping.service -o cat --no-pager | tail -60
sudo systemctl enable --now nexolab-storage-housekeeping.timer   # weekly, Sunday 03:30
df -h /
```

What it may remove: APT downloads; Docker build cache older than 7 days; dangling images older than 7 days not used by any container and not in `protected-images`; `<sha>-<stamp>` frontend releases outside the newest 3, older than 14 days, not referenced by any systemd unit, not used by a process and not in `protected-paths`. Never: volumes, containers, tagged images, PostgreSQL, evidence, deployments, backups, Commander workspaces.

## Stage 3 — idle Commander workspace caches (M5)

Use the exact `M5 CLEAN` commands printed by the inventory (one `rm -rf --one-file-system` per `node_modules` or `.next` directory of a clean, idle, unreferenced workspace). `M5 REVIEW` lines stay.

## Stage 4 — owner review: superseded tagged images and retired release workspaces

List image tags with size and whether any container uses them:

```bash
sudo docker ps -a --format '{{.Image}}' | sort -u          # images used by containers: keep
sudo docker images --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.CreatedSince}} {{.Size}}' | sort
```

Keep: every image used by a container, every ID in `protected-images`, the current and rollback dashboard images (`issue-1638-f0295409-arm64`, `issue-1522-469485b0-arm64`) and the commissioned Device Agent (`nexolab/quick-agent:1490`). Remove other superseded `nexolab/*` tags one at a time:

```bash
sudo docker image rm <repository>:<tag>     # never -f; refuses if a container still uses it
```

Retired Commander release workspaces (for example `guarded-update-1313`, `release-1381-*`, `release-1376-*`): first archive off-device once #1631 media exists, or confirm with the inventory that they are clean, pushed, idle and not evidence; then remove each explicitly listed directory:

```bash
sudo -u nexolab rm -rf --one-file-system '/home/nexolab/commander-workspaces/nexolab-platform/<retired-workspace>'
```

## Stage 5 — PostgreSQL

Only after #1428 (verified backup and independent restore): follow `postgresql-storage-reclamation.md` — dry-run counts, enable `RETENTION_TELEMETRY_DELETE_ENABLED`, let the backlog drain, then one owner-approved `VACUUM FULL telemetry_samples` window.

## Never

`docker system prune -a`, `docker volume prune`, `docker compose down -v`, deleting PostgreSQL or SQLite files, backups, evidence or the current/rollback release, `git clean` or `git reset --hard` in deployment checkouts, an unbounded `DELETE` or an unplanned `VACUUM FULL`.
