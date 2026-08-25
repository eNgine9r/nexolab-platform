# NEXOLAB Blockers

Updated: 2026-08-25

## Issue #679 — ARM64 QEMU Device Agent acceptance

The first real ARM64/local-auth dispatch (`32812878575`) failed closed after successful bundle build, clean-host transfer, egress block and central startup because the Device Agent process remained running but its in-container Python Docker healthcheck became unhealthy under amd64→arm64 QEMU. Native ARM64 Pi health evidence is GREEN and the runtime source is intentionally pinned, so #679 is the active software blocker: use an explicit bounded application `/health` proof only for QEMU acceptance, preserve native production `docker compose --wait`, and improve failed health diagnostics.

## Issue #189 — actual-host recovery acceptance

Backup/isolated restore, MQTT/SQLite outage replay and reboot persistence are verified. #675 authority tooling and #677 hosted ARM64 staging implementation are complete. The remaining update→rollback drill is blocked until #679 is GREEN and a real ARM64/local-auth dispatch publishes a fully accepted package for deployed source `cc27b609...`. Staging/activation, `establish-package-authority`, update/rollback and any power-loss drill remain separately approved runtime actions. No destructive restore over production and no named-volume deletion are authorized.

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
