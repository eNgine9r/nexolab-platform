# NEXOLAB Blockers

Updated: 2026-08-27

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

Issue #704 has exact-head repository verification GREEN at `e2f7857e381600d76dd4100cea2c776bab8868e8`: fresh Container Supply Chain, Telemetry service, Core CI and NEXOLAB Merge Gate all passed. The security interrupt no longer blocks #690, which is Ready. Remaining maintenance is deadline-driven rather than a current merge blocker: Device Agent `libssl3t64/CVE-2026-14456` expires **2026-08-30**; exact Device Agent and telemetry-service SQLite decisions plus telemetry `libcjson1/CVE-2026-16554` and `libwebsockets19t64/CVE-2026-78161` expire **2026-09-02** and must be removed earlier if findings disappear, fixes become consumable, reachability/version evidence changes or severity becomes Critical. No production/runtime mutation is authorized by this security reconciliation.

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

## Safety boundaries

No blocker may be bypassed by Modbus/controller write, hardware write, production/site cutover without approval, persistent-data deletion, named-volume deletion, secret exposure or mandatory cloud dependency.
