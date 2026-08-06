# NEXOLAB Current State

Updated: 2026-08-06
Verified product baseline: `0f871d91124a70110a1948065554d55af6f183d2`
Active control Work Package: Issue #350 — reconcile jsdom 30 completion and promote Playwright 1.62
Branch: `docs/350-reconcile-jsdom-completion`
Next Ready Work Package: Issue #254 — focused Playwright 1.62.x migration
Active epic: Issue #326 — Engineering governance, security exception lifecycle and toolchain hardening
Parallel blocked epic: Issue #282 — acquisition software complete; physical Raspberry Pi/RS-485 acceptance pending

## Focused dependency lanes

Issue #328 / PR #337 established separate dependency update lanes. Corrective Issue #343 / PR #344 excluded migration-grade Playwright updates from routine automation.

Current rules:

- production runtime updates remain individual Pull Requests;
- development patch/minor groups remain limited to compatible verification surfaces;
- npm SemVer-major automation and automatic major merge remain disabled;
- Node 22 and `@types/node` major 22 remain aligned;
- Playwright `>=1.56` remains excluded from Dependabot until Issue #254 completes;
- deterministic dependency-policy validation remains GREEN with 11 fixtures.

Dependency PR status:

- #272 and #339 are closed unmerged;
- #340 remains open and unselected as the React types patch group;
- #341 remains open and unselected as the individual lucide review.

## jsdom 30 migration completed

Issue #253 / PR #349 was squash merged as `0f871d91124a70110a1948065554d55af6f183d2` from exact head `68242400e9604f6d8fcf446667d6543ec917a862`.

Verified outcome:

- direct development dependency changed only from `jsdom 29.1.1` to exact `30.0.0`;
- jsdom engine `^22.22.2 || ^24.15.0 || >=26.0.0` is compatible with repository Node `22.23.1`;
- deterministic lockfile closure is documented in `docs/maintenance/jsdom-30-migration.md`;
- focused URL, storage, focus, form, event, layout-independent and no-network contract passed 6/6;
- formatting, lint, typecheck, complete Vitest suite and production build are GREEN;
- all browser acceptance workflows, Offline Auth Acceptance and Offline Bundle are GREEN;
- the first Offline Auth attempt failed before acceptance after a Docker image pull, then passed on a same-head failed-job rerun;
- production source, runtime containers and offline delivery closure are unchanged.

## Ordered engineering-hardening queue

1. **Issue #254 — Ready:** Playwright 1.62.x migration.
2. **Issue #252 — queued:** lint-staged 17 migration.
3. **Issue #255 — queued:** TypeScript 6 transition.

Issue #257 remains blocked. Issue #256 remains deferred.

## Security and hardware boundaries

The exact `telemetry-service + libcjson1 + CVE-2026-67216` exception expires on **2026-09-05** and must not be broadened.

Issue #289 remains `software verified; hardware performance acceptance pending`. Hardware-dependent Issues #289, #245, #189, #200, #201 and #202 remain blocked by unavailable controlled Raspberry Pi/RS-485 access.

## Next action

Merge Issue #350 as an exact four-file state-only checkpoint. Then execute Issue #254 as one focused Playwright 1.62.x migration: update Playwright only, preserve all browser acceptance contracts and evidence locations, run every browser workflow plus Offline Bundle, audit browser binary/cache behavior and document rollback.
