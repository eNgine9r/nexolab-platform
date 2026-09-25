# NEXOLAB Frontend Toolchain Migration Plan

Updated: 2026-09-25
Parent Issue: #204
Superseded grouped Pull Request: #160
Reconciled baseline main: `fb985bb0125bef42c1cb519c786a65fa51986ffb`

## Objective

Split the grouped frontend development-tool upgrades into focused, reversible Work Packages while preserving the NEXOLAB quality gates:

```text
format → lint → strict typecheck → unit tests → production build → browser acceptance → offline bundle
```

No toolchain migration may introduce a mandatory online runtime dependency, alter production behavior silently, weaken diagnostics or combine unrelated major versions.

## Current repository baseline

As of this reconciliation:

- Node exact CI/developer baseline: `22.23.1`;
- declared Node engine: `>=22.22.1 <23 || >=24 <25`;
- `@types/node`: Node 22 line (`^22.20.1` in `package.json`);
- TypeScript: `^6.0.3`;
- ESLint: major 9;
- eslint-config-next: `16.2.12`;
- jsdom: `30.0.0`;
- lint-staged: `^17.3.0`;
- Playwright Test: exact `1.62.0`;
- Vitest uses the global jsdom environment;
- browser acceptance uses separate Playwright configs and evidence directories;
- ESLint uses flat config and `--max-warnings=0`;
- TypeScript uses strict, no-emit, bundler module resolution and the Next plugin.

The old grouped proposal from PR #160 is historical only and must not be revived as one combined migration.

## Reconciled migration status

### 1. Node 22 baseline and Node types — Issue #251

Status: **Completed**.

Accepted outcome:

- explicit Node 22 floor/baseline;
- developer and CI assumptions aligned;
- Node types moved to the Node 22 line rather than the unsafe Node 26 proposal;
- later lint-staged migration prerequisites satisfied.

### 2. Playwright 1.62 — Issue #254

Status: **Completed**.

Accepted outcome:

- browser/evidence migration performed as a focused Work Package;
- dedicated NEXOLAB configs/evidence semantics preserved;
- `@playwright/test` current repository baseline is `1.62.0`.

### 3. lint-staged 17 — Issue #252

Status: **Completed**.

Accepted outcome:

- repository moved to lint-staged 17 after Node baseline alignment;
- current production ESLint → Prettier staged-file command ordering and globs remain explicit;
- isolated Git integration coverage exists under the repository test harness.

### 4. jsdom 30 — Issue #253

Status: **Completed**.

Accepted outcome:

- unit-test DOM environment migrated to jsdom 30;
- test semantics were preserved through focused regression coverage;
- current repository baseline is `jsdom 30.0.0`.

### 5. TypeScript 6 transition — Issue #255

Status: **Completed**.

Accepted outcome:

- the repository completed the TypeScript 6 transition before any TypeScript 7 evaluation;
- strict/noEmit/Next generated-type behavior remains part of the verification contract;
- current compiler declaration is `^6.0.3`.

### 6. TypeScript 7 native compiler — Issue #256

Status: **Deferred — not Ready**.

The prerequisite TypeScript 6 migration is now complete, but the remaining ecosystem-support gate is still material. TypeScript 7 itself is available and Next.js exposes an experimental TypeScript CLI integration path, but that alone does not satisfy NEXOLAB acceptance. The current TypeScript-aware ESLint/parser toolchain does not provide TypeScript 7 as a normal supported baseline; upstream `typescript-eslint` currently detects/warns on TypeScript 7 rather than treating it as the established supported compiler line.

Do not start #256 until the selected Next.js, Vitest/Vite and ESLint/parser integrations explicitly support the chosen TypeScript 7 line and correctness can be compared against this verified TypeScript 6 baseline.

### 7. ESLint 10 — Issue #257

Status: **Blocked — not Ready**.

`typescript-eslint` has ESLint 10 support, but the official `eslint-plugin-import` release used by the current Next/plugin graph still lacks an official ESLint 10-compatible release/peer baseline. NEXOLAB will not bypass that constraint by silently replacing the plugin with a fork/preview package as part of #257.

Start #257 only after the resolved `eslint-config-next`/import-plugin graph officially supports ESLint 10 and the existing zero-warning rule intent can be preserved.

## Executed order

The currently executable migration sequence is complete:

```text
#251 Node 22 baseline and Node types       ✅ completed
  ↓
#254 Playwright browser/evidence migration ✅ completed
  ↓
#252 lint-staged pre-commit migration      ✅ completed
  ↓
#253 jsdom unit-test DOM migration         ✅ completed
  ↓
#255 TypeScript 6 transition               ✅ completed
```

Future compatibility-gated follow-ups:

```text
#256 TypeScript 7 evaluation  ⏸ deferred until ecosystem support is explicit
#257 ESLint 10 migration      ⏸ blocked until the official plugin graph is compatible
```

There is no immediate Ready migration from this plan as of 2026-09-25.

## Verification contract per future child

Every future migration Work Package must define and actually run the smallest relevant checks plus:

```text
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
```

Additional gates are selected by affected surface:

- TypeScript: generated Next types and all TS-based configs;
- ESLint: nested config lookup and full zero-warning lint;
- any package/lockfile change: Offline Bundle disconnected startup and update/rollback preservation;
- any browser/runtime change: the routed browser acceptance and evidence workflows.

## Rollback rules

- one dependency group per commit history and PR;
- preserve the previous exact manifest and lockfile pair;
- browser upgrades also record the previous browser-cache/install contract;
- configuration changes must be reversible without product-data migration;
- never delete persistent Docker volumes or evidence;
- never use toolchain migration to alter production/site configuration.

## Primary references

- superseded grouped proposal: GitHub PR #160;
- completed Node baseline: #251;
- completed Playwright migration: #254;
- completed lint-staged migration: #252;
- completed jsdom migration: #253;
- completed TypeScript 6 transition: #255;
- deferred TypeScript 7 evaluation: #256;
- blocked ESLint 10 migration: #257.

## Completion definition for parent Issue #204

The parent completion definition is satisfied as of 2026-09-25:

- every currently executable migration child through TypeScript 6 is completed;
- #256 and #257 are explicitly deferred/blocked with current compatibility reasons and have no unsafe partial change;
- no grouped major migration remains authorized.

Issue #204 may therefore close as a completed planning/execution parent. Issues #256 and #257 remain independently open and must be re-evaluated when their compatibility conditions change.
