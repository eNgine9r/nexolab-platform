# NEXOLAB Blockers

Updated: 2026-08-23

## Issue #669 — state reconciliation

No hard implementation blocker. This Work Package is state-only and must not change runtime, deployment, credentials, networking or hardware.

## Issue #245 — standalone offline Raspberry Pi validation

Standalone software is verified and current LAN services are healthy. The deployment script has no dry-run/preflight-only mode.

Final acceptance requires a controlled runtime-mode change to `standalone`, Ethernet/Wi-Fi isolation, no default route, loopback browser verification, Telemetry Service restart and reboot evidence.

This is a production/network cutover boundary. Explicit Product Owner approval is required before the first runtime mutation or network/reboot action.

## Issue #189 — actual-host recovery acceptance

Software/isolated backup-restore and real MQTT/SQLite outage replay are verified. Remaining evidence requires controlled central/Pi reboot, actual update/rollback drill and optional power-loss testing. No destructive restore over production and no named-volume deletion are authorized.

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

- #444 LOCAL_LAN user administration — completed with actual operator create/login evidence plus merged non-admin 403 authorization contract.
- #646 main branch protection — completed; `main` is protected and requires `NEXOLAB Merge Gate`.
- #667 CVE lifecycle date reconciliation — completed and merged.

## Safety boundaries

No blocker may be bypassed by Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret exposure or mandatory cloud dependency.
