# NEXOLAB Blockers

Updated: 2026-08-22

## Current Work Package boundary

Issue #633 is complete. PR #643 squash-merged GREEN into `main` as `6d223415deebf1a44bb52ba4fcaa3c5db9b03697`; Issue #633 is closed `status:done`.

Issue #644 is a state-only post-merge reconciliation package. It changes only `.project/CURRENT_STATE.md`, `.project/ACTIVE_SPRINT.json`, `.project/BLOCKERS.md`, and `.project/LAST_CHECKPOINT.json`. It introduces no product/runtime, dependency, migration, Modbus, hardware, or deployment behavior.

There is no remaining #633 software/CI/review blocker. Real Raspberry Pi post-deployment runtime verification remains `UNVERIFIED_PI_OFFLINE` and must not be represented as completed hardware acceptance.

The requested final Codex automated review for #633 could not run because the code-review usage limit was reached. This is a tooling limitation, not a software/runtime failure; all existing P1/P2 review threads are resolved and the exact final diff received Team Lead review before GREEN merge.

## Security maintenance — CVE-2026-14456 deadline

Issue #598 is closed, but its four exact temporary `CVE-2026-14456` exceptions remain active in `security/vulnerability-exceptions.json` and expire on **2026-08-26**.

Owner: `platform-security`.

Required maintenance action: re-check Debian/fixed-package availability and remove the exceptions immediately when a fixed package becomes available, or review before 2026-08-26. If the exceptions expire unchanged, the Container Supply Chain policy gate is expected to fail closed. Any introduction of a QUIC/HTTP3 listener also invalidates the current reachability justification.

## Issue #618 — independent reliability lane

Saved Dashboard CSV browser-download reliability remains an independent open lane. Its formal Ready status must be established by the post-#644 GitHub Ready audit before implementation starts.

## Issue #607 — architecture prerequisite lane

Dual RS-485 KK1/KK2 software isolation is queued before #589. Its formal Ready status must be established by the post-#644 GitHub Ready audit. Any physical bus cutover/hardware action remains unapproved.

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
- Production remains deployed from `6e387485b68fb862d9f82ae7f6000b1f5b672764` until a separately authorized deployment/cutover.

## Safety boundaries

No Modbus/controller write, hardware write, product persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation, production/site cutover, or mandatory cloud runtime dependency is authorized by Issue #644 or any unselected queued lane.
