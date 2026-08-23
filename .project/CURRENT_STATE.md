# NEXOLAB Current State

Updated: 2026-08-23

## Current Sprint

`PRODUCTION-READINESS-1` is active: production readiness and controlled acceptance.

Issue #665 / PR #666 is completed with the state-only fast lane proven again. Issue #667 is the active focused security-maintenance Work Package: reconcile the stale current-decision CVE date with the already accepted #660/#661 Stage 2 decision through 2026-08-30.

Next critical validation target after #667: Issue #444 — **Restore LOCAL_LAN user administration API availability**.

## Completed chart boundary

Issue #415 / PR #662 is merged with GREEN Core, Authenticated Dashboard, Refrigeration Browser, Offline Bundle and NEXOLAB Merge Gate evidence.

Issue #663 / PR #664 is merged. Exact head `f7bf4e7351353b88ead4f8d194443e416ef3c435` passed Core Quality/Build, Authenticated Dashboard Acceptance, Acquisition Scale Acceptance and NEXOLAB Merge Gate. Canonical chart changes now automatically route into authenticated dashboard acceptance.

## Durable baselines

Accepted product source: `286a219611f95413b5580d8099a7c5665416d1ad`.

Deployed product source: `6e387485b68fb862d9f82ae7f6000b1f5b672764`.

The Raspberry Pi Git checkout may be synchronized with current `main`; repository synchronization is not deployment or cutover.

## Issue #444 validation boundary

Current Raspberry Pi LAN runtime has `AUTH_MODE=jwt` and `NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER=local`. Telemetry/PostgreSQL/MQTT/MinIO containers are healthy. The LAN-bound Telemetry API returns HTTP 200 from `/health/ready`; unauthenticated `/api/v1/admin/users` reaches the organization/auth guard rather than 404.

Remaining #444 acceptance is functional operator evidence only: create/manage a local user through the authenticated path, prove that account can authenticate, and prove a non-admin receives HTTP 403 for user administration. No password/token will be requested or exposed in chat, and database bypass is not acceptance.

Opera Browser Connector was unavailable during the audit, so authenticated operator interaction remains pending.

## Issue #245 standalone boundary

Standalone runtime software is already merged and software-verified. The previous actual-host central-service health blocker is not present in the current LAN runtime, but the deployment script has no dry-run/preflight-only mode.

The next meaningful #245 action changes runtime mode to `standalone`, then requires Ethernet/Wi-Fi isolation and reboot. That remains an explicit production/network cutover boundary and is not authorized by repository state.

## Issue #189 recovery boundary

Software/isolated backup and restore contracts are already verified. Real edge MQTT outage/SQLite outbox replay evidence is also recorded. Remaining #189 acceptance is actual-host reboot, update/rollback drill and optional controlled power-loss evidence; destructive production restore and named-volume deletion remain forbidden.

## Hardware validation backlog

- #200 — physical RS-485 topology, second adapter, Unit 115 reality, termination/bias/shielding and duplicate-ID isolation remain hardware-unverified.
- #201 — LE-01MP cumulative energy software/normal-operation evidence is accepted; controlled restart/power-cycle evidence remains pending.
- #202 — representative XJP60D firmware/semantic portability still needs real hardware evidence.
- #585 — W2 / Unit 201 handback remains blocked until external RS-485 ownership is released and physical handback is approved.
- #646 — completed. GitHub `main` is protected; `NEXOLAB Merge Gate` is required, pull requests are required with zero mandatory approvals, force pushes/deletions are disabled, and controlled admin recovery remains available.

## Security maintenance

Four exact OpenSSL QUIC `CVE-2026-14456` temporary decisions remain reviewed through **2026-08-30**. Debian Trixie still exposes OpenSSL `3.5.6-1~deb13u2` as vulnerable/postponed; upstream fixes the affected 3.5 line in 3.5.8. Issue #667 aligns the stale **Current decision** sentence with that already accepted Stage 2 date; the Stage 1 2026-08-26 statement remains historical evidence, not the current expiry.

## Runtime and safety boundary

Core NEXOLAB remains `LOCAL_LAN` / offline-first with no mandatory public internet, paid service, CDN, remote font or external runtime API.

No Modbus/controller write, hardware write, product persistent-data deletion, named-volume deletion, secret exposure, DNS/billing mutation, production deployment, network isolation or reboot is authorized by Issue #667.
