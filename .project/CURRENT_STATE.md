# NEXOLAB Current State

Updated: 2026-08-06
Verified product baseline: `5ba8af5b7c9a2bec184b7f39bc15f45d5c3a703e`
Repository state baseline: `0e5b39a93130dfcc8810b28e0ff7348fdd3d0e08`
Active Work Package: Issue #252 / PR #361 — lint-staged 17.3.0 migration, exact-head verified and ready for final merge audit
Branch: `maint/252-lint-staged-17`
Verified implementation head: `ca9291903e61fd4951bb2565a64d2306ef5da824`
Next Ready Work Package after merge: Issue #255 — TypeScript 6 transition line
Active epic: Issue #326 — Engineering governance, critical operator defects and toolchain hardening
Parallel blocked epic: Issue #282 — acquisition software complete; physical Raspberry Pi/RS-485 acceptance pending

## Reconciled predecessor state

- Issue #355 / PR #358 completed the canonical Live Dashboard inventory and merged as `5ba8af5b7c9a2bec184b7f39bc15f45d5c3a703e`.
- Post-merge state reconciliation completed on `main` as `0e5b39a93130dfcc8810b28e0ff7348fdd3d0e08` with GREEN push CI.
- Issue #355 remains `software verified; Raspberry Pi runtime latency acceptance pending`.

## Issue #252 product outcome verified

The development-only staged-file runner moves from `lint-staged 16.4.0` to `17.3.0` on the unchanged Node `22.23.1` baseline.

Verified behavior:

- `.husky/pre-commit` remains `npx lint-staged`;
- JavaScript and TypeScript globs still run `eslint --fix` before `prettier --write`;
- JSON, Markdown, CSS and YAML globs still run `prettier --write`;
- a real production-config TypeScript fixture is formatted and staged successfully;
- partially staged files hide unstaged content from tasks and restore it after success;
- failed tasks restore the original index and unstaged worktree diff;
- an empty staged-file set exits successfully without mutation;
- the harness operates only in disposable Git repositories;
- Node `22.23.1` satisfies the v17 floor `22.22.1`;
- Git `2.54.0` satisfies the v17 floor `2.32.0`.

## Dependency and lockfile boundary

The lockfile resolves `lint-staged 17.3.0` with the development-only direct graph:

- `picomatch ^4.0.5`;
- `string-argv ^0.3.2`;
- `tinyexec ^1.2.4`.

The v16-only CLI rendering and YAML graph is removed. No YAML dependency is needed because NEXOLAB stores lint-staged configuration in `package.json`.

The implementation diff contains exactly four permanent files:

- `package.json`;
- `package-lock.json`;
- `scripts/tests/lint-staged-v17.mjs`;
- `docs/maintenance/lint-staged-17-migration.md`.

No temporary workflow remains.

## Exact-head verification

Exact implementation head `ca9291903e61fd4951bb2565a64d2306ef5da824` is GREEN for:

- CI, including runtime contracts, dependency policy, formatting, lint, typecheck, full tests and production build;
- Authenticated Dashboard Acceptance;
- Refrigeration Browser Acceptance;
- Alerts Browser Acceptance;
- Reports Browser Acceptance;
- Rendered Reports Browser Acceptance;
- Nodes Browser Acceptance;
- Test Sessions Browser Acceptance;
- Security Browser Acceptance;
- Offline Auth Acceptance;
- Offline Bundle, including disconnected startup and update/rollback persistent-data preservation.

Preparation evidence used Node `22.23.1`, Git `2.54.0` and artifact SHA-256 `0265ae89f4c56827171350b6d0dfef79b225048e72e5f9b80f103a828d0b910b`.

## Runtime and safety audit

- production dependencies changed: no;
- production runtime closure changed: no;
- application source changed: no;
- database or migration changed: no;
- cloud or paid runtime dependency added: no;
- acquisition or physical polling changed: no;
- Modbus write: none;
- hardware action: none;
- production/site cutover: none.

## Ordered queue

1. **Issue #255 — next after PR #361 merge:** TypeScript 6 transition line.
2. **Issue #257 — blocked:** ESLint 10 migration.
3. **Issue #256 — deferred:** TypeScript 7 transition.

Open unselected dependency PRs remain #340, #341 and #346. PR #347 remains obsolete.

## Security and hardware boundaries

The exact `telemetry-service + libcjson1 + CVE-2026-67216` exception expires on **2026-09-05** and remains unbroadened.

Hardware-dependent Issues #289, #245, #189, #200, #201 and #202 remain pending controlled Raspberry Pi/RS-485 evidence.

## Next action

Validate this four-file state checkpoint on the exact PR head, mark PR #361 Ready, repeat current-head/check/review/mergeability audit, squash merge PR #361, confirm Issue #252 closure and promote Issue #255 as the sole Next Ready Work Package.
