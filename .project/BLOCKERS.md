# NEXOLAB Blockers

Updated: 2026-08-28

## Issue #709 — post-merge Saved Dashboard runtime CSV verification

The Product Owner explicitly authorized the controlled Raspberry Pi deployment/runtime CSV re-verification on 2026-08-29, bounded to historical main target `ff86b10b71c8e5252c15baaf4183adbf42f30f18` so later unapproved product scope is not deployed. Runtime mutation remains temporarily blocked only by Issue #753: the repository-owned deployment path must first gain exact historical-main source selection with fail-closed `deployed → target → origin/main` ancestry and checkout restoration. Repository/software acceptance remains valid.

## Issue #711 — post-merge Energy runtime verification

The Product Owner explicitly authorized the controlled Raspberry Pi deployment/operator verification on 2026-08-29 using the same bounded target `ff86b10b71c8e5252c15baaf4183adbf42f30f18`. Software verification remains GREEN. Runtime mutation waits only for Issue #753 deployment-tooling exact-head acceptance; no Modbus, acquisition-cadence, hardware, database or persistent-volume write is required by the #711 fix itself.

## Issue #189 — actual-host recovery acceptance

Blocked because accepted ARM64/local-auth artifact `9584581740` from GREEN run `32939760743` is exact to runtime source `cc27b609...`, while the currently deployed LAN source is now `ff796b1f...` from successful deployment evidence `runtime/deployments/20260827T101743Z`. The old artifact remains historical evidence but is not exact-source authority for the current runtime. Refresh recovery/package acceptance for `ff796b1f...` or establish another explicitly accepted current-source recovery path before resuming the actual-host recovery drill. Actual-host cutover/recovery and power-loss remain separately gated.

## Issue #200 — physical RS-485 topology

Passive evidence confirms one CP2104 adapter and one current production bus. Full acceptance still requires physical topology inspection and/or the intended second isolated adapter. Unit 115, duplicate IDs, termination, biasing, shielding and grounding remain unverified.

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

## Issues #709 / #711 — approved bounded controlled deployment

Product Owner authorization is recorded for the exact historical-main deployment target `ff86b10b71c8e5252c15baaf4183adbf42f30f18` only. Issue #753 is the temporary tooling gate that prevents deploying later unrelated `main` scope. After #753 merges GREEN, run source-selection preflight, controlled deployment and real runtime acceptance for CSV sensor rows plus Energy continuity.

## Issue #753 — PR #754 deployment-safety review hardening

The fifth P1 is locally addressed: historical source adoption now stays on canonical control `main`, verifies explicit historical evidence/main ancestry, and derives build/schema from the exact deployed source Git object. Real source proof distinguishes target `ff86b10b...` schema `20260820_0026` from control-main `20260828_0027`; local deployment + adopter safety tests are 45/45 PASS. #753 remains blocked from merge/production mutation until the new exact head is Core/Telemetry/Merge-Gate GREEN and fresh review has zero unresolved findings.

## Cleared boundaries

- #730 Opera/Tailscale inspection — completed on 2026-08-29. The dedicated `ChatGPT Opera Inspection` session enters the authenticated shell automatically as `Спостерігач`; REST/WebSocket are active; the isolated `nexolab-inspection` helper and root-owned `0600` login socket remain intact; direct frontend `/inspection-login` stays 404; production `:3000` stays HTTP 200; PR #731 is merged with exact-head Core/Telemetry/Merge-Gate GREEN.
- #729 Embraco refrigeration digital twin — completed and merged in PR #736; exact-head Core/Telemetry/Refrigeration/Auth/Offline/DR/Security/Device-Agent/Container/Merge-Gate verification is GREEN. Production Embraco polling activation, migration application and temperature engineering scale remain separate unapproved/unverified boundaries.
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
