# NEXOLAB Blockers

Updated: 2026-08-26

## Issue #189 — actual-host recovery acceptance

Blocked because accepted ARM64/local-auth artifact `9584581740` from GREEN run `32939760743` is exact to runtime source `cc27b609...`, while the currently deployed LAN source is now `a929144a...` from successful deployment evidence `runtime/deployments/20260826T125356Z`. The old artifact remains historical evidence but is not exact-source authority for the current runtime. Refresh recovery/package acceptance for `a929144a...` or establish another explicitly accepted current-source recovery path before resuming the actual-host recovery drill. Actual-host cutover/recovery and power-loss remain separately gated.

## Issue #696 / #698 — refrigeration latency merge blocked by hosted-runner allocation

Issue #696 is implemented in PR #697 at exact head `e77b99af4bc53b9e173ff913f824f6f7dc2a71c8`. Targeted refrigeration tests and real Raspberry Pi SQL benchmarking are GREEN; the affected KK2 lookup improved from `85874.034 ms` to `1.853 ms`. Merge is soft-blocked by Issue #698: GitHub scheduler annotation states `The job was not acquired by Runner of type hosted even after multiple attempts`. Repository Actions are enabled, no other accessible repository had an in-progress Actions job during diagnosis, and Capacity Release Gate later obtained a runner and passed, so allocation is intermittent. Do not merge #697 until the exact-head required checks execute and are GREEN.

## Issue #200 — physical RS-485 topology

Passive evidence confirms one CP2104 adapter and one current production bus. Full acceptance still requires physical topology inspection and/or the intended second isolated adapter. Unit 115, duplicate IDs, termination, biasing, shielding and grounding remain unverified.

## Issue #201 — LE-01MP cumulative energy

Normal-operation semantics are accepted. Controlled restart/power-cycle discontinuity evidence remains pending; an unplanned hard reset cannot be reclassified as approved evidence.

## Issue #202 — XJP60D portability

Representative KK1/KK2 physical evidence, Unit 115 resolution and extended semantics still require real hardware evidence. Unconfirmed fields remain unmapped.

## Issue #585 — W2 / Unit 201 handback

Blocked until the Product Owner confirms the temporary external RS-485 owner has released W2 and approves any required physical handback/reconnection.

## Security maintenance — CVE-2026-14456

Issue #704 is the active security-maintenance interrupt. Three telemetry-service OpenSSL `CVE-2026-14456` exceptions are retired because the fresh image consumes fixed OpenSSL `3.5.7-1~deb13u2`. The remaining Device Agent OpenSSL tuple expires **2026-08-30** while the supported distroless base still lags the Debian fix. Two exact Device Agent `libsqlite3-0` HIGH decisions (`CVE-2026-11822`, `CVE-2026-11824`) expire **2026-09-02**; current reachability audit finds no FTS5, arbitrary-SQL or untrusted-database import path. Any Critical finding remains release-blocking and cannot be excepted. Issue #690 is temporarily blocked only by this critical interrupt and returns to Ready after #704 completes.

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
- #684 task-oriented Settings workspace — implementation and exact-head CI/browser/offline/merge-gate verification completed in PR #689; no hardware or production cutover evidence required for this presentation-only Work Package.

## Safety boundaries

No blocker may be bypassed by Modbus/controller write, hardware write, production/site cutover without approval, persistent-data deletion, named-volume deletion, secret exposure or mandatory cloud dependency.
