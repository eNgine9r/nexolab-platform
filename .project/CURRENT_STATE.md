# NEXOLAB Current State

Updated: 2026-08-27

## Current Sprint

`PRODUCTION-READINESS-1` is active: production readiness and controlled acceptance.

Issue #704 / PR #705 is merged and completed. Issue #698 is resolved after fresh GitHub-hosted runner allocation recovered and the exact-head #697 verification matrix completed GREEN. Critical refrigeration performance Issue #696 / PR #697 is merged, deployed and completed on the real Raspberry Pi. The current next independent Ready Work Package is Issue #690 — risk-aware and path-targeted PR verification.

## Recently completed production-readiness boundaries

Issue #245 is completed with real Raspberry Pi standalone hardware evidence. Issue #444 LOCAL_LAN user administration, #646 protected `main`, #667 CVE lifecycle reconciliation, #673 state reconciliation, #684 Settings workspace, #704 security reconciliation and #696 refrigeration structural-latency optimization are completed.

## Durable baselines

Accepted product/runtime source: `a389a69d00a92380bce49930750bc5a99d992bde`.

Currently deployed source: `a389a69d00a92380bce49930750bc5a99d992bde` in `lan` runtime mode. Controlled LAN deployment evidence: `/home/nexolab/nexolab-platform/runtime/deployments/20260827T054754Z` with `DEPLOYMENT PASSED`. Post-activation readiness passed for Telemetry Service, Device Agent, Dashboard, Prometheus, Alertmanager, Grafana and MinIO; the central smoke gate and API-contract verification also passed.

The latest exact real-hardware acceptance lineage for the standalone acquisition/restart boundary remains Issue #245 at `750a5b8cba02add472f1aa7ca7a2b077e809c3c3`. This hardware evidence is distinct from the accepted/deployed product baseline. Repository synchronization is not deployment or cutover.

## Issue #696 refrigeration structural latency

PR #697 replaced the climate-chamber structural snapshot latest-value history scan with the bounded `telemetry_latest` projection while retaining canonical channel/binding/value/quality/timestamp semantics and the legacy fallback path. Exact-head required workflows completed GREEN before merge.

Real Raspberry Pi production evidence for `Cool jet` (`7d98aa06-2942-4b2a-b124-1278d8339eb3`) after deployment on `a389a69d...`:

- 84 configured channels;
- cold authenticated structural snapshot: `0.067 s` — target `< 1.0 s` PASS;
- warm requests: `0.049–0.078 s`, average `0.059 s`;
- structural response: layout revision `4`, 1 placement, 1 binding, 9 known and 75 unknown latest sample states;
- telemetry advanced during the acceptance interval;
- local login/logout passed;
- Product Owner confirmed the real production UI is fast.

The original production SQL bottleneck was `85874.034 ms`; the bounded latest-projection SQL core measured `1.853 ms` before deployment. No history deletion, acquisition-cadence change, Modbus write or hardware write was part of #696.

## Issue #675 source-to-packaged authority

Software implementation adds one bounded `establish-package-authority` host command. It accepts only trusted `controlled_source_deployment` lineage and an exact host-validated staged bundle with matching source commit, platform, schema, runtime mode and local-auth boundary. It holds the worker and update-plane locks, requires capacity and a verified non-empty PostgreSQL backup, records persistent-volume identities, preserves hardware/bridge/standalone overlays, performs a rollback-aware source-to-packaged Dashboard handoff, requires exactly one Alembic head, proves the real Modbus path on the same stable RS-485 topology, and commits catalog-backed packaged authority only after volume identities remain unchanged. The packaged record carries forward hardware authority so later update/rollback operations must retain the hardware overlay and re-prove the same hardware contract.

Legacy controlled-source records may derive missing Dashboard/auth identity only from their exact immutable deployment evidence with matching source commit and runtime mode. The full version-management matrix passes 63/63; Python compile, shell syntax and `git diff --check` also pass. Exact-source runtime packaging is decoupled from recovery tooling through digest-bound `source_commit`/`tooling_commit` provenance, and verified offline image references are activated before Compose-based backup or post-install verification. Actual packaged installation has not been executed on the Raspberry Pi.

## Issues #677 / #679 ARM64 package acceptance

#677 is merged and completed at PR #678. #679 merged at PR #680 and replacement run `32832798392` is GREEN for tooling `431f2a28a8ebf7b86536e5059b381b75d2c5b1a3`, runtime source `cc27b609eea2917b97da96003a08e5c84a7edbb1`, `linux/arm64`, immutable LOCAL_LAN endpoints and local auth. Accepted artifact `9558305055` has GitHub/local SHA256 `25057b85a6b096275d3cadef8f03f3dfa8e608e1a3160932aec73d3a368fe74f`; the inner recovery bundle SHA256 is `587b88b53634084be89f1d1fd96c96eb77549655a6f8dbe76d57c16e8c818517`. Hosted update/rollback preserved named-volume identities and local-auth continuity.

## Issue #189 recovery boundary

Software/isolated backup-restore, real MQTT/SQLite outage replay, actual-host reboot persistence and hosted ARM64/local-auth package acceptance are verified for their recorded source lineages. The currently accepted recovery artifact `9584581740` is exact to runtime source `cc27b609...`, not the currently deployed `a389a69d...` source. Therefore #189 remains blocked until recovery/package acceptance is refreshed for `a389a69d...` or another explicitly accepted current-source recovery path is established. Optional power-loss evidence remains separately gated.

## Current soft blockers and operational observations

- Authorized telemetry-retention maintenance on 2026-08-26 created and checksum-verified a PostgreSQL backup before deletion. Confirmed completed cleanup is 3,784,832 old `telemetry_session_contexts` rows plus 250,000 old `telemetry_samples`, followed by `VACUUM FULL ANALYZE telemetry_session_contexts`. Full deletion of all sensor samples before 2026-08-20 was not completed and must not be reported as completed retention.
- Temporary `/dev/zram1` was added only to provide deployment build headroom. It is not a persistent runtime requirement and should be removed after a safe swap-headroom check; it is not part of the NEXOLAB product/runtime contract.

## Hardware validation backlog

- #200 — physical RS-485 topology, second adapter, Unit 115 reality, termination/bias/shielding and duplicate-ID isolation remain hardware-unverified.
- #201 — normal-operation LE-01MP semantics are accepted; controlled restart/power-cycle discontinuity evidence remains pending.
- #202 — representative XJP60D firmware/semantic portability still needs real hardware evidence.
- #585 — W2 / Unit 201 handback remains blocked until external RS-485 ownership is released and physical handback is approved.

## Security maintenance

Issue #704 / PR #705 is merged and completed after exact-head fresh Container Supply Chain, Telemetry Service, Core CI and NEXOLAB Merge Gate verification. Telemetry-service OpenSSL `CVE-2026-14456` exceptions remain retired. Device Agent retains only `libssl3t64/CVE-2026-14456` through **2026-08-30**. Exact Device Agent and telemetry-service SQLite decisions plus telemetry `libcjson1/CVE-2026-16554` and `libwebsockets19t64/CVE-2026-78161` remain time-bounded through **2026-09-02** with documented early-removal triggers.

## Runtime and safety boundary

Core NEXOLAB remains `LOCAL_LAN` / offline-first with no mandatory public internet, paid runtime service, CDN, remote font or external runtime API.

Package authority/staging/activation, `establish-package-authority`, source→packaged transition and actual-host update/rollback remain production cutover boundaries requiring separate approval. No destructive restore, new persistent-data deletion, named-volume deletion, Modbus/controller write or hardware write is authorized.
