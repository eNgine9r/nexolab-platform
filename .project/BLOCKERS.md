# NEXOLAB Blockers

Updated: 2026-08-28

## Issue #709 — post-merge Saved Dashboard runtime CSV verification

PR #710 merged at `3f73e81f4d99cfcd07ba1afadf3eba9957945bd1`, but controlled Raspberry Pi deployment and runtime CSV-content re-verification remain blocked until the Product Owner explicitly approves that production/site-cutover action. Repository/software acceptance remains valid and no deployment is implied by the merge.

## Issue #711 — post-merge Energy runtime verification

Repository/software verification is complete for exact product head `da3569969ad39be4e409fe91bc0821e2587368a0`: local 66/66 focused tests, full lint/typecheck/build, Core CI, Authenticated Dashboard Acceptance, Offline Bundle, NEXOLAB Merge Gate and fresh Codex review are GREEN, with all review threads resolved. The corrected Energy history code has not been deployed to the Raspberry Pi. Controlled deployment and operator/runtime verification remain a production/site-cutover action and must not occur without explicit Product Owner approval. No Modbus, acquisition-cadence, hardware, database or persistent-volume write is required by the repository fix.

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

## Security maintenance — #704 verified; no current merge blocker

Issue #704 has exact-head repository verification GREEN at `e2f7857e381600d76dd4100cea2c776bab8868e8`: fresh Container Supply Chain, Telemetry service, Core CI and NEXOLAB Merge Gate all passed. The security interrupt no longer blocks repository work; #690 repository verification is complete and pending final state-only merge reconciliation. Remaining maintenance is deadline-driven rather than a current merge blocker: Device Agent `libssl3t64/CVE-2026-14456` expires **2026-08-30**; exact Device Agent and telemetry-service SQLite decisions plus telemetry `libcjson1/CVE-2026-16554` and `libwebsockets19t64/CVE-2026-78161` expire **2026-09-02** and must be removed earlier if findings disappear, fixes become consumable, reachability/version evidence changes or severity becomes Critical. No production/runtime mutation is authorized by this security reconciliation.

## Issue #709 — post-merge controlled deployment authorization

Repository verification and PR merge are not blocked. The controlled Raspberry Pi deployment and real CSV sensor-row re-verification are a production/site cutover boundary. Durable state records `production_cutover_authorized=false`, and Issue #709 has no Product Owner authorization comment. After GREEN merge, stop before runtime mutation until the Product Owner explicitly approves that controlled deployment. No Modbus or hardware write is part of the requested runtime verification.

## Operator browser inspection — soft tooling limitation

Opera Browser Connector private-address actions remain unsuitable for direct LAN/Tailscale DOM/screenshot acceptance. This did not block the controlled #707 deployment: the Product Owner directly confirmed consolidated graphs and CSV download, then identified the missing sensor-row content now owned by #709.

## Cleared boundaries

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
- #690 risk-aware/path-targeted PR verification — repository verification completed on exact product head `6b91236f87695c0901dd5498c7374657665d392c` with required external workflows and NEXOLAB Merge Gate GREEN; final state-only merge reconciliation remains.

## Safety boundaries

No blocker may be bypassed by Modbus/controller write, hardware write, production/site cutover without approval, persistent-data deletion, named-volume deletion, secret exposure or mandatory cloud dependency.
