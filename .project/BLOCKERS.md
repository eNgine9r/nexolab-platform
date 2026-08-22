# NEXOLAB Blockers

Updated: 2026-08-22

## Current Work Package boundary — Issue #646

Issue #646 — **Add change-impact CI orchestration and protected main merge gate** — is active `status:in-progress` in branch `chore/646-impact-aware-ci`.

Repository-side implementation can proceed independently. The current connected GitHub tool surface supports repository files, branches, Pull Requests, CI inspection and merge operations, but it does not expose a mutation for branch protection/rules. This is a **soft access blocker** for the final repository-settings acceptance criterion only; it does not block implementing or verifying the classifier, state-only lane, deterministic Node install, stable Core merge gate, tests or documentation.

`main` remains unprotected until branch/rules settings are actually changed and verified. Do not report technical branch protection as complete before that evidence exists.

The remote `nexolab-edge-01` is offline. Issue #646 requires no Raspberry Pi or hardware acceptance, so this is not a blocker for the active Work Package.

## Completed state boundary

Issue #644 / PR #645 is complete and GREEN merged as `bd2a0a56b8c3e67cdf960419076b154302da9e2f`. The accepted #633 product source remains `6d223415deebf1a44bb52ba4fcaa3c5db9b03697`; the #645 state-only merge did not change product/runtime code.

## Security maintenance — CVE-2026-14456 deadline

Issue #598 is closed, but its four exact temporary `CVE-2026-14456` exceptions remain active in `security/vulnerability-exceptions.json` and expire on **2026-08-26**.

Owner: `platform-security`.

Required maintenance action: re-check Debian/fixed-package availability and remove the exceptions immediately when a fixed package becomes available, or review before 2026-08-26. If the exceptions expire unchanged, the Container Supply Chain policy gate is expected to fail closed. Any introduction of a QUIC/HTTP3 listener also invalidates the current reachability justification.

## Issue #618 — independent reliability lane

Saved Dashboard CSV browser-download reliability remains an independent open lane. It is not mixed into #646.

## Issue #607 — architecture prerequisite lane

Dual RS-485 KK1/KK2 software isolation remains queued before #589. Any physical bus cutover/hardware action remains unapproved.

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

No Modbus/controller write, hardware write, product persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation, production/site cutover, or mandatory cloud runtime dependency is authorized by Issue #646.
