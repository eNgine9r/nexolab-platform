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

## Stage 2 — apply a reviewed, checksum-pinned manifest

Scheduled and manual report runs never change anything. Each report writes a manifest (`/var/lib/nexolab-storage/manifest-<stamp>.json`) and prints its SHA-256. Every candidate was already checked against: the protected image and path inventories (both required — if either is missing, empty or unreadable, **no** image or release candidate is produced), images used by any container, container bind mounts, systemd units, running processes, and every mention of the release name or image ID in the reference roots (deployment, rollback and recovery records, offline bundle manifests, backups, workspaces, project state). Referenced items appear as `kept: … (referenced by N record(s), e.g. …)` and are never candidates. If Docker cannot be listed or inspected, image and release candidates are withheld (`WITHHELD` line).

Review the manifest, then apply exactly that file:

```bash
M=/var/lib/nexolab-storage/manifest-<stamp>.json
sudo sha256sum "$M"                      # must equal the hash printed by the report
sudo python3 -I /usr/local/lib/nexolab-storage/nexolab-storage-housekeeping.py \
  --env-file /etc/nexolab-storage/housekeeping.env --apply-manifest "$M" --manifest-sha256 <approved-hash>
df -h /
```

Apply re-plans everything and executes only manifest entries that are **still** eligible; anything that became protected, used or referenced since the report is skipped and listed. A wrong hash is refused. There is no unattended apply; the weekly timer only refreshes the report and manifest.

What a manifest can contain: APT downloads; Docker build cache older than 7 days; dangling images older than 7 days; `<sha>-<stamp>` frontend releases outside the newest 3 and older than 14 days. Never: volumes, containers, tagged images, PostgreSQL, evidence, deployments, backups, Commander workspaces.

Large individual workspaces (for example `guarded-update-1313`) are reviewed separately and read-only first:

```bash
sudo bash docs/operations/storage/nexolab-workspace-review.sh /home/nexolab/commander-workspaces/nexolab-platform/guarded-update-1313 "$HOME"
```

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
