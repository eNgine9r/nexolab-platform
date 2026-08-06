# NEXOLAB Blockers

Updated: 2026-08-06

## Issue #255 merge boundary

Issue #255 / PR #362 is verified ready for merge at exact head:

```text
8c43439e1ab34e398f4b3bf2a9c8545e4386b956
```

Verified outcome:

- TypeScript resolves from `5.9.3` to `6.0.3`;
- `tsc --noEmit` is GREEN before and after the migration;
- new TypeScript 6 diagnostics: `0`;
- deterministic lockfile movement is limited to the root entry and `node_modules/typescript`;
- `tsconfig.json`, application source, tests, Playwright configs and Vitest config are unchanged;
- `strict`, `noEmit`, `isolatedModules`, `module: esnext`, `moduleResolution: bundler` and explicit `target: ES2017` remain unchanged;
- no `ignoreDeprecations`, broad `types` list, `any` baseline or mass `ts-expect-error` was introduced;
- all 11 exact-head CI, browser, Offline Auth and Offline Bundle workflows are GREEN;
- Offline Bundle proves disconnected startup and update/rollback persistent-data preservation;
- production dependencies and runtime closure are unchanged;
- no database, acquisition, scheduler, hardware, Modbus or production/site action occurred.

No Issue #255 software blocker remains. Merge only while the immutable head above remains current, zero commits behind `main`, and GREEN.

## Next Ready boundary: Issue #357

Issue #357 is the selected next Ready Work Package after Issue #255 merges.

Required outcome:

- return refrigeration equipment identity, active image metadata, layout revision, placements, active bindings and canonical channel metadata as one bounded structural snapshot;
- retain the last valid organization/equipment-scoped snapshot across route transitions;
- use stale-while-revalidate without clearing image, placements or markers;
- deduplicate concurrent equivalent reads and invalidate only the affected equipment after mutations;
- render configured channels without current telemetry using explicit unknown/stale state;
- keep structural rendering independent from latest telemetry latency;
- measure cold and warm route hydration and duplicate request count;
- preserve image lifecycle, layout editing, optimistic concurrency, binding lifecycle and physical polling boundaries.

Until real Raspberry Pi evidence is attached, completion must remain:

```text
software verified; Raspberry Pi perceived-latency acceptance pending
```

## Parallel runtime and hardware boundary

Issue #245 remains Ready on the parallel standalone Raspberry Pi runtime track, but it is not selected ahead of the critical product-visible Issue #357. Actual loopback-only Raspberry Pi acceptance remains mandatory before hardware completion can be claimed.

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
