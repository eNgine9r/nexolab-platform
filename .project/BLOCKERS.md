# NEXOLAB Blockers

Updated: 2026-08-23

## Issue #615 — implementation verified, final state-head pending

Issue #615 is software/tooling-complete in PR #658. Verified head `107935b7ab08ca48878b73603a6d1a9e683985f0` passed Core CI, the three focused project-name regression tests, Authenticated Dashboard Acceptance without a manual Compose project-name override and `NEXOLAB Merge Gate`; unresolved review threads are zero.

There is no product/software hard blocker. Only the final state-recording head must repeat its exact-head checks before merge.

No Raspberry Pi access, secrets, product-runtime mutation, Modbus operation, hardware action or site cutover is required for this tooling-only Work Package.

## Issue #590 — software completed, hardware evidence pending

Issue #590 merged through PR #657. Its authenticated Settings control plane remains software-verified, while physical cadence acceptance on the real KK1/KK2 installation remains unavailable because the Remote Desktop/Raspberry Pi connector is offline.

Do not convert software capacity evidence into a hardware acceptance claim.

## Issue #607 — software completed, hardware evidence pending

Dual RS-485 isolation was accepted through PR #653. Physical two-adapter verification remains unavailable while the Raspberry Pi connector is offline.

Repository evidence maps XJP60D KK2 to Unit IDs `101..115` and KK1 to `126..138`. LE-01MP Unit IDs `200..203` still have no repository-backed KK1/KK2 ownership and must not be guessed.

## Issue #646 — branch protection settings access

Repository-side change-impact CI, exact-head external-workflow aggregation and the stable merge gate are software-verified.

Current GitHub observation still reports:

- `main` protected: false;
- required status checks: disabled.

The connected GitHub surface does not expose the required branch-protection/rules mutation. This remains a **soft access blocker** only.

## Security maintenance — CVE-2026-14456

Issue #598 is closed, but four temporary `CVE-2026-14456` exceptions expire on **2026-08-26**.

Owner: `platform-security`.

Re-check fixed Debian package availability and remove the exceptions immediately when a fix becomes available, or review before expiry. Any change that makes QUIC/HTTP3 reachable invalidates the current reachability justification.

## Product and validation dependencies

- #585 — blocked until explicit physical W2 / Unit 201 handback approval.
- #444 — LOCAL_LAN user-administration API acceptance remains `needs_validation`.
- #245 — standalone loopback-only Raspberry Pi acceptance remains `needs_validation`.
- #200 — physical RS-485 topology and safe polling envelope remain hardware-unverified beyond retained evidence.
- #201 — LE-01MP restart/power-cycle evidence remains pending.
- #202 — XJP60D KK1/KK2 portability and Unit ID 115 presence/absence remain hardware-unverified.
- #189 — controlled backup/restore/rollback/power-loss recovery evidence remains outstanding.

## Safety boundaries

No Modbus/controller write, hardware write, product persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation, production/site cutover or mandatory cloud runtime dependency is authorized by Issue #615.
