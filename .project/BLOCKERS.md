# NEXOLAB Blockers

Updated: 2026-08-06

## Issue #252 / PR #361 merge boundary

No software implementation or verification blocker remains on exact implementation head `ca9291903e61fd4951bb2565a64d2306ef5da824`.

Verified:

- current `main` state baseline `0e5b39a93130dfcc8810b28e0ff7348fdd3d0e08` is included and the branch is zero commits behind;
- implementation diff is limited to four permitted permanent files plus this four-file state checkpoint;
- lint-staged resolves from `16.4.0` to `17.3.0` under Node `22.23.1`;
- Git `2.54.0` satisfies the v17 minimum `2.32.0`;
- current globs, ESLint-before-Prettier command order and Husky hook are unchanged;
- production-config staged-file processing passes;
- partial-stage success restores unstaged changes;
- failed tasks restore the original index and worktree diff;
- empty staged-file behavior passes;
- all exact-head CI, browser, Offline Auth and Offline Bundle workflows are GREEN;
- Offline Bundle proves disconnected startup and update/rollback persistent-data preservation;
- production dependencies and runtime closure are unchanged;
- no temporary workflow remains;
- unresolved review threads are zero;
- no database, acquisition, hardware, Modbus or production/site action exists.

Remaining control sequence:

1. validate this four-file state checkpoint;
2. mark PR #361 Ready;
3. repeat current-head, mergeability, review and required-check audit;
4. squash merge PR #361 and confirm Issue #252 closure;
5. promote Issue #255 as the sole Next Ready Work Package.

## Next Ready Work Package boundary: Issue #255

After PR #361 merges, Issue #255 becomes the sole Ready package.

Required outcome:

- review the official TypeScript 6 transition release and breaking diagnostics;
- update TypeScript only with deterministic lockfile movement;
- preserve strict mode and no-emit verification;
- explain and fix every new diagnostic without broad ignores, `any` baselines or weakened strictness;
- keep Next.js production build, Vitest and Playwright TypeScript configs operational;
- retain Offline Bundle GREEN;
- document rollback.

Hard boundaries:

- no TypeScript 7 native compiler;
- no ESLint 10, React, Next.js or unrelated dependency migration;
- no product refactor unrelated to new TypeScript 6 diagnostics;
- no production deployment, secrets, hardware actions or Modbus writes.

## Raspberry Pi acceptance boundary

Issue #355 remains `software verified; Raspberry Pi runtime latency acceptance pending`. Its physical acceptance does not block Issue #252 or Issue #255.

## Dependency lanes

Open unselected dependency PRs: #340, #341 and #346.

PR #347 remains obsolete because Playwright 1.62 already merged through Issue #254 / PR #352.

Closed unmerged dependency PRs: #272 and #339.

Ordered sequence:

```text
#252 lint-staged 17
→ #255 TypeScript 6
```

Issue #257 remains blocked. Issue #256 remains deferred.

## Security and hardware blockers

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Do not broaden it.

Hardware-dependent Issues #289, #245, #189, #200, #201 and #202 remain pending controlled Raspberry Pi/RS-485 evidence.

`/lockers`, physical cameras, ONVIF/RTSP and NVR remain blocked or unverified by their existing evidence requirements.

## Global hard-stop rules

Stop before destructive data/volume operations, production cutover, hardware writes, secret exposure, mandatory online runtime dependencies, grouped migrations or unsupported physical acceptance claims.
