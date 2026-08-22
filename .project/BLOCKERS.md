# NEXOLAB Blockers

Updated: 2026-08-22

## Issue #650 — no hard blocker

State Model v2 implementation is active and repository-local. It requires no Raspberry Pi, hardware, production cutover, secret, billing/DNS or external runtime service.

The migration must preserve the accepted/deployed baselines, known exact-head/hardware evidence, the current Sprint queue, blockers and the 2026-08-26 security maintenance deadline.

## Issue #646 — branch protection settings access

Repository-side change-impact CI, deterministic `npm ci`, exact-head external-workflow aggregation and the canonical state-only fast lane are software-verified.

The remaining acceptance criterion is technical branch protection for `main`.

A timestamped GitHub observation on 2026-08-22 reports:

- `main` protected: false;
- required status checks: disabled.

The connected GitHub tool surface does not expose branch-protection/rules mutation. This is a **soft access blocker** only. Do not represent branch protection as complete until the repository setting is actually changed and verified.

## Security maintenance — CVE-2026-14456

Issue #598 is closed, but four temporary `CVE-2026-14456` exceptions expire on **2026-08-26**.

Owner: `platform-security`.

Re-check fixed Debian package availability and remove the exceptions immediately when a fix becomes available, or review before expiry. Any change that makes QUIC/HTTP3 reachable invalidates the current reachability justification.

## Product and validation dependencies

- #618 — independent Saved Dashboard CSV browser-download reliability lane.
- #607 — dual RS-485 KK1/KK2 software architecture is queued before #589; no physical bus cutover is approved.
- #589 — blocked on #607.
- #590 — blocked on #589.
- #585 — blocked until explicit physical W2 / Unit 201 handback approval.
- #444 — LOCAL_LAN user-administration API acceptance remains `needs_validation`.
- #245 — standalone loopback-only Raspberry Pi acceptance remains `needs_validation`.
- #200 — physical RS-485 topology and safe polling envelope remain hardware-unverified beyond retained evidence.
- #201 — LE-01MP restart/power-cycle evidence remains pending.
- #202 — XJP60D KK1/KK2 portability and Unit ID 115 presence/absence remain hardware-unverified.
- #189 — controlled backup/restore/rollback/power-loss recovery evidence remains outstanding.

## Safety boundaries

No Modbus/controller write, hardware write, product persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation, production/site cutover or mandatory cloud runtime dependency is authorized by Issue #650.
