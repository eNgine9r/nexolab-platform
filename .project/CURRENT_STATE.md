# NEXOLAB Current State

Updated: 2026-08-06
Verified product baseline: `5cfba8b58080cca22105934b94110e961c5b3098`
Active control Work Package: Issue #345 — reconcile dependency lane completion and promote jsdom 30
Branch: `docs/345-reconcile-dependency-lanes`
Next Ready Work Package: Issue #253 — focused jsdom 30 migration
Active epic: Issue #326 — Engineering governance, security exception lifecycle and toolchain hardening
Parallel blocked epic: Issue #282 — acquisition software complete; physical Raspberry Pi/RS-485 acceptance pending

## Dependency update lanes completed

Issue #328 / PR #337 was merged as `21dc6ee26702f42e22e01eea9bca07c1d853ac73` from exact head `efb685df980735427307902aaa649bd1f9b926f0`.

Corrective Issue #343 / PR #344 was merged as `5cfba8b58080cca22105934b94110e961c5b3098` from exact head `eec26d7f5daeed510eab2df551fac011b5e3f05a` after live Dependabot evidence exposed a migration-grade Playwright grouping defect.

Final policy:

- production runtime updates are individual Pull Requests;
- development patch/minor groups are limited to compatible verification surfaces;
- npm SemVer-major automation is disabled;
- Node 22 and `@types/node` major 22 remain aligned;
- Playwright `>=1.56` is excluded from automation until focused Issue #254;
- automatic major merge is prohibited;
- deterministic validation includes 11 GREEN positive/negative fixtures;
- `package.json`, `package-lock.json`, dependency versions and runtime closure were unchanged.

Live PR evidence:

- #272 closed unmerged after Dependabot deleted/recreated its branch; GitHub rejected reopening and the limitation is documented;
- #339 closed unmerged because it grouped Playwright 1.62 with an unrelated patch;
- #340 remains open and unselected as a valid React-types patch group;
- #341 remains open and unselected as the individual lucide replacement.

## Ordered engineering-hardening queue

1. **Issue #253 — Ready:** jsdom 30 migration.
2. **Issue #254 — queued:** Playwright 1.62.x migration.
3. **Issue #252 — queued:** lint-staged 17 migration.
4. **Issue #255 — queued:** TypeScript 6 transition.

Issue #257 remains blocked; Issue #256 remains deferred.

## Security and hardware boundaries

The exact `telemetry-service + libcjson1 + CVE-2026-67216` exception expires on **2026-09-05** and must not be broadened.

Issue #289 remains `software verified; hardware performance acceptance pending`. Hardware-dependent Issues #289, #245, #189, #200, #201 and #202 remain blocked by unavailable controlled Raspberry Pi/RS-485 access.

## Next action

Merge Issue #345 as an exact four-file state-only checkpoint. Then execute Issue #253 as one focused jsdom 30 migration: update only jsdom and its required lockfile closure, verify Vitest/Testing Library behavior, run full CI/build and review offline/transitive impact.
