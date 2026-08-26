# NEXOLAB Current State

Updated: 2026-08-26

## Current Sprint

`PRODUCTION-READINESS-1` is active: production readiness and controlled acceptance.

Issue #681 state reconciliation is completed. Issue #679 is completed after real post-merge `linux/arm64` + local-auth dispatch `32832798392` passed the QEMU application-health, disconnected runtime, persistent-volume and auth-continuity gates and published a checksum-verified accepted recovery artifact for the exact deployed source lineage.

Issue #683 is merged and completed at PR #685. Issue #686 is also completed at PR #687: replacement post-merge ARM64/local-auth dispatch `32939760743` passed disconnected startup, local-auth continuity, update/rollback persistent-data preservation and published accepted artifact `9584581740` for deployed runtime source `cc27b609...`. Issue #189 now remains blocked only on controlled re-staging of that accepted artifact and the separately governed actual-host recovery/cutover boundary. Issue #684 has completed implementation and exact-head verification in PR #689; the next Ready Work Package is Issue #690, which makes PR verification risk-aware and path-targeted without weakening safety gates.

## Recently completed production-readiness boundaries

Issue #245 is completed with real Raspberry Pi standalone hardware evidence. Issue #444 LOCAL_LAN user administration, #646 protected `main`, #667 CVE lifecycle reconciliation and #673 state reconciliation are also completed.

## Durable baselines

Accepted hardware-validated product source: `750a5b8cba02add472f1aa7ca7a2b077e809c3c3`.

Currently deployed source: `cc27b609eea2917b97da96003a08e5c84a7edbb1` in `lan` runtime mode. Controlled LAN deployment evidence: `/home/nexolab/nexolab-platform/runtime/deployments/20260824T091838Z` with `DEPLOYMENT PASSED`.

The accepted baseline remains anchored to #245 real-hardware acceptance. Repository synchronization is not deployment or cutover.

## Issue #675 source-to-packaged authority

Software implementation adds one bounded `establish-package-authority` host command. It accepts only trusted `controlled_source_deployment` lineage and an exact host-validated staged bundle with matching source commit, platform, schema, runtime mode and local-auth boundary. It holds the worker and update-plane locks, requires capacity and a verified non-empty PostgreSQL backup, records persistent-volume identities, preserves hardware/bridge/standalone overlays, performs a rollback-aware source-to-packaged Dashboard handoff, requires exactly one Alembic head, proves the real Modbus path on the same stable RS-485 topology, and commits catalog-backed packaged authority only after volume identities remain unchanged. The packaged record carries forward hardware authority so later update/rollback operations must retain the hardware overlay and re-prove the same hardware contract.

Legacy controlled-source records may derive missing Dashboard/auth identity only from their exact immutable deployment evidence with matching source commit and runtime mode. The full version-management matrix passes 63/63; Python compile, shell syntax and `git diff --check` also pass. Exact-source runtime packaging is now decoupled from recovery tooling through digest-bound `source_commit`/`tooling_commit` provenance, and verified offline image references are activated before any Compose-based backup or post-install verification. Exact-head CI, Telemetry service, Offline Bundle and NEXOLAB Merge Gate were GREEN for the completed #675 implementation. Actual packaged installation has not been executed on the Raspberry Pi.

## Issues #677 / #679 ARM64 package acceptance

#677 is merged and completed at PR #678. Its first real post-merge ARM64/local-auth run `32812878575` correctly failed closed on the QEMU-specific Device Agent Docker health timing gap, which was fixed by #679 without changing the pinned runtime source or native production health semantics. #679 merged at PR #680 and replacement run `32832798392` is GREEN for tooling `431f2a28a8ebf7b86536e5059b381b75d2c5b1a3`, exact deployed runtime source `cc27b609eea2917b97da96003a08e5c84a7edbb1`, `linux/arm64`, immutable LOCAL_LAN endpoints and local auth. Accepted artifact `9558305055` has GitHub/local SHA256 `25057b85a6b096275d3cadef8f03f3dfa8e608e1a3160932aec73d3a368fe74f`; the inner recovery bundle SHA256 is `587b88b53634084be89f1d1fd96c96eb77549655a6f8dbe76d57c16e8c818517`. Manifest/provenance record ARM64, runtime source `cc27b609...`, tooling `431f2a28...`, local auth, no packaged secrets, no mandatory runtime network/paid service and no volume deletion. Hosted update/rollback preserved named-volume identities and local-auth refresh/session/RBAC continuity, including rollback logout revocation.

## Issue #189 recovery boundary

Software/isolated backup-restore, real MQTT/SQLite outage replay, actual-host reboot persistence and hosted ARM64/local-auth package acceptance are verified. The first approved actual-host package transition failed safely on #683 after backup and partial central recreation; source central, Dashboard, edge, all six persistent-volume identities and advancing telemetry were restored. #686 restored GREEN ARM64/local-auth acceptance in run `32939760743`; #189 remains blocked on controlled re-staging of accepted artifact `9584581740` before the actual-host recovery drill resumes. Optional power-loss evidence remains separately gated.

## Hardware validation backlog

- #200 — physical RS-485 topology, second adapter, Unit 115 reality, termination/bias/shielding and duplicate-ID isolation remain hardware-unverified.
- #201 — normal-operation LE-01MP semantics are accepted; controlled restart/power-cycle discontinuity evidence remains pending.
- #202 — representative XJP60D firmware/semantic portability still needs real hardware evidence.
- #585 — W2 / Unit 201 handback remains blocked until external RS-485 ownership is released and physical handback is approved.

## Security maintenance

Four exact OpenSSL QUIC `CVE-2026-14456` temporary decisions remain reviewed through **2026-08-30**. Rebuild/review again at expiry or earlier if a fixed Debian Trixie package appears, findings disappear, QUIC reachability changes or severity becomes Critical.

## Runtime and safety boundary

Core NEXOLAB remains `LOCAL_LAN` / offline-first with no mandatory public internet, paid runtime service, CDN, remote font or external runtime API.

#679 hosted-QEMU acceptance is completed; its GREEN evidence does not authorize Raspberry Pi runtime mutation. Package authority/staging/activation, `establish-package-authority`, source→packaged transition and actual-host update/rollback remain production cutover boundaries requiring separate approval. No destructive restore, persistent-data deletion, named-volume deletion, Modbus/controller write or hardware write is authorized.
