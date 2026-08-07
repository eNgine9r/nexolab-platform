# NEXOLAB Blockers

Updated: 2026-08-07

## Issue #357 software completion

Issue #357 / PR #364 is squash-merged into `main` as `f837cae493e9903b0123c8b1ba7ff3c7401eacfc`.

Verified outcome:

- bounded equipment-scoped structural snapshot implemented;
- canonical climate-chamber channels included independently of current telemetry samples;
- configured no-sample channels remain visible with explicit `unknown`/`stale` state;
- bounded organization-scoped SWR cache, concurrent request deduplication and equipment-targeted invalidation implemented;
- valid canvas/markers retained during reconciliation and route transitions;
- structural rendering no longer waits on telemetry-history latency;
- refrigeration hydration and detail reconciliation loops removed;
- canonical restored-equipment path no longer requires a direct `node_id`;
- all exact-head CI, browser, telemetry, security, fleet, disaster-recovery, Offline Auth and Offline Bundle workflows GREEN;
- unresolved review threads: 0;
- no dependency upgrade, database migration, acquisition scheduler change, Device Agent configuration change, Modbus write, hardware write or site cutover occurred.

No software blocker remains for Issue #357.

## Remaining physical acceptance

Issue #357 retains the truthful completion classification:

```text
software verified; Raspberry Pi perceived-latency acceptance pending
```

The remaining Raspberry Pi check is physical evidence, not a software blocker. Hardware completion must not be claimed until the controlled LOCAL_LAN Raspberry Pi retest measures cold/warm perceived latency and confirms the absence of the historical blank-marker interval on the real substrate image/database.

## Parallel runtime and hardware boundary

Issue #245 remains Ready on the parallel standalone Raspberry Pi runtime track. Actual loopback-only Raspberry Pi acceptance remains mandatory before hardware completion can be claimed.

Issue #355 remains:

```text
software verified; Raspberry Pi runtime latency acceptance pending
```

## Dependency lanes

Open unselected dependency PRs: #340, #341 and #346.

PR #347 remains obsolete because Playwright 1.62 already merged through Issue #254 / PR #352.

Issue #257 remains blocked. Issue #256 remains deferred.

## Security and hardware blockers

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Do not broaden it.

Hardware-dependent Issues #289, #245, #189, #200, #201 and #202 remain pending controlled Raspberry Pi/RS-485 evidence.

`/lockers`, physical cameras, ONVIF/RTSP and NVR remain blocked or unverified by their existing evidence requirements.

## Global hard-stop rules

Stop before destructive data or volume operations, production cutover, hardware writes, secret exposure, mandatory online runtime dependencies, grouped migrations or unsupported physical acceptance claims.
