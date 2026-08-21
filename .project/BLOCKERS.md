# NEXOLAB Blockers

Updated: 2026-08-21

## Current Work Package boundary

Issue #606 is complete. PR #632 merged GREEN into `main` as `dc2b130cbd0f9f6e84dcfec1dc8ee045b18ab8cc`; Issue #606 is closed `status:done`.

Issue #641 is a state-only post-merge reconciliation package. It changes only `.project/CURRENT_STATE.md`, `.project/ACTIVE_SPRINT.json`, `.project/BLOCKERS.md`, and `.project/LAST_CHECKPOINT.json`. It introduces no product/runtime, dependency, migration, Modbus, hardware, or deployment behavior.

There is no remaining #606 product, software, CI, review, LAN, or hardware-acceptance blocker.

## Security maintenance — CVE-2026-14456 deadline

Issue #598 is closed, but its four exact temporary `CVE-2026-14456` exceptions remain active in `security/vulnerability-exceptions.json` and expire on **2026-08-26**.

Owner: `platform-security`.

Required maintenance action: re-check Debian/fixed-package availability and remove the exceptions immediately when a fixed package becomes available, or review before 2026-08-26. If the exceptions expire unchanged, the Container Supply Chain policy gate is expected to fail closed. Any introduction of a QUIC/HTTP3 listener also invalidates the current reachability justification.

## Issue #633 — Ready

The successful 2026-08-21 Raspberry Pi production deployment left an isolated frontend candidate listening on `127.0.0.1:3100` after `DEPLOYMENT PASSED`. It was manually stopped and production remained healthy.

Issue #633 is Ready/high and is the expected next Work Package after #641 is merged and the Ready audit confirms no higher-priority dependency change.

No production cutover is required to implement the deterministic cleanup behavior. Any real deployment/cutover remains separately controlled.

## Issue #618 — independent reliability lane

Saved Dashboard CSV browser-download reliability remains an independent open lane. It does not block #641 or #633 unless a required verification gate demonstrates a direct dependency.

## Issue #607 — queued architecture prerequisite

Dual RS-485 KK1/KK2 software isolation is queued before #589. Software architecture may proceed independently when selected, but any physical bus cutover/hardware action remains unapproved.

## Issue #589 — blocked on #607

Persistent device-scoped acquisition cadence/capacity work remains blocked until the #607 dual-bus architecture is established.

## Issue #590 — blocked on #589

Operator cadence controls remain blocked on the authoritative persisted cadence/capacity contract from #589.

## Issue #585 — hard physical handback blocker

Restoring LE-01MP W2 / Unit 201 remains blocked until the Product Owner confirms that the external controller no longer owns the W2 RS-485 interface and explicitly approves any required physical handback.

The review window is not authorization for hardware changes.

## Required evidence / validation lanes

- #444 — `status:needs-validation`, priority critical: LOCAL_LAN user-administration API acceptance remains open.
- #245 — `status:needs-validation`, priority critical: actual standalone loopback-only Raspberry Pi acceptance remains open.
- #201 — `status:needs-validation`, priority high: approved restart/power-cycle boundary for LE-01MP cumulative energy remains unverified.
- #189 — `status:blocked`, priority high: full backup/restore/rollback/power-loss recovery requires controlled central-host/Raspberry Pi evidence; missing hardware evidence must remain explicit.

These lanes are not silently completed by unrelated software CI and must remain visible in Sprint planning.

## Non-blocking maintenance

- #615 tracks the authenticated-dashboard generated Compose project-name defect; explicit lowercase overrides remain the local workaround.
- Existing production remains deployed from `6e387485b68fb862d9f82ae7f6000b1f5b672764` until a separately authorized deployment/cutover.

## Safety boundaries

No Modbus/controller write, hardware write, product persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation, production/site cutover, or mandatory cloud runtime dependency is authorized by the current state-only reconciliation.
