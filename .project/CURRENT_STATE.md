# NEXOLAB Current State

Updated: 2026-08-24

## Current Sprint

`PRODUCTION-READINESS-1` is active: production readiness and controlled acceptance.

Issue #673 is the active state-continuity Work Package. It records completed real Raspberry Pi hardware acceptance for #245 and advances production readiness to #189.

Next recovery boundary: Issue #189 — **Prove backup, restore, rollback and power-loss recovery**.

## Recently completed production-readiness boundaries

Issue #444 is completed. Actual Raspberry Pi LOCAL_LAN evidence proves administrator user creation (`201 Created`) and created non-admin local login (`200 OK`); prior controlled runtime evidence proves administrator list access (`200`), and the merged backend authorization contract enforces non-admin `/api/v1/admin/users` as `403 permission_denied`. No credential was extracted or logged.

Issue #667 / PR #668 is completed. Exact head `eee92a0e9b0e33c6d19a498046894b8319689117` passed Core Quality/Build, Telemetry Service and `NEXOLAB Merge Gate`; the current CVE decision now consistently points to 2026-08-30 while Stage 1 history remains intact.

Issue #646 is completed. GitHub `main` is protected with required `NEXOLAB Merge Gate`, pull-request enforcement with zero mandatory approvals, force pushes/deletions disabled, and controlled admin recovery preserved.

## Durable baselines

Accepted product source: `750a5b8cba02add472f1aa7ca7a2b077e809c3c3`.

Deployed product source: `750a5b8cba02add472f1aa7ca7a2b077e809c3c3`.

The Raspberry Pi Git checkout may be synchronized with current `main`; repository synchronization is not deployment or cutover.

## Issue #245 standalone acceptance

Issue #245 is completed with real Raspberry Pi evidence anchored to `750a5b8cba02add472f1aa7ca7a2b077e809c3c3`. The controlled standalone run proved physical Ethernet carrier loss, Wi-Fi disabled, no default route, loopback Dashboard/API/Device Agent readiness, authenticated offline verification, 15 minutes of advancing telemetry, Telemetry Service restart recovery, a second offline reboot, preserved named-volume identities, migration success and post-reboot telemetry progression.

Evidence: `/home/nexolab/nexolab-platform/runtime/evidence/standalone-offline-acceptance-20260824T065756Z` completed at `2026-08-24T10:17:49+03:00`. Ethernet was then restored and all core services returned healthy.

## Issue #189 recovery boundary

Software/isolated backup-restore and real MQTT/SQLite outage recovery are verified. Remaining acceptance requires actual-host reboot, update/rollback drill and optional controlled power-loss evidence. Destructive production restore and named-volume deletion remain forbidden.

## Hardware validation backlog

- #200 — physical RS-485 topology, second adapter, Unit 115 reality, termination/bias/shielding and duplicate-ID isolation remain hardware-unverified.
- #201 — normal-operation LE-01MP semantics are accepted; controlled restart/power-cycle discontinuity evidence remains pending.
- #202 — representative XJP60D firmware/semantic portability still needs real hardware evidence.
- #585 — W2 / Unit 201 handback remains blocked until external RS-485 ownership is released and physical handback is approved.

## Security maintenance

Four exact OpenSSL QUIC `CVE-2026-14456` temporary decisions remain reviewed through **2026-08-30**. Rebuild/review again at expiry or earlier if a fixed Debian Trixie package appears, findings disappear, QUIC reachability changes or severity becomes Critical.

## Runtime and safety boundary

Core NEXOLAB remains `LOCAL_LAN` / offline-first with no mandatory public internet, paid runtime service, CDN, remote font or external runtime API.

Issue #673 is state-only and authorizes no runtime mutation. #189 remains blocked on controlled reboot/update-rollback and optional power-loss actions; no destructive restore, persistent-data deletion, named-volume deletion, Modbus/controller write or hardware write is authorized.
