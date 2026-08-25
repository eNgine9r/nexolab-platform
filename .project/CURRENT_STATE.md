# NEXOLAB Current State

Updated: 2026-08-24

## Current Sprint

`PRODUCTION-READINESS-1` is active: production readiness and controlled acceptance.

Issue #677 is the active Work Package. It enables a parameterized GitHub-runner path for a full `linux/arm64` offline recovery bundle, including explicit runtime-source/tooling provenance and local-auth-preserving disconnected update/rollback proof, so the production Raspberry Pi does not need to perform a resource-heavy native image build.

Issue #675 software implementation is completed. Issue #189 remains the parent recovery boundary and is blocked until #677 produces a verified ARM64 package for the controlled source lineage; staging/activation and the actual Raspberry Pi package transition remain a separate cutover approval boundary.

## Recently completed production-readiness boundaries

Issue #245 is completed with real Raspberry Pi standalone hardware evidence. Issue #444 LOCAL_LAN user administration, #646 protected `main`, #667 CVE lifecycle reconciliation and #673 state reconciliation are also completed.

## Durable baselines

Accepted hardware-validated product source: `750a5b8cba02add472f1aa7ca7a2b077e809c3c3`.

Currently deployed source: `cc27b609eea2917b97da96003a08e5c84a7edbb1` in `lan` runtime mode. Controlled LAN deployment evidence: `/home/nexolab/nexolab-platform/runtime/deployments/20260824T091838Z` with `DEPLOYMENT PASSED`.

The accepted baseline remains anchored to #245 real-hardware acceptance. Repository synchronization is not deployment or cutover.

## Issue #675 source-to-packaged authority

Software implementation adds one bounded `establish-package-authority` host command. It accepts only trusted `controlled_source_deployment` lineage and an exact host-validated staged bundle with matching source commit, platform, schema, runtime mode and local-auth boundary. It holds the worker and update-plane locks, requires capacity and a verified non-empty PostgreSQL backup, records persistent-volume identities, preserves hardware/bridge/standalone overlays, performs a rollback-aware source-to-packaged Dashboard handoff, requires exactly one Alembic head, proves the real Modbus path on the same stable RS-485 topology, and commits catalog-backed packaged authority only after volume identities remain unchanged. The packaged record carries forward hardware authority so later update/rollback operations must retain the hardware overlay and re-prove the same hardware contract.

Legacy controlled-source records may derive missing Dashboard/auth identity only from their exact immutable deployment evidence with matching source commit and runtime mode. The full version-management matrix passes 63/63; Python compile, shell syntax and `git diff --check` also pass. Exact-source runtime packaging is now decoupled from recovery tooling through digest-bound `source_commit`/`tooling_commit` provenance, and verified offline image references are activated before any Compose-based backup or post-install verification. Exact-head CI, Telemetry service, Offline Bundle and NEXOLAB Merge Gate were GREEN for the completed #675 implementation. Actual packaged installation has not been executed on the Raspberry Pi.

## Issue #677 ARM64 package staging

The controlled Raspberry Pi version-management catalog is currently empty and no full ARM64 offline archive is staged. The existing Offline Bundle CI lane proves amd64 disconnected behavior, while existing ARM64 workflows only cover partial artifacts. #677 therefore parameterizes the existing Offline Bundle workflow for a bounded `linux/arm64` dispatch with explicit runtime source ref, LOCAL_LAN Dashboard/API/WebSocket inputs, local-auth provider, QEMU runtime proof and deterministic source/tooling evidence. Ephemeral CI signing keys remain runner-local and are never part of the bundle or uploaded evidence. The production Pi runtime, catalog and services are not mutated by this Work Package.

## Issue #189 recovery boundary

Software/isolated backup-restore, real MQTT/SQLite outage replay and actual-host reboot persistence are verified. Remaining acceptance is blocked on a compatible ARM64 package staged through #677, followed by the separately approved source→packaged transition and update→rollback drill. Optional controlled power-loss evidence remains separately gated. Destructive production restore and named-volume deletion remain forbidden.

## Hardware validation backlog

- #200 — physical RS-485 topology, second adapter, Unit 115 reality, termination/bias/shielding and duplicate-ID isolation remain hardware-unverified.
- #201 — normal-operation LE-01MP semantics are accepted; controlled restart/power-cycle discontinuity evidence remains pending.
- #202 — representative XJP60D firmware/semantic portability still needs real hardware evidence.
- #585 — W2 / Unit 201 handback remains blocked until external RS-485 ownership is released and physical handback is approved.

## Security maintenance

Four exact OpenSSL QUIC `CVE-2026-14456` temporary decisions remain reviewed through **2026-08-30**. Rebuild/review again at expiry or earlier if a fixed Debian Trixie package appears, findings disappear, QUIC reachability changes or severity becomes Critical.

## Runtime and safety boundary

Core NEXOLAB remains `LOCAL_LAN` / offline-first with no mandatory public internet, paid runtime service, CDN, remote font or external runtime API.

#677 authorizes only package-build/verification work on hosted CI and no Raspberry Pi runtime mutation. Package staging/activation, source→packaged transition and update/rollback remain production cutover boundaries requiring separate approval. No destructive restore, persistent-data deletion, named-volume deletion, Modbus/controller write or hardware write is authorized.
