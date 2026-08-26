# NEXOLAB Current State

Updated: 2026-08-26

## Current Sprint

`PRODUCTION-READINESS-1` is active: production readiness and controlled acceptance.

Issue #681 state reconciliation is completed. Issue #679 is completed after real post-merge `linux/arm64` + local-auth dispatch `32832798392` passed the QEMU application-health, disconnected runtime, persistent-volume and auth-continuity gates and published a checksum-verified accepted recovery artifact for the exact deployed source lineage.

Issue #683 is merged and completed at PR #685. Issue #686 is also completed at PR #687: replacement post-merge ARM64/local-auth dispatch `32939760743` passed disconnected startup, local-auth continuity and update/rollback persistence for runtime source `cc27b609...`. Issue #684 is merged at PR #689 and its controlled LAN deployment completed successfully on source `a929144a2cbfa7c192e5e04cae6e02291cbef2cc`. The previously accepted recovery artifact `9584581740` remains valid evidence for `cc27b609...` but is no longer exact-source recovery authority for the currently deployed `a929144a...` lineage. Critical performance Issue #696 is implemented in PR #697 and locally/production-query verified, but exact-head merge is soft-blocked by GitHub hosted-runner allocation Issue #698. Issue #690 remains the next independent Ready Work Package.

## Recently completed production-readiness boundaries

Issue #245 is completed with real Raspberry Pi standalone hardware evidence. Issue #444 LOCAL_LAN user administration, #646 protected `main`, #667 CVE lifecycle reconciliation and #673 state reconciliation are also completed.

## Durable baselines

Accepted hardware-validated product source: `750a5b8cba02add472f1aa7ca7a2b077e809c3c3`.

Currently deployed source: `a929144a2cbfa7c192e5e04cae6e02291cbef2cc` in `lan` runtime mode. Controlled LAN deployment evidence: `/home/nexolab/nexolab-platform/runtime/deployments/20260826T125356Z` with `DEPLOYMENT PASSED`; `/settings` returned HTTP 200, API readiness and Device Agent health were GREEN, and telemetry continued advancing.

The accepted baseline remains anchored to #245 real-hardware acceptance. Repository synchronization is not deployment or cutover.

## Issue #675 source-to-packaged authority

Software implementation adds one bounded `establish-package-authority` host command. It accepts only trusted `controlled_source_deployment` lineage and an exact host-validated staged bundle with matching source commit, platform, schema, runtime mode and local-auth boundary. It holds the worker and update-plane locks, requires capacity and a verified non-empty PostgreSQL backup, records persistent-volume identities, preserves hardware/bridge/standalone overlays, performs a rollback-aware source-to-packaged Dashboard handoff, requires exactly one Alembic head, proves the real Modbus path on the same stable RS-485 topology, and commits catalog-backed packaged authority only after volume identities remain unchanged. The packaged record carries forward hardware authority so later update/rollback operations must retain the hardware overlay and re-prove the same hardware contract.

Legacy controlled-source records may derive missing Dashboard/auth identity only from their exact immutable deployment evidence with matching source commit and runtime mode. The full version-management matrix passes 63/63; Python compile, shell syntax and `git diff --check` also pass. Exact-source runtime packaging is now decoupled from recovery tooling through digest-bound `source_commit`/`tooling_commit` provenance, and verified offline image references are activated before any Compose-based backup or post-install verification. Exact-head CI, Telemetry service, Offline Bundle and NEXOLAB Merge Gate were GREEN for the completed #675 implementation. Actual packaged installation has not been executed on the Raspberry Pi.

## Issues #677 / #679 ARM64 package acceptance

#677 is merged and completed at PR #678. Its first real post-merge ARM64/local-auth run `32812878575` correctly failed closed on the QEMU-specific Device Agent Docker health timing gap, which was fixed by #679 without changing the pinned runtime source or native production health semantics. #679 merged at PR #680 and replacement run `32832798392` is GREEN for tooling `431f2a28a8ebf7b86536e5059b381b75d2c5b1a3`, exact deployed runtime source `cc27b609eea2917b97da96003a08e5c84a7edbb1`, `linux/arm64`, immutable LOCAL_LAN endpoints and local auth. Accepted artifact `9558305055` has GitHub/local SHA256 `25057b85a6b096275d3cadef8f03f3dfa8e608e1a3160932aec73d3a368fe74f`; the inner recovery bundle SHA256 is `587b88b53634084be89f1d1fd96c96eb77549655a6f8dbe76d57c16e8c818517`. Manifest/provenance record ARM64, runtime source `cc27b609...`, tooling `431f2a28...`, local auth, no packaged secrets, no mandatory runtime network/paid service and no volume deletion. Hosted update/rollback preserved named-volume identities and local-auth refresh/session/RBAC continuity, including rollback logout revocation.

## Issue #189 recovery boundary

Software/isolated backup-restore, real MQTT/SQLite outage replay, actual-host reboot persistence and hosted ARM64/local-auth package acceptance are verified for their recorded source lineages. The first approved actual-host package transition failed safely on #683 after backup and partial central recreation; source central, Dashboard, edge, all six persistent-volume identities and advancing telemetry were restored. #686 restored GREEN ARM64/local-auth acceptance in run `32939760743` for `cc27b609...`; because the currently deployed source is now `a929144a...`, artifact `9584581740` must not be treated as exact-source recovery authority. #189 remains blocked until recovery/package acceptance is refreshed for the current deployed source or another explicitly accepted recovery path is established. Optional power-loss evidence remains separately gated.

## Current soft blockers and operational observations

- #696 / PR #697 removes the refrigeration structural-snapshot history scan by using `telemetry_latest`. Real Raspberry Pi SQL evidence improved the affected 84-channel KK2 lookup from `85874.034 ms` to `1.853 ms`. Merge remains soft-blocked on #698 because several GitHub-hosted jobs were not acquired by a hosted runner; Capacity Release Gate subsequently completed GREEN, so runner allocation is intermittent rather than a product-code failure.
- Authorized telemetry-retention maintenance on 2026-08-26 created and checksum-verified a PostgreSQL backup before deletion. Confirmed completed cleanup is 3,784,832 old `telemetry_session_contexts` rows plus 250,000 old `telemetry_samples`, followed by `VACUUM FULL ANALYZE telemetry_session_contexts`. Full deletion of all sensor samples before 2026-08-20 was not completed and must not be reported as completed retention.

## Hardware validation backlog

- #200 — physical RS-485 topology, second adapter, Unit 115 reality, termination/bias/shielding and duplicate-ID isolation remain hardware-unverified.
- #201 — normal-operation LE-01MP semantics are accepted; controlled restart/power-cycle discontinuity evidence remains pending.
- #202 — representative XJP60D firmware/semantic portability still needs real hardware evidence.
- #585 — W2 / Unit 201 handback remains blocked until external RS-485 ownership is released and physical handback is approved.

## Security maintenance

Security maintenance is being reconciled under Issue #704. Fresh exact-head scan evidence shows telemetry-service now consumes fixed OpenSSL `3.5.7-1~deb13u2`, so its three `CVE-2026-14456` exceptions are retired. Device Agent retains only `libssl3t64/CVE-2026-14456` through **2026-08-30** while the supported distroless base still lags the fixed Debian package. Two exact Device Agent `libsqlite3-0` HIGH decisions (`CVE-2026-11822`, `CVE-2026-11824`) are reviewed through **2026-09-02** because the current runtime exposes no FTS5, arbitrary-SQL or untrusted-database import path. Remove any decision earlier when its finding disappears, a supported fix becomes consumable, reachability changes or severity becomes Critical.

## Runtime and safety boundary

Core NEXOLAB remains `LOCAL_LAN` / offline-first with no mandatory public internet, paid runtime service, CDN, remote font or external runtime API.

#679 hosted-QEMU acceptance is completed; its GREEN evidence does not authorize Raspberry Pi runtime mutation. Package authority/staging/activation, `establish-package-authority`, source→packaged transition and actual-host update/rollback remain production cutover boundaries requiring separate approval. No destructive restore, persistent-data deletion, named-volume deletion, Modbus/controller write or hardware write is authorized.
