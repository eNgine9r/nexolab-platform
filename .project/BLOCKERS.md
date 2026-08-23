# NEXOLAB Blockers

Updated: 2026-08-23

## Issue #667 — CVE lifecycle reconciliation

No hard implementation blocker. This Work Package only aligns the stale current-decision expiry sentence with the already accepted #660/#661 Stage 2 date of 2026-08-30 and updates project continuity. It does not renew or broaden an exception.

## Issue #444 — LOCAL_LAN user administration validation

Software and runtime route availability are verified. Current LAN runtime uses local JWT auth, `/health/ready` returns 200, and `/api/v1/admin/users` reaches the organization/auth guard rather than 404.

Remaining acceptance requires an authenticated administrator operator flow:

- create/manage a local test user;
- authenticate as that user;
- verify non-admin user-management access is HTTP 403;
- verify the operator-facing diagnostic where applicable.

No secret may be copied into chat/logs. Opera Browser Connector was not connected during the 2026-08-23 audit, so this remains a credential/operator-interaction boundary, not a software defect.

## Issue #245 — standalone offline Raspberry Pi validation

Standalone software is verified. Current LAN services are healthy, but the deployment script has no dry-run/preflight-only mode.

Final acceptance requires a controlled runtime-mode change, Ethernet/Wi-Fi isolation, no default route, reboot, loopback browser verification, Telemetry Service restart and another reboot. This is a production/network cutover boundary and requires explicit Product Owner approval before execution.

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

## Issue #646 — completed main branch protection

The settings-access blocker is cleared. GitHub `main` is protected with required `NEXOLAB Merge Gate`, pull-request enforcement with zero mandatory approvals, force pushes/deletions disabled, and `enforce_admins=false` for controlled administrative recovery.

## Security maintenance — CVE-2026-14456

Four exact reviewed HIGH/no-fix decisions are retained through **2026-08-30**. Debian Trixie still reports OpenSSL 3.5.6 vulnerable/postponed and upstream fixes the affected 3.5 line in 3.5.8. Rebuild/review again at expiry or earlier if a fixed Trixie package appears, the findings disappear, QUIC reachability changes or severity becomes Critical.

Issue #667 corrects the stale **Current decision** sentence to 2026-08-30. The separate Stage 1 statement that the entries still expired on 2026-08-26 at that earlier stage remains historical evidence and must not be rewritten as if Stage 1 had already renewed the decision.

## Safety boundaries

No blocker may be bypassed by Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret exposure or mandatory cloud dependency.
