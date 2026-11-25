# NEXOLAB #1553 — inactive developer cache reclamation (2026-11-10)

**Scope:** One-time source/developer workspace cache removal on `nexolab-edge-01`. This is **not** a protected site release, production database retention or recovery/backup cleanup.

## Actual site measurements

- Prior to this Work Package: `df -B1 /` on `/dev/sda2` reported 250372304896 bytes filesystem capacity, 200319201280 bytes used, **37260357632 bytes available** (85%).
- After removing ignored generated directories: filesystem still 250372304896 bytes, **191895007232 bytes used, 45684551680 bytes available** (81%).
- Free space increased by **8424194048 bytes**, or **7.85 GiB**. This is actual physical filesystem headroom, not an additive `du` estimate.
- Earlier, independent cleanup in the same session brought free capacity up from the initial ~7.2 GiB to ~34.7 GiB. Cumulative available space is ~42.55 GiB, but this package claims only its own delta.

## What was removed

Only explicitly allowlisted `node_modules` and `.next` directories inside these **inactive** NEXOLAB source worktrees:

- `/home/nexolab/nexolab-{1003,1136,1140,1146,1147,923,compat-1019,verify-965-a}`
- `/home/nexolab/worktrees/nexolab-{1075,1104,chart-hover,point-budget}`
- `/home/nexolab/commander-workspaces/nexolab-external-stage/source-4b9dc85`
- `/home/nexolab/commander-workspaces/nexolab-platform/.next`

22 first-pass eligible directories were selected with an exact allowlist and checks for git-ignore, real directory (not symlink), worktree status, active process working directory and mountpoint; **20 were deleted**, two `nexolab-compat-1019` directories were blocked by filesystem permissions. The symlinked `nexolab-1140/node_modules` was skipped. A second pass removed 3 additional ignored generated directories. No source files, Git objects, tracked configs or named backup/recovery materials were removed.

**Important discovered active use:** a host Next.js process has its working directory at `/home/nexolab/commander-workspaces/nexolab-platform/quick-1490`. It was deliberately not included in this cleanup. The separate external frontend service points to `/home/nexolab/commander-workspaces/nexolab-1520-artifacts-4be678f6/external/release`; that release was not touched.

## Runtime verification

- 13 active NEXOLAB containers remained running. Health-status enabled containers reported healthy; MinIO lacks a health status.
- `nexolab-external-frontend.service` and `nexolab-external-nginx.service` both returned `active`.
- Actual PostgreSQL `telemetry_samples MAX(id)` increased from **13482333** before cache cleanup to **13482381** during post-cleanup check. This verifies continued insertion, not full hardware acceptance.
- Docker volumes, installed container images and currently running frontend build were not removed or restarted; no Modbus/hardware writes.

## Deliberately preserved

- `/var/lib/nexolab/version-management/catalog` (~13 GB), `/var/backups/nexolab` (~8 GB), `runtime/deployments` and old `runtime/frontend-releases` may contain protected restore/rollback assets.
- PostgreSQL and other Docker volumes, Docker images labelled reclaimable, site telemetry, session evidence and old tests' raw archives were **not** deleted.
- `/home/nexolab/commander-workspaces/nexolab-platform/guarded-update-1313-df5485f6`, accepted `release-1376`/`release-1381`, active `1520` installation, and other artifacts have not passed a verified unpinned-releases inventory.

## Risks, blocked work, follow-up

- Old source worktrees no longer have ready-to-use dependencies; a future developer must reinstall them via the repository's pinned lockfile (`npm ci`) and rebuild as needed. This does not require internet at **runtime**.
- A few stale directories are permission protected, not assumed safely disposable.
- **Hard blocker:** #1428 still lacks independently tested full recovery of PostgreSQL, object storage, MQTT, edge SQLite/outbox, local auth and rollback. Do not run bulk SQL deletion, `docker image prune -a`, `docker volume prune`, rollback release deletion, or production cutover.
- #1551 / draft PR #1552 addresses evidence-safe 30-day telemetry policy in source only. It is not deployed.
- Next bounded Work Package after the disaster-recovery proof: build a referenced/pinned release manifest and an explicit retention policy for unpinned artifacts, with a dry-run inventory and verified restoration.
