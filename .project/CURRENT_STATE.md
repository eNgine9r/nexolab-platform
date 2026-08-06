# NEXOLAB Current State

Updated: 2026-08-06
Verified product and state baseline: `323f384297bba5a0fd734b7e47704fbd360454a4`
Completed Work Package: Issue #252 / PR #361 — lint-staged 17.3.0 migration
Verified implementation head: `958fab7c84b717860138b60fddac6f60be52934a`
Next Ready Work Package: Issue #255 — TypeScript 6 transition line
Active epic: Issue #326 — Engineering governance, critical operator defects and toolchain hardening
Parallel blocked epic: Issue #282 — acquisition software complete; physical Raspberry Pi/RS-485 acceptance pending

## Issue #252 completed

Issue #252 / PR #361 merged into `main` as `323f384297bba5a0fd734b7e47704fbd360454a4`.

The development-only staged-file runner moved from `lint-staged 16.4.0` to `17.3.0` on the unchanged Node `22.23.1` baseline.

Completed behavior:

- `.husky/pre-commit` remains `npx lint-staged`;
- JavaScript and TypeScript globs still run `eslint --fix` before `prettier --write`;
- JSON, Markdown, CSS and YAML globs still run `prettier --write`;
- production-config TypeScript processing formats and stages the intended result;
- partially staged files hide unstaged content from tasks and restore it after success;
- failed tasks restore the original index and unstaged worktree diff;
- an empty staged-file set exits successfully without mutation;
- the acceptance harness operates only in disposable Git repositories;
- Node `22.23.1` and Git `2.54.0` satisfy the lint-staged v17 runtime floors.

## Dependency and lockfile boundary

The lockfile resolves `lint-staged 17.3.0` with a development-only graph. The v16-only CLI rendering and YAML graph was removed. No YAML dependency is needed because NEXOLAB stores lint-staged configuration in `package.json`.

No production dependency, application source, runtime container, database, acquisition or physical polling behavior changed.

## Verification evidence

Final exact head `958fab7c84b717860138b60fddac6f60be52934a` was GREEN for all 11 triggered workflows:

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

Offline Bundle proved disconnected startup and update/rollback persistent-data preservation.

Preparation evidence used Node `22.23.1`, Git `2.54.0` and artifact SHA-256:

```text
0265ae89f4c56827171350b6d0dfef79b225048e72e5f9b80f103a828d0b910b
```

Two initial final-head Offline Auth attempts failed before migrations at Docker container startup. A fresh exact-head run passed migration round-trip and disconnected local-auth acceptance, classifying those failures as runner transients rather than product or dependency regressions.

Permanent migration evidence is recorded in `docs/maintenance/lint-staged-17-migration.md`.

## Next Ready Work Package: Issue #255

Issue #255 is open, assigned to `eNgine9r` and labeled:

- `area:devops`;
- `dependencies`;
- `priority:high`;
- `status:ready`.

Required outcome:

- verify the currently available official TypeScript 6 transition release before changing versions;
- update TypeScript only with deterministic lockfile movement;
- preserve strict mode and no-emit verification;
- classify every new diagnostic and fix it without broad ignores, `any` baselines or weakened strictness;
- keep Next.js production build, Vitest and Playwright TypeScript configuration operational;
- retain Offline Bundle GREEN;
- document rollback.

## Ordered queue

1. **Issue #255 — Ready:** TypeScript 6 transition line.
2. **Issue #257 — blocked:** ESLint 10 migration.
3. **Issue #256 — deferred:** TypeScript 7 native compiler transition.

Open unselected dependency PRs remain #340, #341 and #346. PR #347 remains obsolete.

## Security and hardware boundaries

The exact `telemetry-service + libcjson1 + CVE-2026-67216` exception expires on **2026-09-05** and remains unbroadened.

Issue #355 remains `software verified; Raspberry Pi runtime latency acceptance pending`. Hardware-dependent Issues #289, #245, #189, #200, #201 and #202 remain pending controlled Raspberry Pi/RS-485 evidence.

## Next action

Begin Issue #255 from current `main` in one focused feature branch and Pull Request. Do not combine TypeScript 7, ESLint 10, React, Next.js or unrelated dependency changes with the TypeScript 6 transition.
