# NEXOLAB Current State

Updated: 2026-08-03
Verified main baseline: `72ecc207af528942396054764c0b33a663727de1`
Active Work Package: Issue #251 — Node 22 baseline and Node 22 type definitions
Status confidence: high for official release metadata, repository workflow inventory and deterministic lockfile movement; exact-head GitHub quality/browser/offline verification is pending.

## Completed planning baseline

Issue #204 planning PR #258 is merged as `72ecc207af528942396054764c0b33a663727de1`. The parent remains open to track child migrations #251–#257.

## Issue #251 outcome

NEXOLAB now has one explicit Node 22 contract:

```text
.nvmrc exact developer/CI version: 22.23.1
package engine: >=22.22.1 <23
@types/node manifest: ^22.20.1
@types/node resolved: 22.20.1
undici-types resolved: 6.21.0
```

Rationale:

- Node 22.23.1 is the latest published Node 22 LTS patch at review time.
- Node 22 remains supported through April 2027.
- The engine floor rejects Node 22 versions older than the future lint-staged 17 requirement.
- The `<23` upper bound prevents accidental use of unsupported odd/current majors.
- Node 26 declarations were rejected while the supported runtime remains Node 22.
- Every searched frontend GitHub workflow already uses `node-version-file: .nvmrc`.
- Primary CI now fails if `node --version` does not exactly match `.nvmrc` and records the npm version.

## Scope completed

- pinned `.nvmrc` from broad `22` to exact `22.23.1`;
- narrowed the package Node engine from `>=22.0.0` to `>=22.22.1 <23`;
- moved `@types/node` from resolved `20.19.43` to `22.20.1`;
- refreshed `package-lock.json` deterministically with only five additions and five deletions;
- preserved `undici-types 6.21.0`;
- added exact Node baseline evidence to `.github/workflows/ci.yml`;
- documented developer, CI, verification and rollback procedures in `docs/maintenance/node22-baseline.md`;
- removed the temporary branch-only lockfile workflow from the final diff.

## Files changed

```text
.nvmrc
package.json
package-lock.json
.github/workflows/ci.yml
docs/maintenance/node22-baseline.md
.project/CURRENT_STATE.md
.project/ACTIVE_SPRINT.json
.project/BLOCKERS.md
.project/LAST_CHECKPOINT.json
```

No production source, browser behavior, backend, Compose, database, telemetry or hardware contract changed.

## Verification pending

- exact Node 22.23.1 assertion;
- deterministic npm installation;
- formatting, ESLint, strict TypeScript, full Vitest and production build;
- all triggered browser acceptance workflows;
- Offline Bundle disconnected startup and update/rollback volume preservation;
- review audit and expected-head merge.

## Runtime and hardware status

```text
build-tool baseline changed; production runtime contract unchanged; no hardware operation performed
```

Actual Raspberry Pi acceptance for Issue #245 and recovery Issue #189 remain pending. Issues #200–#202 remain hardware-blocked. No Modbus or hardware write was performed.

## Next Ready Work Package

After #251 merges, Issue #254 — Playwright browser/evidence migration — is next in the approved toolchain order. Issue #252 also becomes unblocked but remains ordered after #254.
