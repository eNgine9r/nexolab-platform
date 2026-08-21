# NEXOLAB Blockers

Updated: 2026-08-21

## Current Work Package boundary

Issue #633 is active `status:in-progress` in PR #643 (`fix/633-frontend-candidate-cleanup`). Software implementation through `f5c8a1e6eae289c4882664972a786fcfc3f2deb9` now isolates the candidate in an exact process group, confirms the actual PGID before publishing it, falls back to exact-PID termination during the pre-handshake race window, performs bounded group cleanup on success/error/exit paths, treats zombie-only group members as terminated, and verifies candidate port `3100` is free before continuing.

Initial Core CI run `32514504593` on `87afc111...` passed. Review findings for stale state, zombie-only PGID handling, and the pre-`setsid` PGID publication race are addressed in the current branch. Final exact-head CI/review remains the software merge gate.

The remote Raspberry Pi `nexolab-edge-01` is currently offline. This is a soft blocker only for real post-deployment runtime evidence. No production/site cutover is authorized by #633, so no deployment is being attempted while the Pi is offline.

## Security maintenance — CVE-2026-14456 deadline

Issue #598 is closed, but its four exact temporary `CVE-2026-14456` exceptions remain active in `security/vulnerability-exceptions.json` and expire on **2026-08-26**.

Owner: `platform-security`.

Required maintenance action: re-check Debian/fixed-package availability and remove the exceptions immediately when a fixed package becomes available, or review before 2026-08-26. If the exceptions expire unchanged, the Container Supply Chain policy gate is expected to fail closed. Any introduction of a QUIC/HTTP3 listener also invalidates the current reachability justification.

## Issue #618 — independent reliability lane

Saved Dashboard CSV browser-download reliability remains an independent open lane. It does not block #633 unless a required verification gate demonstrates a direct dependency.

## Issue #607 — queued architecture prerequisite

Dual RS-485 KK1/KK2 software isolation is queued before #589. Software architecture may proceed independently when selected, but any physical bus cutover/hardware action remains unapproved.

## Issue #589 — blocked on #607

Persistent device-scoped acquisition cadence/capacity work remains blocked until the #607 dual-bus architecture is established.

## Issue #590 — blocked on #589

Operator cadence controls remain blocked on the authoritative persisted cadence/capacity contract from #589.

## Issue #585 — hard physical handback blocker

Restoring LE-01MP W2 / Unit 201 remains blocked until the Product Owner confirms that the external controller no longer owns the W2 RS-485 interface and explicitly approves any required physical handback.

## Required evidence / validation lanes

- #444 — `status:needs-validation`, priority critical: LOCAL_LAN user-administration API acceptance remains open.
- #245 — `status:needs-validation`, priority critical: actual standalone loopback-only Raspberry Pi acceptance remains open.
- #200 — physical RS-485 topology, stable adapter paths, active Unit IDs, duplicate-ID isolation, termination/biasing, latency and safe polling envelope remain unverified beyond narrow retained pilot evidence.
- #201 — `status:needs-validation`, priority high: approved restart/power-cycle boundary for LE-01MP cumulative energy remains unverified.
- #202 — representative KK1/KK2 XJP60D evidence, firmware portability, and actual Unit ID 115 presence/absence remain unverified.
- #189 — `status:blocked`, priority high: full backup/restore/rollback/power-loss recovery requires controlled central-host/Raspberry Pi evidence.

## Non-blocking maintenance

- #615 tracks the authenticated-dashboard generated Compose project-name defect; explicit lowercase overrides remain the local workaround.
- Existing production remains deployed from `6e387485b68fb862d9f82ae7f6000b1f5b672764` until a separately authorized deployment/cutover.

## Safety boundaries

No Modbus/controller write, hardware write, product persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation, production/site cutover, or mandatory cloud runtime dependency is authorized by Issue #633.
