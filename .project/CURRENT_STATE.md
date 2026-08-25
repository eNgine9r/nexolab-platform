# NEXOLAB Current State

Updated: 2026-08-25

## Current Sprint

`PRODUCTION-READINESS-1` is active: production readiness and controlled acceptance.

Issue #679 is the active Work Package. A real post-merge `linux/arm64` + local-auth dispatch proved bundle construction, QEMU registration, clean-host transfer and central disconnected startup, then failed only because the emulated Device Agent Docker health probe became `unhealthy` while the process remained running. #679 makes hosted QEMU acceptance use a bounded application `/health` proof without weakening native production health semantics.

Issues #675 and #677 software implementation are completed. Issue #189 remains the parent recovery boundary and is blocked until #679 fixes the QEMU acceptance gate and a real ARM64/local-auth dispatch publishes a fully accepted package for the controlled source lineage; staging/activation and the actual Raspberry Pi package transition remain a separate cutover approval boundary.

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

#677 is merged and completed at PR #678. The real post-merge dispatch `32812878575` used tooling `f9c7165b63bed6aa25e3a105bb5ea8e6d40a7d9e`, exact deployed runtime source `cc27b609eea2917b97da96003a08e5c84a7edbb1`, `linux/arm64`, the immutable LOCAL_LAN endpoints and local auth. It successfully built and checksum-verified the ARM64 bundle, simulated a clean transferred host, blocked egress and started the full central stack under QEMU. The edge MQTT became healthy and the Device Agent process stayed running with exit code 0, but its emulated in-container Python healthcheck became `unhealthy`, so accepted artifact publication correctly failed closed. Native ARM64 Pi evidence shows the same production healthcheck repeatedly succeeds, and Device Agent runtime source files are unchanged across the deployed source/tooling boundary. #679 is the focused tooling defect that must prove the actual application `/health` endpoint under QEMU while preserving native production `--wait` behavior.

## Issue #189 recovery boundary

Software/isolated backup-restore, real MQTT/SQLite outage replay and actual-host reboot persistence are verified. Remaining acceptance is blocked on #679 and then a fully GREEN ARM64/local-auth package dispatch for exact deployed source lineage. Package staging, `establish-package-authority`, source→packaged transition and the actual Raspberry Pi update→rollback drill remain separately approved runtime actions. Optional controlled power-loss evidence remains separately gated. Destructive production restore and named-volume deletion remain forbidden.

## Hardware validation backlog

- #200 — physical RS-485 topology, second adapter, Unit 115 reality, termination/bias/shielding and duplicate-ID isolation remain hardware-unverified.
- #201 — normal-operation LE-01MP semantics are accepted; controlled restart/power-cycle discontinuity evidence remains pending.
- #202 — representative XJP60D firmware/semantic portability still needs real hardware evidence.
- #585 — W2 / Unit 201 handback remains blocked until external RS-485 ownership is released and physical handback is approved.

## Security maintenance

Four exact OpenSSL QUIC `CVE-2026-14456` temporary decisions remain reviewed through **2026-08-30**. Rebuild/review again at expiry or earlier if a fixed Debian Trixie package appears, findings disappear, QUIC reachability changes or severity becomes Critical.

## Runtime and safety boundary

Core NEXOLAB remains `LOCAL_LAN` / offline-first with no mandatory public internet, paid runtime service, CDN, remote font or external runtime API.

#679 authorizes only hosted-QEMU acceptance tooling and verification; it does not authorize Raspberry Pi runtime mutation. Package staging/activation, `establish-package-authority`, source→packaged transition and update/rollback remain production cutover boundaries requiring separate approval. No destructive restore, persistent-data deletion, named-volume deletion, Modbus/controller write or hardware write is authorized.
