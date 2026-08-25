# NEXOLAB Blockers

Updated: 2026-08-25

## Issue #189 — actual-host recovery acceptance

Backup/isolated restore, MQTT/SQLite outage replay, reboot persistence and hosted ARM64/local-auth package acceptance are verified. #679 is complete: run `32832798392` published checksum-verified accepted artifact `9558305055` for deployed source `cc27b609...`, with preserved volume identities and auth continuity through update/rollback under QEMU. The remaining actual-host update→rollback drill is blocked only on separate Product Owner approval for Raspberry Pi package authority/staging/activation, `establish-package-authority` and source→packaged transition. Any power-loss drill remains separately approved. No destructive restore over production and no named-volume deletion are authorized.

## Issue #200 — physical RS-485 topology

Passive evidence confirms one CP2104 adapter and one current production bus. Full acceptance still requires physical topology inspection and/or the intended second isolated adapter. Unit 115, duplicate IDs, termination, biasing, shielding and grounding remain unverified.

## Issue #201 — LE-01MP cumulative energy

Normal-operation semantics are accepted. Controlled restart/power-cycle discontinuity evidence remains pending; an unplanned hard reset cannot be reclassified as approved evidence.

## Issue #202 — XJP60D portability

Representative KK1/KK2 physical evidence, Unit 115 resolution and extended semantics still require real hardware evidence. Unconfirmed fields remain unmapped.

## Issue #585 — W2 / Unit 201 handback

Blocked until the Product Owner confirms the temporary external RS-485 owner has released W2 and approves any required physical handback/reconnection.

## Security maintenance — CVE-2026-14456

Four exact reviewed HIGH/no-fix decisions are retained through **2026-08-30**. Rebuild/review at expiry or earlier if a fixed Trixie package appears, findings disappear, QUIC reachability changes or severity becomes Critical.

## Cleared boundaries

- #444 LOCAL_LAN user administration — completed.
- #646 main branch protection — completed; `main` requires `NEXOLAB Merge Gate`.
- #667 CVE lifecycle date reconciliation — completed and merged.
- #245 standalone offline Raspberry Pi acceptance — completed on real hardware.
- #673 production-readiness state reconciliation — completed and merged.
- #675 source-to-packaged authority tooling — completed with exact-head review and required GREEN workflows.
- #679 ARM64 QEMU package acceptance — completed with GREEN post-merge ARM64/local-auth run `32832798392` and independently verified artifact/provenance.

## Safety boundaries

No blocker may be bypassed by Modbus/controller write, hardware write, production/site cutover without approval, persistent-data deletion, named-volume deletion, secret exposure or mandatory cloud dependency.
