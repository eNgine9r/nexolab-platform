# NEXOLAB Current State

Updated: 2026-08-03
Verified main baseline: `72ecc207af528942396054764c0b33a663727de1`
Active Work Package: Issue #251 — Node tooling and type-definition baseline
Status confidence: high for official release metadata, repository workflow inventory, deterministic lockfile movement and the exact Offline Bundle failure diagnosis; corrected exact-head verification is pending.

## Completed planning baseline

Issue #204 planning PR #258 is merged as `72ecc207af528942396054764c0b33a663727de1`. The parent remains open to track child migrations #251–#257.

## Issue #251 outcome

NEXOLAB now has an explicit dual-line Node contract:

```text
.nvmrc exact developer/CI version: 22.23.1
package engine: >=22.22.1 <23 || >=24 <25
@types/node manifest: ^22.20.1
@types/node resolved: 22.20.1
undici-types resolved: 6.21.0
```

Responsibilities:

- Node 22.23.1 is the exact developer and GitHub Actions baseline.
- Node 22.22.1 is the minimum supported Node 22 patch and satisfies the future lint-staged 17 floor.
- The existing dashboard offline image uses the Node 24 container line, which remains supported.
- Node 23 and Node 25 are rejected.
- Source typechecking remains conservative on Node 22 declarations even when the container build uses Node 24.
- Node 26 declarations remain rejected.
- Every searched frontend GitHub workflow uses `node-version-file: .nvmrc`.
- Primary CI fails if `node --version` does not exactly match `.nvmrc` and records the npm version.

## Offline failure and correction

The first candidate incorrectly restricted the package engine to Node 22 only. Offline Bundle correctly failed during dashboard-image `npm prune --omit=dev` because the established offline Dockerfile uses Node 24.

The failure was not bypassed. The engine contract was corrected to admit supported Node 22 and Node 24 lines, the lockfile was regenerated, and the complete exact-head cascade must rerun.

## Scope completed

- pinned `.nvmrc` from broad `22` to exact `22.23.1`;
- changed the package engine from `>=22.0.0` to `>=22.22.1 <23 || >=24 <25`;
- moved `@types/node` from resolved `20.19.43` to `22.20.1`;
- refreshed `package-lock.json` deterministically;
- preserved `undici-types 6.21.0`;
- added exact Node baseline evidence to `.github/workflows/ci.yml`;
- documented developer, CI, container, verification and rollback procedures in `docs/maintenance/node22-baseline.md`;
- removed both temporary branch-only lockfile workflows from the final diff.

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

No production source, browser behavior, backend, Compose, database, telemetry or hardware contract changed. The existing Node 24 dashboard image contract is preserved.

## Verification pending

- exact Node 22.23.1 developer/CI assertion;
- deterministic npm installation;
- formatting, ESLint, strict TypeScript, full Vitest and production build;
- all triggered browser acceptance workflows;
- Offline Bundle connected build on Node 24;
- disconnected startup and update/rollback volume preservation;
- review audit and expected-head merge.

## Runtime and hardware status

```text
developer/CI baseline aligned; existing Node 24 container runtime preserved; no hardware operation performed
```

Actual Raspberry Pi acceptance for Issue #245 and recovery Issue #189 remain pending. Issues #200–#202 remain hardware-blocked. No Modbus or hardware write was performed.

## Next Ready Work Package

After #251 merges, Issue #254 — Playwright browser/evidence migration — is next in the approved toolchain order. Issue #252 also becomes unblocked but remains ordered after #254.
