# NEXOLAB Current State

Updated: 2026-08-06
Verified product baseline: `5831190f9714236b53f362234785639e22267477`
Verified Work Package: Issue #255 / PR #362 — TypeScript 6 transition compiler
Verified implementation head: `8c43439e1ab34e398f4b3bf2a9c8545e4386b956`
Next Ready Work Package after GREEN merge: Issue #357 — immediate refrigeration image/layout/marker hydration
Active epic: Issue #326 — Engineering governance, critical operator defects and toolchain hardening
Parallel hardware/runtime track: Issue #282

## Issue #255 verified ready for merge

Issue #255 / PR #362 upgrades the development-only TypeScript compiler from resolved `5.9.3` to `6.0.3`.

Verified scope:

- root `devDependencies.typescript` changes from `^5` to `^6.0.3`;
- deterministic lockfile movement is limited to the root package entry and `node_modules/typescript`;
- `tsconfig.json` is unchanged;
- application source, tests, Playwright configs and Vitest config are unchanged;
- `strict`, `noEmit`, `isolatedModules`, `module: esnext`, `moduleResolution: bundler` and explicit `target: ES2017` remain unchanged;
- no `ignoreDeprecations`, broad `types` list, `any` baseline, mass `ts-expect-error` or weakened compiler boundary was added;
- TypeScript 7, ESLint 10, React, Next.js and unrelated refactoring remain outside scope.

## Diagnostic evidence

Diagnostic workflow `31099428290` compared the same repository state:

| Check                    | TypeScript 5.9.3 | TypeScript 6.0.3 |
| ------------------------ | ---------------: | ---------------: |
| `tsc --noEmit` exit code |              `0` |              `0` |
| New diagnostics          |                — |              `0` |

Diagnostic artifact SHA-256:

```text
2a8c38909db85d4844613ea6d7c24039bd42c4aea8e9363a781fd3ed83eb098f
```

Migration workflow `31100010365` verified deterministic lockfile scope, compiler invariants, all root Playwright configs, all `e2e/*.ts`, `vitest.config.ts`, ESLint, 67 Vitest files / 300 tests, lint-staged integration, Playwright package loading and Next.js production build. Migration artifact SHA-256:

```text
b4db5cc6b3abcaa9df721a95dc95b809f186d1b0a9cc7a23be30033717f096b7
```

Publisher workflow `31100231787` reproduced the migration and full quality cascade, committed the three permanent files and removed the temporary workflow.

Permanent evidence is recorded in `docs/maintenance/typescript-6-migration.md`.

## Exact-head verification

Final implementation head `8c43439e1ab34e398f4b3bf2a9c8545e4386b956` is GREEN for all 11 triggered workflows:

- CI;
- Authenticated Dashboard Acceptance;
- Refrigeration Browser Acceptance;
- Alerts Browser Acceptance;
- Reports Browser Acceptance;
- Rendered Reports Browser Acceptance;
- Nodes Browser Acceptance;
- Test Sessions Browser Acceptance;
- Security Browser Acceptance;
- Offline Auth Acceptance;
- Offline Bundle.

Offline Bundle proved disconnected startup and update/rollback persistent-data preservation. TypeScript remains development-only and does not change the production runtime closure.

## Next Ready Work Package: Issue #357

Issue #357 is open, assigned to `eNgine9r`, labeled `priority:critical` and `status:ready`.

Required product outcome:

- hydrate refrigeration image, saved layout and sensor placements as one coherent structural snapshot;
- keep the previous valid snapshot visible during background reconciliation;
- render configured no-sample channels with explicit unknown/stale state;
- deduplicate equipment-scoped reads and retain a bounded organization-scoped cache;
- separate structural rendering from latest telemetry latency;
- prove cold and warm route performance and repeated route-cycle request counts;
- preserve editing, image lifecycle, binding lifecycle, optimistic concurrency and physical polling boundaries;
- classify completion as `software verified; Raspberry Pi perceived-latency acceptance pending` until real Pi evidence exists.

## Ordered queue

1. **Issue #357 — Ready, priority critical:** refrigeration structural snapshot and warm hydration.
2. **Issue #245 — Ready parallel runtime track:** standalone offline Raspberry Pi loopback operation; physical acceptance remains required.
3. **Issue #257 — blocked:** ESLint 10 migration.
4. **Issue #256 — deferred:** TypeScript 7 native compiler transition.

Open unselected dependency PRs remain #340, #341 and #346. PR #347 remains obsolete.

## Security and hardware boundaries

The exact `telemetry-service + libcjson1 + CVE-2026-67216` exception expires on **2026-09-05** and remains unbroadened.

Issue #355 remains `software verified; Raspberry Pi runtime latency acceptance pending`. Hardware-dependent Issues #289, #245, #189, #200, #201 and #202 still require controlled Raspberry Pi/RS-485 evidence.

## Next action

Complete the immutable-head audit for PR #362, merge only while exact head `8c43439e1ab34e398f4b3bf2a9c8545e4386b956` remains current and GREEN, reconcile the actual merge SHA, then activate Issue #357 in one focused branch and Pull Request.
