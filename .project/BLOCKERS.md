# NEXOLAB Blockers

Updated: 2026-08-24

## Issue #677 — ARM64 offline package staging

No implementation blocker. The current controlled Pi has an empty version-management catalog and no full ARM64 bundle, while native Docker bundle construction on the 4 GiB production Pi is an avoidable stability risk. #677 is the active software prerequisite: build and fully validate the ARM64/local-auth package on a hosted GitHub runner without mutating the Pi.

## Issue #189 — actual-host recovery acceptance

Backup/isolated restore, MQTT/SQLite outage replay and reboot persistence are verified. #675 software authority transition is complete. The remaining update→rollback drill is blocked until #677 produces a compatible ARM64 package for the deployed source lineage and that package is staged for the controlled Pi. Staging/activation, `establish-package-authority`, update/rollback and any power-loss drill remain separately approved runtime actions. No destructive restore over production and no named-volume deletion are authorized.

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

## Safety boundaries

No blocker may be bypassed by Modbus/controller write, hardware write, production/site cutover without approval, persistent-data deletion, named-volume deletion, secret exposure or mandatory cloud dependency.
