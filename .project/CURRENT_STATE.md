# NEXOLAB Current State

Updated: 2026-08-24

## Current Sprint

`PRODUCTION-READINESS-1` is active: production readiness and controlled acceptance.

Issue #675 is the active Work Package. It implements a fail-closed transition from a verified controlled source deployment to exact staged packaged-release authority so the remaining #189 update/rollback recovery drill can be executed through the normal version-management safety gates.

Issue #189 remains the parent recovery boundary and is blocked until #675 software verification is GREEN and the subsequent actual Raspberry Pi package transition receives separate cutover approval.

## Recently completed production-readiness boundaries

Issue #245 is completed with real Raspberry Pi standalone hardware evidence. Issue #444 LOCAL_LAN user administration, #646 protected `main`, #667 CVE lifecycle reconciliation and #673 state reconciliation are also completed.

## Durable baselines

Accepted hardware-validated product source: `750a5b8cba02add472f1aa7ca7a2b077e809c3c3`.

Currently deployed source: `cc27b609eea2917b97da96003a08e5c84a7edbb1` in `lan` runtime mode. Controlled LAN deployment evidence: `/home/nexolab/nexolab-platform/runtime/deployments/20260824T091838Z` with `DEPLOYMENT PASSED`.

The accepted baseline remains anchored to #245 real-hardware acceptance. Repository synchronization is not deployment or cutover.

## Issue #675 source-to-packaged authority

Software implementation adds one bounded `establish-package-authority` host command. It accepts only trusted `controlled_source_deployment` lineage and an exact host-validated staged bundle with matching source commit, platform, schema, runtime mode and local-auth boundary. It holds the worker and update-plane locks, requires capacity and a verified non-empty PostgreSQL backup, records persistent-volume identities, preserves hardware/bridge/standalone overlays, performs a rollback-aware source-to-packaged Dashboard handoff, requires exactly one Alembic head, proves the real Modbus path on the same stable RS-485 topology, and commits catalog-backed packaged authority only after volume identities remain unchanged. The packaged record carries forward hardware authority so later update/rollback operations must retain the hardware overlay and re-prove the same hardware contract.

Legacy controlled-source records may derive missing Dashboard/auth identity only from their exact immutable deployment evidence with matching source commit and runtime mode. The full version-management matrix passes 63/63; Python compile, shell syntax and `git diff --check` also pass. Exact-source runtime packaging is now decoupled from recovery tooling through digest-bound `source_commit`/`tooling_commit` provenance, and verified offline image references are activated before any Compose-based backup or post-install verification. Actual packaged installation has not been executed on the Raspberry Pi in #675 and remains a separate approved cutover after software merge.

## Issue #189 recovery boundary

Software/isolated backup-restore, real MQTT/SQLite outage replay and actual-host reboot persistence are verified. Remaining acceptance is the packaged update→rollback drill enabled by #675; optional controlled power-loss evidence remains separately gated. Destructive production restore and named-volume deletion remain forbidden.

## Hardware validation backlog

- #200 — physical RS-485 topology, second adapter, Unit 115 reality, termination/bias/shielding and duplicate-ID isolation remain hardware-unverified.
- #201 — normal-operation LE-01MP semantics are accepted; controlled restart/power-cycle discontinuity evidence remains pending.
- #202 — representative XJP60D firmware/semantic portability still needs real hardware evidence.
- #585 — W2 / Unit 201 handback remains blocked until external RS-485 ownership is released and physical handback is approved.

## Security maintenance

Four exact OpenSSL QUIC `CVE-2026-14456` temporary decisions remain reviewed through **2026-08-30**. Rebuild/review again at expiry or earlier if a fixed Debian Trixie package appears, findings disappear, QUIC reachability changes or severity becomes Critical.

## Runtime and safety boundary

Core NEXOLAB remains `LOCAL_LAN` / offline-first with no mandatory public internet, paid runtime service, CDN, remote font or external runtime API.

#675 software work authorizes no actual packaged reinstall. The subsequent package transition/update/rollback is a production cutover boundary requiring separate approval. No destructive restore, persistent-data deletion, named-volume deletion, Modbus/controller write or hardware write is authorized.
