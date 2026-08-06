# NEXOLAB Current State

Updated: 2026-08-06
Verified product baseline: `21dc6ee26702f42e22e01eea9bca07c1d853ac73`
Active control Work Package: Issue #338 — reconcile dependency policy completion and promote jsdom 30
Branch: `docs/338-reconcile-dependency-policy`
Next Ready Work Package: Issue #253 — focused jsdom 30 migration
Active epic: Issue #326 — Engineering governance, security exception lifecycle and toolchain hardening
Parallel blocked epic: Issue #282 — acquisition software complete; physical Raspberry Pi/RS-485 acceptance pending
Status confidence: high for repository, CI, dependency policy, offline-runtime and security evidence; physical hardware acceptance remains explicitly pending.

## Dependency automation policy completed

Issue #328 / PR #337 was squash-merged as `21dc6ee26702f42e22e01eea9bca07c1d853ac73` from exact verified head `efb685df980735427307902aaa649bd1f9b926f0`.

Completed outcome:

- broad `development-dependencies` and `production-dependencies` groups were retired;
- production runtime dependency updates remain individual Pull Requests;
- development patch/minor updates are grouped only by compatible test, quality, build or React-types verification surface;
- npm SemVer-major automation is disabled;
- `@types/node >=23` is explicitly ignored while Node 22 remains the active `.nvmrc` runtime boundary;
- every major migration requires a dedicated Issue, branch and focused Pull Request;
- deterministic policy validation rejects broad groups, major grouping, missing Node guards, Node/runtime mismatch, production dependencies in dev groups, Dependabot auto-merge paths and missing migration mappings;
- nine policy fixtures, formatting, lint, typecheck, full tests and production build were GREEN;
- `package.json`, `package-lock.json`, dependency versions and runtime closure were unchanged.

PR #271 remains closed unmerged as superseded. PR #272 remains independently open and unselected.

## Ordered engineering-hardening queue

1. **Issue #253 — Ready:** focused jsdom 30 migration.
2. **Issue #254 — queued:** Playwright 1.62.x migration.
3. **Issue #252 — queued:** lint-staged 17 migration.
4. **Issue #255 — queued:** TypeScript 6 transition.

Blocked or deferred:

- **Issue #257:** ESLint 10 remains blocked until a compatible Next.js/plugin graph is demonstrated.
- **Issue #256:** TypeScript 7 remains deferred until TypeScript 6 and ecosystem support are available.

## Security exception boundary

The exact `telemetry-service + libcjson1 + CVE-2026-67216` exception remains narrow and expires on **2026-09-05**. Fixed version remains unavailable in the verified image evidence. Do not broaden or silently renew it.

## Parallel hardware boundary

Issue #289 remains classified:

```text
software verified; hardware performance acceptance pending
```

Hardware-dependent Issues #289, #245, #189, #200, #201 and #202 remain blocked by unavailable controlled Raspberry Pi/RS-485 access. No physical acceptance claim is permitted without real evidence.

## Guardrails for Issue #253

- update only jsdom and the lockfile closure required by that focused migration;
- do not combine Playwright, lint-staged, TypeScript, ESLint, Node types or unrelated package updates;
- confirm Vitest/Testing Library environment compatibility;
- run unit tests, typecheck, lint and production build;
- inspect transitive dependency and offline bundle impact;
- preserve Node 22 and LOCAL_LAN runtime guarantees;
- no product, database, hardware, Modbus, secret or deployment changes.

## Next action

Complete Issue #338 as an exact four-file state-only PR and merge it after GREEN CI. Then execute Issue #253 from current `main` as one focused jsdom 30 migration with targeted test-environment evidence and no unrelated dependency changes.
