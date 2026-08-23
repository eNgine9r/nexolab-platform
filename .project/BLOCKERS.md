# NEXOLAB Blockers

Updated: 2026-08-23

## Issue #200 — physical topology evidence blocked

Passive evidence on 2026-08-23 confirms exactly one stable CP2104 RS-485 adapter on `nexolab-edge-01`, with the production Device Agent using legacy `rs485-main` at `9600 8N1`, `0.30 s` timeout and one retry. A 60-second non-invasive observation recorded 402 physical requests, 306 successes, 96 timeout/retry outcomes and bus load rising from 75.591% to 76.942%. No service operation or independent Modbus scan was introduced.

Full Issue #200 acceptance remains blocked because remote software evidence cannot establish cable topology, termination, biasing, shielding/grounding, electrical duplicate Unit IDs or physical presence/absence of Unit ID 115. The intended #607 two-adapter KK1/KK2 topology is also not physically available: only one serial adapter is enumerated.

Resume #200 only with safe physical inspection and/or the intended isolated second adapter. Do not start a parallel Modbus master on the active production segment.

## Issue #444 — route availability restored, full admin acceptance still gated

A read-only production probe on 2026-08-23 shows `/api/v1/admin/users` is mounted in OpenAPI and reaches the security layer (`HTTP 400 organization_header_required` without auth context), rather than the historical HTTP 404. Full acceptance still requires an authorized administrator identity and local-user creation/authentication checks, which are not performed without the required credential/security-mutation approval.

## Issue #590 — software completed, hardware evidence pending

Issue #590 merged through PR #657. Its authenticated Settings control plane remains software-verified. The Raspberry Pi connector is online, but the deployed product source remains older and no controlled #589/#590 deployment or physical cadence acceptance has been performed.

Do not convert software capacity evidence into a hardware acceptance claim.

## Issue #607 — software completed, hardware evidence pending

Dual RS-485 isolation was accepted through PR #653. The Raspberry Pi connector is online, but physical two-adapter verification remains blocked because the host currently enumerates only one CP2104 serial adapter and the deployed runtime is still the older single-bus release.

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
