# NEXOLAB Blockers

Updated: 2026-08-06

## Issue #252 completion boundary

Issue #252 / PR #361 is merged and closed.

Verified software outcome:

- merge SHA: `323f384297bba5a0fd734b7e47704fbd360454a4`;
- final verified head: `958fab7c84b717860138b60fddac6f60be52934a`;
- all 11 exact-head workflows were GREEN;
- lint-staged resolves from `16.4.0` to `17.3.0` under Node `22.23.1`;
- Git `2.54.0` satisfies the v17 minimum `2.32.0`;
- globs, ESLint-before-Prettier order and the Husky hook are unchanged;
- production-config processing, partial-stage restoration, failed-task rollback and empty-stage behavior pass;
- Offline Bundle proves disconnected startup and update/rollback persistent-data preservation;
- production dependencies and runtime closure are unchanged;
- no database, acquisition, hardware, Modbus or production/site action occurred.

No Issue #252 blocker remains.

## Active queue boundary: Issue #255

Issue #255 is the sole Ready package.

Required outcome:

- verify the currently available official TypeScript 6 transition release before selecting an exact version;
- update TypeScript only with deterministic lockfile movement;
- preserve strict mode, no-emit verification, bundler module resolution, isolated modules and Next.js integration;
- classify and fix every new diagnostic without broad ignores, `any` baselines, weakened strictness or unrelated cleanup;
- keep ESLint, Vitest, Next.js production build and all TypeScript Playwright configurations operational;
- retain Offline Bundle GREEN;
- document rollback.

Hard boundaries:

- no TypeScript 7 native compiler;
- no ESLint 10, React, Next.js or unrelated dependency migration;
- no broad source refactor unrelated to TypeScript 6 diagnostics;
- no production deployment, secrets, hardware actions or Modbus writes.

## Raspberry Pi acceptance boundary

Issue #355 remains:

```text
software verified; Raspberry Pi runtime latency acceptance pending
```

Its physical acceptance does not block Issue #255.

## Dependency lanes

Open unselected dependency PRs: #340, #341 and #346.

PR #347 remains obsolete because Playwright 1.62 already merged through Issue #254 / PR #352.

Closed unmerged dependency PRs: #272 and #339.

Ordered sequence:

```text
#255 TypeScript 6
```

Issue #257 remains blocked. Issue #256 remains deferred.

## Security and hardware blockers

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Do not broaden it.

Hardware-dependent Issues #289, #245, #189, #200, #201 and #202 remain pending controlled Raspberry Pi/RS-485 evidence.

`/lockers`, physical cameras, ONVIF/RTSP and NVR remain blocked or unverified by their existing evidence requirements.

## Global hard-stop rules

Stop before destructive data/volume operations, production cutover, hardware writes, secret exposure, mandatory online runtime dependencies, grouped migrations or unsupported physical acceptance claims.
