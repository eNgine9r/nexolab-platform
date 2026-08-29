# NEXOLAB Current State

Updated: 2026-08-29

## Current Sprint

`PRODUCTION-READINESS-1` remains active only for outstanding hardware/recovery and controlled-deployment acceptance boundaries. Its repository-readiness gate is complete. RFX-00 / Issue #715 / PR #716 is completed and merged; accepted ADR 0010 remains the architecture authority for future refrigeration expansion.

### Product priority hold — RFX-01 through RFX-19C

On **2026-08-28** the Product Owner intentionally deferred the global RFX implementation programme **RFX-01 through RFX-19C for an indefinite period until after the main NEXOLAB presentation** (Issue #727). This is a product-priority decision, not a technical failure or architecture rollback. The current product is the presentation/delivery baseline; normal bug fixes, security maintenance and explicitly requested presentation-readiness work remain allowed.

RFX-01 / Issue #717 is no longer Ready and is blocked by the Product Owner hold. PR #718 was closed **without merge**; its branch and head `61bf4eac3f6c87b92786327e1b63416977057583` are retained only as a recoverable engineering checkpoint. RFX-02 and all later RFX Work Packages must not start automatically. Resume requires an explicit Product Owner restart decision after the presentation followed by a fresh Team Lead audit of current `main`, `.project/**`, architecture, migration head, open Issues/PRs and CI; the pre-pause PR must not be treated as merge-ready by default.

Security/CI interrupts discovered during the attempted RFX-01 verification were completed independently because they affect the presentation baseline: #723 / PR #724 merged at `8e9333fe76bce4a5babccaf7a3bedf35c5fe49bb`, and #719 / PR #721 merged at `1f2654dec0f02263aec6c2314187cfa62e5723e9` with exact-head Container Supply Chain, Telemetry service, Core CI and NEXOLAB Merge Gate GREEN. Issue #722 triage is completed. The exact Device Agent `libexpat1/CVE-2026-66046` maintenance decision remains separately reviewable through **2026-09-02**.

Issue #707 remains the currently deployed LAN product lineage `ff796b1f7ddcf95a9be8e7f93c75a4837ec7eb0d`. Issue #709 repository implementation and Issue #711 repository fix are complete, but their Raspberry Pi runtime verification remains separately approval-gated as production/site-cutover work. Existing hardware/recovery blockers remain documented below and are not evidence that the presentation baseline is incomplete.

## Issue #733 — canonical project-state formatter boundary

Repository maintenance now excludes canonical `.project/*.json` State Model v2 files from Prettier formatting while leaving all ordinary formatter behavior unchanged. `scripts/validate-project-state.py` remains the sole formatting authority for `ACTIVE_SPRINT.json` and `LAST_CHECKPOINT.json`. The lint-staged v17 regression harness now stages canonical state JSON, runs the production lint-staged configuration and verifies byte-for-byte staged-state preservation. Formatter-only paths `.prettierignore` and `scripts/tests/lint-staged-v17.mjs` are also classified as known dependency/toolchain changes: they retain full Core quality/build but no longer fail closed into unrelated dashboard/offline/refrigeration external workflow requirements. The change-impact regression matrix passes 29/29. This fixes the deterministic Husky/CI routing conflicts reproduced during Issue #729 checkpointing without changing application or runtime behavior.

## Issue #729 Embraco refrigeration digital twin

Issue #729 is **completed** and PR #736 is merged. The accepted exact PR head is `c30a0d3b6cdb310652f9fc11f817ca2d986f77c4`. Exact-head GitHub verification is GREEN for Core Quality/build, Telemetry service, Refrigeration Browser Acceptance, Authenticated Dashboard Acceptance after one controlled rerun of a transient unchanged-product-code failure, Offline Bundle, Disaster Recovery Browser, Security Browser Acceptance, Device Agent Fleet Acceptance, Container Supply Chain and the NEXOLAB Merge Gate. The GitHub merge result was observed on `main` at `9b9f8cb74e98d3cd0f3162c8a883f02245344333`; that volatile merge/main fact is an observation and does not replace the exact verified product head.

The completed vertical slice adds a strict FC03-only Embraco Sync profile, reusable controller-to-refrigeration-equipment binding, persisted latest/history integration, operator tabs `Огляд / Схема / Графіки / Контролер`, periods `1 год / 12 год / 24 год / Кастом`, state/relay/alarm timelines, and a time-weighted compressor runtime duty calculation with explicit coverage and continuity-gap handling. Temperature/control engineering scaling remains fail-closed until real hardware correlation confirms it; raw values are not presented as verified °C.

No `EMBRACO_UNIT_IDS=2` production activation, production migration, runtime deployment, Modbus write, controller parameter change or hardware write occurred. The earlier local heavy-browser reboot risk is closed as a repository merge blocker because the full exact-head GitHub acceptance is GREEN; it does not authorize production activation.

## Active presentation-readiness chain after #729

Issue #730 / PR #731 has now passed the previously missing fresh approved-workstation Opera/Tailscale positive proof on **2026-08-29**. Opening `/inspection-login` from the connected Opera workstation automatically redirected into the normal authenticated NEXOLAB shell without Product Owner credential input; Settings identified the dedicated session as `ChatGPT Opera Inspection` with role `Спостерігач`, REST snapshot synchronization was active and WebSocket was active. The viewer session exposed no administrator/create controls in the inspected Settings surface. Host-side persistence/security was rechecked at the same time: inspection frontend and login socket are enabled/active, `Linger=yes`, the Unix socket is `0600 root:root`, Serve remains tailnet-only with `/`, `/api` and `/inspection-login` handlers, direct TCP frontend access to `/inspection-login` returns 404, and production Dashboard `:3000` still returns 200. No credential/token values were collected. The prior exact head `6a5949863c4e3dd52dc1f4669e1485535110d77b` had Core CI, Telemetry service and NEXOLAB Merge Gate GREEN; because `main` advanced through #745, PR #731 must be reconciled with current `main` and receive fresh exact-head required CI before merge.

Issue #725 (`CI-OPT-01`) is completed and PR #743 is merged. Exact verified head `7070ba520f482208beb47f36435a33324ff0c2e0` is GREEN for Core Quality/build, Telemetry service, Authenticated Dashboard Acceptance, Offline Bundle, Refrigeration Browser Acceptance and NEXOLAB Merge Gate. The repository now provides a detached clean-worktree local candidate gate with dependency-free state-only verification, full Core non-state planning, exact Node/NVM fallback, automatic Compose validation for deployment/runtime changes and fail-closed unknown-path handling. A real state-only candidate was verified GREEN. Full non-state local verification is intentionally directed away from the production 4 GB Raspberry Pi when it would risk competing with runtime services.

The delta Ready audit after #725 found no independent Ready Work Package. #730 is now the active merge candidate because its fresh Opera proof has passed; #200/#201/#202/#585 are hardware/evidence-gated; #709/#711 require explicit production/site-cutover approval; RFX-01 through RFX-19C remain on Product Owner hold. If #730 merges GREEN, the independent Ready queue is again exhausted until one of those gates changes. Issue #732 is closed not-planned because #733 established the accepted canonical State Model formatter boundary, and #720 is closed completed because the merged refrigeration/DR acceptance now selects the authoritative `Схема` route and exact-head DR verification is GREEN.

## Recently completed production-readiness boundaries

Issue #245 is completed with real Raspberry Pi standalone hardware evidence. Issue #444 LOCAL_LAN user administration, #646 protected `main`, #667 CVE lifecycle reconciliation and #673 state reconciliation are also completed.

## Durable baselines

Accepted repository product source: `c30a0d3b6cdb310652f9fc11f817ca2d986f77c4` (Issue #729 exact verified PR head). Embraco temperature scaling and production Bus 2 activation remain hardware/runtime-unverified and are not implied by this repository acceptance.

Currently deployed source: `ff796b1f7ddcf95a9be8e7f93c75a4837ec7eb0d` in `lan` runtime mode. Controlled LAN deployment evidence: `/home/nexolab/nexolab-platform/runtime/deployments/20260827T101743Z` with `DEPLOYMENT PASSED`; telemetry, Device Agent, Dashboard, Prometheus, Alertmanager, Grafana and MinIO readiness gates passed together with central smoke/API-contract verification. The Product Owner confirmed chart consolidation and CSV download, while CSV sensor-row content remains the active #709 regression.

The accepted repository baseline is newer than the deployed/hardware-validated runtime lineage. Existing #245 real-hardware evidence remains valid only for its recorded source/topology; repository synchronization is not deployment, hardware acceptance or cutover.

## Issue #675 source-to-packaged authority

Software implementation adds one bounded `establish-package-authority` host command. It accepts only trusted `controlled_source_deployment` lineage and an exact host-validated staged bundle with matching source commit, platform, schema, runtime mode and local-auth boundary. It holds the worker and update-plane locks, requires capacity and a verified non-empty PostgreSQL backup, records persistent-volume identities, preserves hardware/bridge/standalone overlays, performs a rollback-aware source-to-packaged Dashboard handoff, requires exactly one Alembic head, proves the real Modbus path on the same stable RS-485 topology, and commits catalog-backed packaged authority only after volume identities remain unchanged. The packaged record carries forward hardware authority so later update/rollback operations must retain the hardware overlay and re-prove the same hardware contract.

Legacy controlled-source records may derive missing Dashboard/auth identity only from their exact immutable deployment evidence with matching source commit and runtime mode. The full version-management matrix passes 63/63; Python compile, shell syntax and `git diff --check` also pass. Exact-source runtime packaging is now decoupled from recovery tooling through digest-bound `source_commit`/`tooling_commit` provenance, and verified offline image references are activated before any Compose-based backup or post-install verification. Exact-head CI, Telemetry service, Offline Bundle and NEXOLAB Merge Gate were GREEN for the completed #675 implementation. Actual packaged installation has not been executed on the Raspberry Pi.

## Issues #677 / #679 ARM64 package acceptance

#677 is merged and completed at PR #678. Its first real post-merge ARM64/local-auth run `32812878575` correctly failed closed on the QEMU-specific Device Agent Docker health timing gap, which was fixed by #679 without changing the pinned runtime source or native production health semantics. #679 merged at PR #680 and replacement run `32832798392` is GREEN for tooling `431f2a28a8ebf7b86536e5059b381b75d2c5b1a3`, exact deployed runtime source `cc27b609eea2917b97da96003a08e5c84a7edbb1`, `linux/arm64`, immutable LOCAL_LAN endpoints and local auth. Accepted artifact `9558305055` has GitHub/local SHA256 `25057b85a6b096275d3cadef8f03f3dfa8e608e1a3160932aec73d3a368fe74f`; the inner recovery bundle SHA256 is `587b88b53634084be89f1d1fd96c96eb77549655a6f8dbe76d57c16e8c818517`. Manifest/provenance record ARM64, runtime source `cc27b609...`, tooling `431f2a28...`, local auth, no packaged secrets, no mandatory runtime network/paid service and no volume deletion. Hosted update/rollback preserved named-volume identities and local-auth refresh/session/RBAC continuity, including rollback logout revocation.

## Issue #189 recovery boundary

Software/isolated backup-restore, real MQTT/SQLite outage replay, actual-host reboot persistence and hosted ARM64/local-auth package acceptance are verified for their recorded source lineages. The first approved actual-host package transition failed safely on #683 after backup and partial central recreation; source central, Dashboard, edge, all six persistent-volume identities and advancing telemetry were restored. #686 restored GREEN ARM64/local-auth acceptance in run `32939760743` for `cc27b609...`; because the currently deployed source is now `ff796b1f...`, artifact `9584581740` must not be treated as exact-source recovery authority. #189 remains blocked until recovery/package acceptance is refreshed for the current deployed source or another explicitly accepted recovery path is established. Optional power-loss evidence remains separately gated.

## Current soft blockers and operational observations

- #723 CI routing maintenance and #719 security reconciliation are completed and merged; #722 triage is closed. Their exact-head verification is durable evidence for the current presentation baseline.
- #696 replaced the refrigeration structural-snapshot history scan with the bounded `telemetry_latest` projection. Real Raspberry Pi SQL evidence improved the affected 84-channel KK2 lookup from `85874.034 ms` to `1.853 ms`; the previous #698 hosted-runner allocation blocker is cleared.
- Authorized telemetry-retention maintenance on 2026-08-26 created and checksum-verified a PostgreSQL backup before deletion. Confirmed completed cleanup is 3,784,832 old `telemetry_session_contexts` rows plus 250,000 old `telemetry_samples`, followed by `VACUUM FULL ANALYZE telemetry_session_contexts`. Full deletion of all sensor samples before 2026-08-20 was not completed and must not be reported as completed retention.

## Hardware validation backlog

- #200 — physical RS-485 topology, second adapter, Unit 115 reality, termination/bias/shielding and duplicate-ID isolation remain hardware-unverified.
- #201 — normal-operation LE-01MP semantics are accepted; controlled restart/power-cycle discontinuity evidence remains pending.
- #202 — representative XJP60D firmware/semantic portability still needs real hardware evidence.
- #585 — W2 / Unit 201 handback remains blocked until external RS-485 ownership is released and physical handback is approved.

## Security maintenance

Security reconciliation for Issue #704 has repository-side exact-head verification complete at `e2f7857e381600d76dd4100cea2c776bab8868e8`. Fresh no-cache Container Supply Chain run `33025323284` is GREEN for device-agent, telemetry-service, mqtt-dynamic-security and the aggregate release manifest; Telemetry service run `33025323323`, Core CI run `33025323332` and the NEXOLAB Merge Gate are GREEN on the same product head. All OpenSSL `CVE-2026-14456` exceptions are now retired: the final Device Agent `libssl3t64` tuple disappeared from the 2026-08-28 fresh scan and must not be restored without a new fail-closed evidence review. The replacement exact Device Agent `libexpat1/CVE-2026-66046` HIGH decision is time-bounded through **2026-09-02** because no XML parser/input path is reachable and no consumable fixed Debian package is available. Exact Device Agent/telemetry-service SQLite decisions plus telemetry `libcjson1/CVE-2026-16554` and `libwebsockets19t64/CVE-2026-78161` also remain bounded through **2026-09-02** with their documented early-removal triggers. This repository verification does not authorize or imply any runtime deployment.

## Issue #707 Saved Dashboard export and chart workspace

Repository-side software verification is complete for exact product/test head `1ca06521628e5936c9c00fb94ef895d6abfa1c21`. The persisted CSV endpoint accepts the legacy browser identifier `Europe/Kiev` through explicit canonicalization to `Europe/Kyiv` while invalid identifiers remain fail-closed. Saved Dashboard line/area series now consolidate across equipment and split only when the canonical five-axis readability budget is exceeded, preserving persisted series order; value/gauge-only dashboards do not create empty chart panels. Core CI, Telemetry service, Authenticated Dashboard Acceptance, Offline Bundle, Container Supply Chain and NEXOLAB Merge Gate are GREEN, and the fresh Codex review is clean. Generic Live Data equipment-centric grouping remains unchanged.

#707 was subsequently deployed through the controlled LAN path at `/home/nexolab/nexolab-platform/runtime/deployments/20260827T101743Z` and passed deployment readiness/smoke gates. Operator acceptance confirmed the consolidated graphs and CSV download action. CSV content validation exposed #709: temperature-controller telemetry rows were omitted because Live Dashboard resolved catalog identities such as `DIXELL-108` while persisted telemetry uses `K108`. No Modbus or hardware write occurred.

## Issue #709 Saved Dashboard sensor export identity regression

Repository-side implementation and verification are complete for product-code head `e969772519d896ebe78d8ff5fb283fddfbf800e0` and final product/test anchor `8de343198093c0c4f9b84510623df19e16d1ba87`. Live Dashboard now uses one canonical catalog-device → telemetry-equipment identity contract: temperature controllers resolve to `K{unit_id}`, energy meters remain `LE01MP-{unit_id}`, unsupported device types and Modbus Unit IDs outside `1..247` fail closed, and inventory, dashboard save validation and CSV export share the same eligibility boundary. Production-realistic backend and browser fixtures use the same identity for persisted history and live MQTT samples.

Raspberry Pi isolated Live Dashboard verification on the product-code head passed **27 tests with 1 skipped**. Exact-head GitHub verification on `8de343198093c0c4f9b84510623df19e16d1ba87` is GREEN for Core CI quality/build, Telemetry service, Authenticated Dashboard Acceptance, Offline Bundle, Container Supply Chain, Acquisition Scale, Refrigeration Browser, Offline Auth, MQTT TLS Fleet, Device Agent Fleet, Broker Control, disaster-recovery lanes, Capacity Release Gate and NEXOLAB Merge Gate. Authenticated Dashboard Acceptance passed **19/19** Playwright tests, including the persisted Saved Dashboard scenario whose unchanged CSV-content assertion requires more than the header row. Fresh Codex review on `8de343198093c0c4f9b84510623df19e16d1ba87` found no major issues and all review threads are resolved.

PR #710 merged at `3f73e81f4d99cfcd07ba1afadf3eba9957945bd1`, but production still runs `ff796b1f7ddcf95a9be8e7f93c75a4837ec7eb0d`; #709 has **not** been deployed. Repository state records #709 as blocked because controlled Raspberry Pi deployment/runtime CSV re-verification is a production/site-cutover action requiring explicit Product Owner approval. No Modbus, hardware, destructive-data or volume write occurred during repository verification.

## Issue #711 Energy history continuity regression

Real read-only Raspberry Pi/PostgreSQL/browser inspection on 2026-08-27 established the root cause: Energy history used an independent fixed `30_000 ms` source-gap rule while the real active-power cadence is approximately 30 s. In the current 24h dataset the old rule classifies 1,374 W1, 1,449 W3 and 1,401 W4 intervals as gaps. Applying the canonical observed-cadence policy yields thresholds around 90 s and only two current silent gaps, plus one persisted `communication_error`. PostgreSQL history access and ECharts rendering were not the cause.

Repository implementation is complete on product head `da3569969ad39be4e409fe91bc0821e2587368a0`. Energy history now consumes the existing read-only acquisition-registry cadence policy/audit as canonical authority, matches Device Agent scheduler deadline-reset semantics across cadence transitions, keeps timestamp-only fallbacks reversible, includes accepted non-valid telemetry timestamps in cadence estimation, fingerprints retained history against the exact cadence authority, and rejects stale/out-of-order authority refreshes without suppressing an older successful response after a newer failure.

Final local verification is GREEN: focused Energy/chart matrix **66/66**, Prettier, full frontend ESLint, TypeScript `tsc --noEmit`, Next.js production build and `git diff --check`. Exact-head GitHub Core CI, Authenticated Dashboard Acceptance, Offline Bundle and NEXOLAB Merge Gate are GREEN for `da356996...`; fresh exact-head Codex review found no major issues and all review threads are resolved. Software/repository verification is complete. The corrected code has **not** been deployed to the Raspberry Pi; controlled deployment/runtime operator verification remains a separate production/site-cutover boundary requiring explicit Product Owner approval. No Modbus, acquisition, database, hardware or runtime mutation occurred.

## Runtime and safety boundary

Core NEXOLAB remains `LOCAL_LAN` / offline-first with no mandatory public internet, paid runtime service, CDN, remote font or external runtime API.

#679 hosted-QEMU acceptance is completed; its GREEN evidence does not authorize Raspberry Pi runtime mutation. Package authority/staging/activation, `establish-package-authority`, source→packaged transition and actual-host update/rollback remain production cutover boundaries requiring separate approval. No destructive restore, persistent-data deletion, named-volume deletion, Modbus/controller write or hardware write is authorized.
