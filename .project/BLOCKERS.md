# NEXOLAB Blockers

Updated: 2026-08-22

## Current Work Package boundary

Issue #633 is active `status:in-progress` in PR #643 (`fix/633-frontend-candidate-cleanup`). Final software and regression behavior before the state checkpoint is `68835e14798d49c01ff4a2bd4de98e6c8e8fdc22`.

The candidate lifecycle uses a parent/child startup gate so Next.js cannot execute before the parent records the exact background PID. After release, PGID publication is confirmed with `ps`; cleanup re-checks an unpublished PID for an already-established exact process group before using exact-PID fallback. Established groups use bounded TERM → KILL cleanup. Both exact-PID and process-group paths verify the candidate is no longer live before calling `wait`; if it remains live after the bounded TERM/KILL windows, cleanup returns failure instead of hanging indefinitely. Zombie-only members do not count as executable work, EXIT cleanup failures are surfaced, and the focused cleanup regression suite is part of the standalone runtime CI entry point.

Verified software gates:

- Core CI `32514504593` on `87afc111...`: PASS;
- Core CI `32517056093` on `08884615...`: PASS;
- Core CI `32519957941` on `a7d91af1...`: PASS;
- Core CI `32521673945` on `b3420a3b...`: PASS;
- Core CI `32523415155` on `c2873686...`: PASS.

Fresh review on GREEN head `c2873686...` identified the remaining unbounded child-reap wait; it is fixed and regression-covered in `68835e14...`. Final exact-head CI and fresh review on the new state-checkpoint head remain the only software merge gates.

The remote Raspberry Pi `nexolab-edge-01` is currently offline. This is a soft blocker only for real post-deployment runtime evidence. No production/site cutover is authorized by #633, so no deployment is being attempted.

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
