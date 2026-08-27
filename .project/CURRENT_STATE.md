# NEXOLAB Current State

Updated: 2026-08-27

## Current Sprint

`PRODUCTION-READINESS-1` is active: production readiness and controlled acceptance.

Issue #681 state reconciliation is completed. Issue #679 is completed after real post-merge `linux/arm64` + local-auth dispatch `32832798392` passed the QEMU application-health, disconnected runtime, persistent-volume and auth-continuity gates and published a checksum-verified accepted recovery artifact for the exact deployed source lineage.

Issue #683 and #686 recovery hardening are completed, including replacement post-merge ARM64/local-auth dispatch `32939760743` for runtime source `cc27b609...`. Issue #684 Settings workspace is completed and its controlled LAN deployment remains source `a929144a2cbfa7c192e5e04cae6e02291cbef2cc`. The previously accepted recovery artifact `9584581740` remains valid evidence for `cc27b609...` but is no longer exact-source recovery authority for the currently deployed `a929144a...` lineage. Critical performance Issue #696 and hosted-runner recovery Issue #698 are completed; the refrigeration latest-value path is verified at exact head `42dafbed9952e261a182e1e24e3380419e1369a5`. Issue #707 Saved Dashboard export/chart regression is repository-verified at exact product head `1ca06521628e5936c9c00fb94ef895d6abfa1c21`. Issue #690 remains the next independent Ready Work Package.

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

- #696 replaced the refrigeration structural-snapshot history scan with the bounded `telemetry_latest` projection. Real Raspberry Pi SQL evidence improved the affected 84-channel KK2 lookup from `85874.034 ms` to `1.853 ms`; the previous #698 hosted-runner allocation blocker is cleared.
- Authorized telemetry-retention maintenance on 2026-08-26 created and checksum-verified a PostgreSQL backup before deletion. Confirmed completed cleanup is 3,784,832 old `telemetry_session_contexts` rows plus 250,000 old `telemetry_samples`, followed by `VACUUM FULL ANALYZE telemetry_session_contexts`. Full deletion of all sensor samples before 2026-08-20 was not completed and must not be reported as completed retention.

## Hardware validation backlog

- #200 — physical RS-485 topology, second adapter, Unit 115 reality, termination/bias/shielding and duplicate-ID isolation remain hardware-unverified.
- #201 — normal-operation LE-01MP semantics are accepted; controlled restart/power-cycle discontinuity evidence remains pending.
- #202 — representative XJP60D firmware/semantic portability still needs real hardware evidence.
- #585 — W2 / Unit 201 handback remains blocked until external RS-485 ownership is released and physical handback is approved.

## Security maintenance

Security reconciliation for Issue #704 has repository-side exact-head verification complete at `e2f7857e381600d76dd4100cea2c776bab8868e8`. Fresh no-cache Container Supply Chain run `33025323284` is GREEN for device-agent, telemetry-service, mqtt-dynamic-security and the aggregate release manifest; Telemetry service run `33025323323`, Core CI run `33025323332` and the NEXOLAB Merge Gate are GREEN on the same product head. Telemetry-service OpenSSL `CVE-2026-14456` exceptions remain retired; Device Agent retains only `libssl3t64/CVE-2026-14456` through **2026-08-30**. Exact Device Agent and telemetry-service SQLite decisions plus telemetry `libcjson1/CVE-2026-16554` and `libwebsockets19t64/CVE-2026-78161` remain time-bounded through **2026-09-02** with the documented reachability/version removal triggers. Issue #690 is Ready; this repository verification does not authorize or imply any runtime deployment.

## Issue #707 Saved Dashboard export and chart workspace

Repository-side software verification is complete for exact product/test head `1ca06521628e5936c9c00fb94ef895d6abfa1c21`. The persisted CSV endpoint accepts the legacy browser identifier `Europe/Kiev` through explicit canonicalization to `Europe/Kyiv` while invalid identifiers remain fail-closed. Saved Dashboard line/area series now consolidate across equipment and split only when the canonical five-axis readability budget is exceeded, preserving persisted series order; value/gauge-only dashboards do not create empty chart panels. Core CI, Telemetry service, Authenticated Dashboard Acceptance, Offline Bundle, Container Supply Chain and NEXOLAB Merge Gate are GREEN, and the fresh Codex review is clean. Generic Live Data equipment-centric grouping remains unchanged.

No #707 production/site deployment was performed. Direct operator-page inspection is currently unavailable because Opera Browser Connector is not connected; an earlier connected attempt could see the NEXOLAB private-network tabs but connector actions rejected private LAN/Tailscale page access. This limits real-runtime UI observation only and does not substitute for or invalidate the completed repository-side evidence.

## Runtime and safety boundary

Core NEXOLAB remains `LOCAL_LAN` / offline-first with no mandatory public internet, paid runtime service, CDN, remote font or external runtime API.

#679 hosted-QEMU acceptance is completed; its GREEN evidence does not authorize Raspberry Pi runtime mutation. Package authority/staging/activation, `establish-package-authority`, source→packaged transition and actual-host update/rollback remain production cutover boundaries requiring separate approval. No destructive restore, persistent-data deletion, named-volume deletion, Modbus/controller write or hardware write is authorized.
