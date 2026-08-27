# NEXOLAB Blockers

Updated: 2026-08-27

## Issue #189 — actual-host recovery acceptance

Blocked because accepted ARM64/local-auth artifact `9584581740` from GREEN run `32939760743` is exact to runtime source `cc27b609...`, while the currently accepted and deployed LAN source is `a389a69d00a92380bce49930750bc5a99d992bde` from successful deployment evidence `runtime/deployments/20260827T054754Z`. The old artifact remains historical evidence but is not exact-source authority for the current runtime. Refresh recovery/package acceptance for `a389a69d...` or establish another explicitly accepted current-source recovery path before resuming the actual-host recovery drill. Actual-host cutover/recovery and power-loss remain separately gated.

## Telemetry retention maintenance — partial authorized cleanup

Authorized retention work on 2026-08-26 is only partially complete. Confirmed committed deletion is 3,784,832 old `telemetry_session_contexts` rows and 250,000 old `telemetry_samples`, with `VACUUM FULL ANALYZE telemetry_session_contexts` completed. Do not claim all sensor telemetry before 2026-08-20 was deleted, and do not expand the authorized deletion scope without a separate explicit boundary.

## Issue #200 — physical RS-485 topology

Passive evidence confirms one CP2104 adapter and one current production bus. Full acceptance still requires physical topology inspection and/or the intended second isolated adapter. Unit 115, duplicate IDs, termination, biasing, shielding and grounding remain unverified.

## Issue #201 — LE-01MP cumulative energy

Normal-operation semantics are accepted. Controlled restart/power-cycle discontinuity evidence remains pending; an unplanned hard reset cannot be reclassified as approved evidence.

## Issue #202 — XJP60D portability

Representative KK1/KK2 physical evidence, Unit 115 resolution and extended semantics still require real hardware evidence. Unconfirmed fields remain unmapped.

## Issue #585 — W2 / Unit 201 handback

Blocked until the Product Owner confirms the temporary external RS-485 owner has released W2 and approves any required physical handback/reconnection.

## Security maintenance — deadline driven

Issue #704 / PR #705 is merged and completed. Remaining maintenance is deadline-driven rather than a current merge blocker: Device Agent `libssl3t64/CVE-2026-14456` expires **2026-08-30**; exact Device Agent and telemetry-service SQLite decisions plus telemetry `libcjson1/CVE-2026-16554` and `libwebsockets19t64/CVE-2026-78161` expire **2026-09-02** and must be removed earlier if findings disappear, fixes become consumable, reachability/version evidence changes or severity becomes Critical.

## Cleared boundaries

- #444 LOCAL_LAN user administration — completed.
- #646 main branch protection — completed; `main` requires `NEXOLAB Merge Gate`.
- #667 CVE lifecycle date reconciliation — completed and merged.
- #245 standalone offline Raspberry Pi acceptance — completed on real hardware.
- #673 production-readiness state reconciliation — completed and merged.
- #675 source-to-packaged authority tooling — completed with exact-head review and required GREEN workflows.
- #679 ARM64 QEMU package acceptance — completed with GREEN post-merge ARM64/local-auth run `32832798392` and independently verified artifact/provenance.
- #683 local-auth relocation/full source recovery — merged at PR #685.
- #686 ARM64/local-auth acceptance fixture permissions — completed at PR #687; replacement run `32939760743` GREEN.
- #684 task-oriented Settings workspace — completed and deployed.
- #698 GitHub-hosted runner allocation incident — resolved; fresh exact-head workflows acquired runners and completed.
- #704 container security reconciliation — completed and merged at PR #705.
- #696 refrigeration structural snapshot latency — completed and merged at PR #697, deployed on `a389a69d...`; cold real Pi endpoint `0.067 s`, telemetry continuity PASS, production UI confirmed fast.

## Safety boundaries

No blocker may be bypassed by Modbus/controller write, hardware write, production/site cutover without approval, persistent-data deletion outside the explicitly authorized retention scope, named-volume deletion, secret exposure or mandatory cloud dependency.
