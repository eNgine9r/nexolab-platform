# NEXOLAB Node Tooling and Container Baseline

Updated: 2026-08-03
Issue: #251
Parent: #204
Baseline main: `72ecc207af528942396054764c0b33a663727de1`

## Decision

NEXOLAB uses two explicit supported Node lines for different responsibilities:

```text
Developer and GitHub Actions baseline: Node 22.23.1
Supported Node 22 floor: >=22.22.1 <23
Dashboard container build/runtime line: >=24 <25
Node type declarations: @types/node 22.20.1
npm engine floor: >=10.0.0
```

## Rationale

- Node 22.23.1 is the exact developer and GitHub Actions baseline.
- The Node 22 floor satisfies the planned lint-staged 17 requirement while preventing accidental Node 23 use.
- The offline dashboard Dockerfile already uses the supported Node 24 container line. The package engine must preserve that production build contract.
- The package engine therefore admits supported even-numbered Node 22 and Node 24 lines while rejecting Node 23 and Node 25.
- `@types/node` remains on Node 22 so strict typechecking cannot silently depend on Node 24- or Node 26-only APIs.
- The proposed Node 26 type declarations are rejected while the developer and CI compatibility floor remains Node 22.

Primary references:

- https://nodejs.org/en/blog/release/v22.23.1/
- https://nodejs.org/en/about/previous-releases
- https://www.npmjs.com/package/@types/node?activeTab=versions
- https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/node

## Repository contract

### Developer and CI selector

`.nvmrc` contains:

```text
22.23.1
```

Recommended developer setup:

```bash
nvm install
nvm use
node --version
npm --version
```

Expected Node output:

```text
v22.23.1
```

All searched frontend workflows use:

```yaml
node-version-file: .nvmrc
```

The primary CI workflow also fails if `node --version` differs from `.nvmrc` and records the npm version in job evidence.

### Package engine

`package.json` describes the actual supported build lines:

```json
{
  "engines": {
    "node": ">=22.22.1 <23 || >=24 <25",
    "npm": ">=10.0.0"
  }
}
```

This range deliberately distinguishes two responsibilities:

- Node 22.23.1 for developer machines and GitHub Actions;
- Node 24 for the existing dashboard container build/runtime.

It does not authorize an automatic Node 24 developer migration or Node 26 runtime change.

### Type declarations

The manifest and lockfile use:

```text
manifest: @types/node ^22.20.1
resolved: @types/node 22.20.1
undici-types: 6.21.0
```

Keeping Node 22 declarations is conservative: application source must remain valid on the lowest supported Node line even when a container build runs on Node 24.

## Offline failure discovered and resolved

The first candidate engine range admitted only Node 22:

```text
>=22.22.1 <23
```

Offline Bundle correctly failed during `npm prune --omit=dev` because the dashboard image uses Node 24. The corrected dual-line engine preserves both:

- exact Node 22 developer/CI verification;
- the established Node 24 offline image build.

This failure was not bypassed or reclassified. The package contract was corrected and the complete exact-head cascade must rerun.

## Verification

Required exact-head checks:

```text
Node 22.23.1 baseline assertion
npm install --no-audit
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
```

Because package/lockfile metadata and container engine compatibility are affected, also require:

- every triggered browser acceptance workflow;
- Offline Bundle connected build;
- disconnected archive load/start with pull disabled;
- update/rollback persistent-volume preservation;
- review audit and expected-head merge.

## Runtime and offline impact

- No production browser API, backend API, database, telemetry or hardware contract changes.
- The existing Node 24 dashboard image remains supported.
- No CDN, external telemetry, cloud API, online license or paid runtime dependency is added.
- Persistent-volume names and disconnected installation behavior remain unchanged.

## Rollback

Restore the previous metadata pair:

```text
.nvmrc: 22
package engine: >=22.0.0
@types/node manifest: ^20
@types/node lock: 20.19.43
```

Regenerate `package-lock.json` from the previous repository baseline and rerun the complete quality/build, browser and Offline Bundle gates.

Rollback does not require database migration, persistent-volume deletion, hardware action or production cutover.
