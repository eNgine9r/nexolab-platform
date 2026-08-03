# NEXOLAB Current State

Updated: 2026-08-03
Verified main baseline: `c3488d383d7633f40f7a723bb0d1ffd97b492973`
Active Work Package: Issue #204 — frontend toolchain migration planning
Status confidence: high for repository package inventory, superseded Dependabot targets, current config coupling and migration dependencies; no toolchain package has changed in this Work Package.

## Completed parent maintenance

Issue #203 / PR #250 is merged as `c3488d383d7633f40f7a723bb0d1ffd97b492973` and closed.

## Issue #204 outcome

The grouped Dependabot PR #160 has been decomposed into focused Work Packages with an explicit migration order and rollback contract.

Current exact development-tool baseline:

- Node selector: `.nvmrc` = `22`;
- declared Node engine: `>=22.0.0`;
- CI observed Node: `22.23.1`;
- `@types/node 20.19.43`;
- TypeScript `5.9.3`;
- ESLint `9.39.5`;
- eslint-config-next `16.2.12`;
- jsdom `29.1.1`;
- lint-staged `16.4.0`;
- Playwright Test `1.55.0`.

The migration matrix is stored in:

```text
docs/maintenance/frontend-toolchain-migration-plan.md
```

## Focused child Work Packages

- #251 — align the Node 22 developer/CI baseline and Node 22 type definitions; **Ready first**.
- #254 — upgrade Playwright 1.55 to 1.62 with browser evidence preservation; queued after #251.
- #252 — upgrade lint-staged 16 to 17; blocked by #251 because v17 requires Node 22.22.1 or newer.
- #253 — migrate jsdom 29 to 30 without changing unit-test semantics; queued after the Node baseline.
- #255 — migrate TypeScript 5.9 to the TypeScript 6 transition line.
- #256 — evaluate TypeScript 7 native compiler only after #255 and confirmed Next/Vitest/ESLint support.
- #257 — upgrade ESLint 9 to 10 only after the resolved Next plugin graph supports ESLint 10.

## Key compatibility decisions

- The proposed `@types/node 26.1.2` is rejected while the supported runtime remains Node 22.
- A direct TypeScript `5.9.3 → 7.0.2` migration is rejected; TypeScript 6 is the mandatory transition gate.
- ESLint 10 is currently blocked because resolved `eslint-plugin-import 2.32.0` declares peer support only through ESLint 9.
- Playwright is treated as a browser-runtime and evidence migration because browser revisions and CI installation are part of acceptance reproducibility.
- jsdom and lint-staged remain separate because they affect different failure domains: unit-test DOM behavior versus Git index/worktree safety.

## Scope completed

- reviewed package manifest, lockfile, `.nvmrc`, TypeScript, ESLint, Vitest and Playwright configuration;
- captured Dependabot PR #160 current/target versions;
- created professional child Issues #251–#257;
- defined migration order, blockers, permitted directories, verification and rollback;
- made no package, lockfile, production source, runtime or hardware change.

## Runtime and hardware status

```text
planning verified; runtime unchanged; no hardware operation performed
```

Actual Raspberry Pi acceptance for Issue #245 and physical recovery evidence for Issue #189 remain pending. Issues #200–#202 remain hardware-blocked. No Modbus or hardware write was performed.

## Next Ready Work Package

Issue #251 — align the Node 22 baseline and `@types/node` before any major tool migration.
