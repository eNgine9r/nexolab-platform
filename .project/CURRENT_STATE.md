# NEXOLAB Current State

Updated: 2026-08-23

## Current Sprint

`PRODUCTION-READINESS-1` is active: production readiness and controlled acceptance.

Issue #669 is the active state-continuity Work Package. It reconciles completed #667 security maintenance and final #444 LOCAL_LAN user-administration acceptance.

Next critical validation target: Issue #245 — **Support standalone offline Raspberry Pi 5 monitoring over loopback**.

## Recently completed production-readiness boundaries

Issue #444 is completed. Actual Raspberry Pi LOCAL_LAN evidence proves administrator user creation (`201 Created`) and created non-admin local login (`200 OK`); prior controlled runtime evidence proves administrator list access (`200`), and the merged backend authorization contract enforces non-admin `/api/v1/admin/users` as `403 permission_denied`. No credential was extracted or logged.

Issue #667 / PR #668 is completed. Exact head `eee92a0e9b0e33c6d19a498046894b8319689117` passed Core Quality/Build, Telemetry Service and `NEXOLAB Merge Gate`; the current CVE decision now consistently points to 2026-08-30 while Stage 1 history remains intact.

Issue #646 is completed. GitHub `main` is protected with required `NEXOLAB Merge Gate`, pull-request enforcement with zero mandatory approvals, force pushes/deletions disabled, and controlled admin recovery preserved.

## Durable baselines

Accepted product source: `286a219611f95413b5580d8099a7c5665416d1ad`.

Deployed product source: `6e387485b68fb862d9f82ae7f6000b1f5b672764`.

The Raspberry Pi Git checkout may be synchronized with current `main`; repository synchronization is not deployment or cutover.

## Issue #245 standalone boundary

Standalone runtime software is already merged and software-verified. Current LAN runtime health is good and the previous central-service startup blocker is no longer present.

The next meaningful action changes runtime mode to `standalone`, then requires Ethernet/Wi-Fi isolation, no default route, loopback browser verification, Telemetry Service restart and reboot evidence. The deployment script has no dry-run/preflight-only mode.

Therefore #245 remains `needs_validation`. Production/network cutover and reboot are not authorized by repository state and require explicit Product Owner approval immediately before execution.

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

No Modbus/controller write, hardware write, product persistent-data deletion, named-volume deletion, secret exposure, DNS/billing mutation, production deployment, network isolation or reboot is authorized by Issue #669.
