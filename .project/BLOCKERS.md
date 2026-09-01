# NEXOLAB Blockers

Updated: 2026-09-01

## Issue #792 — selected-interval relay traceability and export

**Software blocker cleared 2026-09-01.** Exact product/test head `cb6bd4357f32e5655d8ebba523afc0bd25c9e842` is GREEN for Core Quality/build, Refrigeration Browser Acceptance, Authenticated Dashboard Acceptance, Disaster Recovery Browser and NEXOLAB Merge Gate. Real Chromium confirms direct left-button drag → selected interval → KPI/relay/export synchronization with persistent highlight and no range slider. The preceding DR failure was a stale title assertion, not restored-data loss; the test now verifies the restored canonical equipment name from the API against the operator H1, and replacement DR acceptance is GREEN. #792 has no remaining software/hardware blocker; only state-only exact-head verification, final review-thread resolution and PR #793 merge remain. No Modbus write, hardware write, cadence change, backend migration or production deployment belongs to #792.

## Issue #790 — controlled deployment final Device Agent health race

Issue #789 product/runtime acceptance is complete: the Product Owner confirmed the selected compressor range/KPI behavior in the real interface, and the activated runtime is currently healthy. A separate deployment-evidence maintenance defect remains: attempt `runtime/deployments/20260901T064156Z` failed its final success marker because Docker health had not yet converged although Device Agent HTTP readiness was already passing; the container became and remained `healthy` seconds later. Until #790 is fixed and a future guarded deployment establishes valid success evidence, **do not advance formal controlled-source authority from `20bb9ca...` based on the failed #789 attempt**. This is an evidence/recovery-governance blocker, not a blocker to the operator-visible #785 feature.

## Issue #785 — operator-selected compressor analysis interval

**Cleared 2026-09-01.** Exact verified product head `5a1df9a08dbe39c4be0f93c6a5e6dc622136d1c3` passed Core Quality/build, Refrigeration Browser Acceptance, Authenticated Dashboard Acceptance, Disaster Recovery Browser and NEXOLAB Merge Gate; PR #786 merged and Issue #785 closed completed. No new hardware acceptance was required because the feature derives locally from already persisted read-only `compressor.speed` history. Production deployment remains a separate explicit boundary.

## Issue #772 — persisted Embraco physical-bus identity

**Cleared 2026-08-30.** PR #773 merged GREEN. Production-copy acceptance proved `EMBRACO-2` persists on `rs485-embraco`, reloads without mismatch, preserves Unit 201 as disabled on `rs485-main`, and retains legacy single-bus behavior. This safety prerequisite no longer blocks #760.

## Issue #760 — Embraco Unit 2 production activation

**Cleared 2026-08-31.** Controlled deployment `runtime/deployments/20260830T202942Z` passed on exact source `20bb9ca473395a0c64267b9b08523c31404f41e6` for physical controller #2 / Embraco Unit 2 only; controller #1 is test-only and Unit 96 is excluded. Registry revision 20 persists `embraco-2@rs485-embraco`, Unit 201 remains disabled on Bus 1, schema head is `20260828_0027`, and Device Agent is healthy in `modbus` mode with MQTT connected and queue depth 0. Real FC03-only state/RPM/relay/alarm telemetry is durable; unverified temperature/control scale remains NULL/`unknown`. `Cool jet → EMBRACO-2` is audit-backed.

Final external gates are cleared: source/version authority is recorded as `controlled_source_deployment` for source `20bb9ca...`, linux/arm64, LAN, schema `20260828_0027`, health `ready`; production Opera acceptance entered as `ChatGPT Opera Inspection / viewer`, proved REST snapshot + active WebSocket, and displayed real `Cool jet` controller state (`Embraco Online`, `Cooling`, 2142 rpm / Running, relay states, no controller alarms, `Scale unverified`). Exact-head manual Telemetry, Refrigeration Browser, Authenticated Dashboard and Offline Bundle workflows on acceptance head `ebccb8ad...` are GREEN. Final state head `46cefa49...` also passed State integrity and NEXOLAB Merge Gate; PR #779 squash-merged at `72d67360...` and GitHub closed #760 completed.

## Issue #709 — post-merge Saved Dashboard runtime CSV verification

**Cleared 2026-08-29.** Bounded deployment `runtime/deployments/20260829T154823Z` activated `ff86b10b...`. Existing Saved Dashboard runtime export produced 120 real `108-01 / temperature.probe` rows using `K108`, with numeric valid values; inventory/latest correlation also resolves `K108`. Issue #709 is closed completed.

## Issue #711 — post-merge Energy runtime verification

**Cleared 2026-08-29.** The same bounded deployment activated the cadence-aware Energy fix. Real 24h exact-target verification reduced 8,573 raw rows to 717 render rows with 7 durable and 0 inferred continuity breaks, eliminating the previous 448 normal-jitter false breaks while preserving genuine silent gaps.

## Issue #189 — actual-host recovery acceptance

Blocked because accepted ARM64/local-auth artifact `9584581740` from GREEN run `32939760743` is exact to runtime source `cc27b609...`, while the currently deployed LAN source is now `20bb9ca...` from successful deployment evidence `runtime/deployments/20260830T202942Z`. The old artifact remains historical evidence but is not exact-source authority for the current runtime. Refresh recovery/package acceptance for `20bb9ca...` or establish another explicitly accepted current-source recovery path before resuming the actual-host recovery drill. Actual-host cutover/recovery and power-loss remain separately gated.

## Issue #200 — physical RS-485 topology

Issue #760 now verifies the second CP2104 production adapter `0133F246` and read-only Embraco Unit 2 ownership on isolated `rs485-embraco` at 9600 8N2 while preserving Bus 1. Full #200 acceptance still requires the remaining physical-topology evidence: Unit 115 reality, duplicate-ID isolation beyond the accepted Unit 2 scope, termination, biasing, shielding and grounding.

## Issue #201 — LE-01MP cumulative energy

Normal-operation semantics are accepted. Controlled restart/power-cycle discontinuity evidence remains pending; an unplanned hard reset cannot be reclassified as approved evidence.

## Issue #202 — XJP60D portability

Representative KK1/KK2 physical evidence, Unit 115 resolution and extended semantics still require real hardware evidence. Unconfirmed fields remain unmapped.

## Issue #585 — W2 / Unit 201 handback

Blocked until the Product Owner confirms the temporary external RS-485 owner has released W2 and approves any required physical handback/reconnection.

## Product priority hold — RFX-01 through RFX-19C

Issue #727 records an intentional Product Owner defer of **RFX-01 through RFX-19C until after the main presentation**. This is not a technical blocker and does not invalidate accepted RFX-00 / ADR 0010. Issue #717 is non-Ready/blocked by product decision; PR #718 is closed unmerged and retained only as a historical checkpoint. Do not auto-advance to RFX-02 or reopen/merge the pre-pause RFX-01 branch. Resume requires an explicit Product Owner restart plus a fresh Team Lead source-of-truth audit.

## Security maintenance — #704 verified; no current merge blocker

Issue #704 has exact-head repository verification GREEN at `e2f7857e381600d76dd4100cea2c776bab8868e8`; #690 is completed and merged in PR #714 at `4ee7f836442fbfc9ed257c2c8eaf8ad2e22fbe51`. The final Device Agent `libssl3t64/CVE-2026-14456` exception is **retired** because the fresh 2026-08-28 scan no longer reports the finding. Deadline-driven maintenance through **2026-09-02** now consists of the exact Device Agent `libexpat1/CVE-2026-66046` decision, Device Agent/telemetry-service SQLite decisions, and telemetry `libcjson1/CVE-2026-16554` / `libwebsockets19t64/CVE-2026-78161`; each must be removed earlier if its documented finding/fix/reachability/version/severity trigger changes. No production/runtime mutation is authorized by this security reconciliation.

## Issue #755 — approved bounded #709 / #711 controlled deployment

**Cleared 2026-08-29.** Deployment `runtime/deployments/20260829T154823Z`, #709/#711 real runtime acceptance and controlled-source version-management adoption all passed. Deployed source authority is `ff86b10b...` with schema `20260820_0026`, `linux/arm64`, `lan`, health `ready`, and `known_packaged_release=false`. #729 and later product runtime scope remain excluded and require a separate explicit production/hardware gate.

## Issue #757 — completion candidate capacity prerequisite for #755

**Cleared.** Issue #757 / PR #758 is merged and the corrected capacity guard was used successfully by #755. No runtime/data/hardware mutation belongs to #757.

## Issue #753 — cleared

PR #754 is merged at `76fa83a80e2eef82ae6f6e7c616a0dbe9352a5c8`; implementation safety and final state heads are GREEN and clean-reviewed. #753 no longer blocks runtime activation.

## Cleared boundaries

- #730 Opera/Tailscale inspection — completed on 2026-08-29. The dedicated `ChatGPT Opera Inspection` session enters the authenticated shell automatically as `Спостерігач`; REST/WebSocket are active; the isolated `nexolab-inspection` helper and root-owned `0600` login socket remain intact; direct frontend `/inspection-login` stays 404; production `:3000` stays HTTP 200; PR #731 is merged with exact-head Core/Telemetry/Merge-Gate GREEN.
- #729 Embraco refrigeration digital twin — completed and merged in PR #736; exact-head Core/Telemetry/Refrigeration/Auth/Offline/DR/Security/Device-Agent/Container/Merge-Gate verification is GREEN. Production Embraco Unit 2 polling and migration were subsequently accepted under #760; temperature/control engineering scale remains separately hardware-unverified and fail-closed.
- #444 LOCAL_LAN user administration — completed.
- #646 main branch protection — completed; `main` requires `NEXOLAB Merge Gate`.
- #667 CVE lifecycle date reconciliation — completed and merged.
- #245 standalone offline Raspberry Pi acceptance — completed on real hardware.
- #673 production-readiness state reconciliation — completed and merged.
- #675 source-to-packaged authority tooling — completed with exact-head review and required GREEN workflows.
- #679 ARM64 QEMU package acceptance — completed with GREEN post-merge ARM64/local-auth run `32832798392` and independently verified artifact/provenance.
- #683 local-auth relocation/full source recovery — merged at PR #685 with exact-head required workflows GREEN; its post-merge acceptance correctly failed before mutation on the separate #686 hosted fixture-permission defect.
- #686 ARM64/local-auth acceptance fixture permissions — completed at PR #687; replacement run `32939760743` GREEN and accepted artifact `9584581740` published without production runtime mutation.
- #684 task-oriented Settings workspace — implementation and exact-head CI/browser/offline/merge-gate verification completed; no hardware or production cutover evidence required for this presentation-only Work Package.
- #696 refrigeration structural latest-value latency — completed; bounded `telemetry_latest` query and real Raspberry Pi benchmark evidence accepted.
- #698 GitHub-hosted runner allocation recovery — completed; exact-head workflows execute normally again.
- #704 container security reconciliation — completed with exact-head security/CI evidence; only time-bounded maintenance remains.
- #719 / PR #721 fresh Device Agent security reconciliation — completed and merged at `1f2654dec0f02263aec6c2314187cfa62e5723e9`; #722 triage is completed.
- #723 / PR #724 CI routing maintenance — completed and merged at `8e9333fe76bce4a5babccaf7a3bedf35c5fe49bb`.
- #690 risk-aware/path-targeted PR verification — completed and merged in PR #714 at `4ee7f836442fbfc9ed257c2c8eaf8ad2e22fbe51`; post-merge Core CI and Acquisition Scale Acceptance are GREEN.
- #715 RFX-00 refrigeration architecture ADR — completed and merged in PR #716; ADR 0010 remains accepted architecture authority while RFX-01 through RFX-19C are product-deferred under #727.
- #733 canonical project-state formatter boundary — completed locally; `.project/*.json` is excluded from Prettier and remains governed by State Model v2 validation.

## Safety boundaries

No blocker may be bypassed by Modbus/controller write, hardware write, production/site cutover without approval, persistent-data deletion, named-volume deletion, secret exposure or mandatory cloud dependency.
