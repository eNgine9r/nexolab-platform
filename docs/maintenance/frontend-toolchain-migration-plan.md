# NEXOLAB Frontend Toolchain Migration Plan

Updated: 2026-08-03
Parent Issue: #204
Superseded grouped Pull Request: #160
Baseline main: `c3488d383d7633f40f7a723bb0d1ffd97b492973`

## Objective

Split the grouped frontend development-tool upgrades into focused, reversible Work Packages while preserving the current NEXOLAB quality gates:

```text
format → lint → strict typecheck → unit tests → production build → browser acceptance → offline bundle
```

No toolchain migration may introduce a mandatory online runtime dependency, alter production behavior silently, weaken diagnostics or combine unrelated major versions.

## Repository baseline

- Node selector: `.nvmrc` contains `22`.
- Declared Node engine: `>=22.0.0`.
- CI currently resolves Node `22.23.1`.
- TypeScript: resolved `5.9.3`.
- ESLint: resolved `9.39.5`.
- eslint-config-next: resolved `16.2.12`.
- jsdom: resolved `29.1.1`.
- lint-staged: resolved `16.4.0`.
- Playwright Test: exact `1.55.0`.
- Node types: resolved `20.19.43`.
- Vitest uses a global jsdom environment.
- Browser acceptance uses separate Playwright configs and evidence directories.
- ESLint uses flat config and `--max-warnings=0`.
- TypeScript uses strict, no-emit, bundler module resolution and the Next plugin.

## Superseded grouped targets

Dependabot PR #160 attempted one lockfile change containing:

- Playwright `1.55.0 → 1.62.0`;
- Node types `20.19.43 → 26.1.2`;
- ESLint `9.39.5 → 10.8.0`;
- eslint-config-next `16.2.10 → 16.2.12`;
- jsdom `29.1.1 → 30.0.0`;
- lint-staged `16.4.0 → 17.2.0`;
- TypeScript `5.9.3 → 7.0.2`.

The eslint-config-next patch was already completed separately with the production framework security work. The remaining majors must not be recombined.

## Compatibility decisions

### 1. Node 22 baseline and Node types — Issue #251

Status: **Ready first**.

Decision:

- keep the supported runtime on Node 22;
- select an explicit supported Node 22 patch/floor;
- align package engines and CI/developer selectors;
- move `@types/node` to the Node 22 type line;
- reject the proposed Node 26 type line while runtime remains Node 22.

Reason:

- lint-staged 17 requires Node 22.22.1 or newer;
- the current broad engine declaration allows older unsupported Node 22 patches;
- Node 26 types would expose APIs unavailable on the supported runtime.

### 2. Playwright 1.62 — Issue #254

Status: **Queued after #251**.

Decision:

- treat Playwright as a browser-runtime and evidence migration, not a routine package update;
- preserve all dedicated NEXOLAB configs, single-worker execution, evidence paths and failure artifacts;
- run every browser acceptance workflow and Offline Bundle.

Risk:

- versions 1.56–1.62 change browser revisions and remove deprecated APIs/selectors;
- browser installation and cache behavior affect CI reproducibility.

### 3. lint-staged 17 — Issue #252

Status: **Blocked by #251**.

Decision:

- migrate only after the Node floor is explicit and compatible;
- preserve current globs and ESLint/Prettier ordering;
- test index rollback and unstaged-change preservation.

### 4. jsdom 30 — Issue #253

Status: **Queued after the Node baseline**.

Decision:

- isolate the unit-test DOM environment from Vitest, Testing Library and production dependencies;
- add focused behavior tests before accepting changed DOM semantics;
- do not rewrite assertions merely to accommodate regressions.

### 5. TypeScript 6 transition — Issue #255

Status: **Queued after the independent test-tool migrations**.

Decision:

- migrate from 5.9 to the official TypeScript 6 transition line first;
- classify every new diagnostic;
- preserve strictness, noEmit, Next generated types and bundler resolution;
- reject broad suppressions.

### 6. TypeScript 7 native compiler — Issue #256

Status: **Blocked by #255 and ecosystem support**.

Decision:

- reject the direct `5.9.3 → 7.0.2` jump;
- require a verified TypeScript 6 baseline;
- require explicit Next.js, Vitest/Vite and ESLint integration support;
- compare correctness before performance.

### 7. ESLint 10 — Issue #257

Status: **Blocked by the resolved Next plugin graph**.

Decision:

- do not update while any resolved plugin rejects ESLint 10;
- current `eslint-plugin-import 2.32.0` declares peer support only through ESLint 9;
- preserve flat config, zero warnings and narrow NEXOLAB-specific overrides;
- wait for a compatible eslint-config-next/plugin graph.

## Execution order

Only one implementation Work Package is active at a time.

```text
#251 Node 22 baseline and Node types
  ↓
#254 Playwright browser/evidence migration
  ↓
#252 lint-staged pre-commit migration
  ↓
#253 jsdom unit-test DOM migration
  ↓
#255 TypeScript 6 transition
  ↓
#256 TypeScript 7 evaluation (only when unblocked)

#257 ESLint 10 remains blocked until plugin peers support it
```

The order may skip a soft-blocked task and continue to the next independent Ready child, but it must never merge two migration groups into one PR.

## Verification contract per child

Every child Issue must define and actually run the smallest relevant checks plus:

```text
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
```

Additional gates are selected by affected surface:

- Node baseline: CI version evidence and install reproducibility;
- Playwright: every browser acceptance and evidence upload;
- lint-staged: isolated temporary Git-repository hook tests;
- jsdom: focused DOM behavior tests plus full Vitest;
- TypeScript: generated Next types and all TS-based configs;
- ESLint: nested config lookup and full zero-warning lint;
- any package/lockfile change: Offline Bundle disconnected startup and update/rollback preservation.

## Rollback rules

- one dependency group per commit history and PR;
- preserve the previous exact manifest and lockfile pair;
- browser upgrades also record the previous browser-cache/install contract;
- configuration changes must be reversible without product-data migration;
- never delete persistent Docker volumes or evidence;
- never use toolchain migration to alter production/site configuration.

## Primary references

- Dependabot grouped proposal: GitHub PR #160.
- TypeScript 6 transition notes: https://www.typescriptlang.org/docs/handbook/release-notes/typescript-6-0.html
- TypeScript release notes: https://www.typescriptlang.org/docs/handbook/release-notes/overview
- ESLint 10 migration guide: https://eslint.org/docs/latest/use/migrate-to-10.0.0
- Playwright release notes: https://playwright.dev/docs/release-notes
- lint-staged migration guide: https://github.com/lint-staged/lint-staged/blob/main/MIGRATION.md
- jsdom releases: https://github.com/jsdom/jsdom/releases

## Completion definition for parent Issue #204

Issue #204 remains open as the tracking parent until every applicable child is either:

- merged with GREEN exact-head evidence; or
- explicitly deferred/blocked with a current compatibility reason and no unsafe partial change.

The immediate Ready Work Package is Issue #251.
