# NEXOLAB Node 22 Baseline

Updated: 2026-08-03
Issue: #251
Parent: #204
Baseline main: `72ecc207af528942396054764c0b33a663727de1`

## Decision

NEXOLAB frontend development and GitHub Actions use:

```text
Recommended exact Node: 22.23.1
Supported engine range: >=22.22.1 <23
Node type declarations: @types/node 22.20.1
npm engine floor: >=10.0.0
```

## Rationale

- Node 22 is an LTS line in Maintenance status and remains supported through April 2027.
- Node 22.23.1 is the latest published Node 22 LTS patch at review time.
- The exact `.nvmrc` value makes developer and CI resolution reproducible.
- The package engine floor rejects older Node 22 patches that do not satisfy the planned lint-staged 17 migration requirement.
- The `<23` upper bound prevents accidental use of unsupported odd/current majors.
- `@types/node` remains on the Node 22 declaration line. The proposed Node 26 types are not accepted while the runtime contract is Node 22.
- The latest published Node 22 declarations at review time are `22.20.1`.

Primary references:

- https://nodejs.org/en/blog/release/v22.23.1/
- https://nodejs.org/en/about/previous-releases
- https://www.npmjs.com/package/@types/node?activeTab=versions
- https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/node

## Repository contract

### Developer selector

`.nvmrc` contains the exact supported version:

```text
22.23.1
```

Recommended setup:

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

### Package engine

`package.json` rejects unsupported runtime majors:

```json
{
  "engines": {
    "node": ">=22.22.1 <23",
    "npm": ">=10.0.0"
  }
}
```

### Type declarations

The development dependency and lockfile remain on Node 22:

```text
manifest: @types/node ^22.20.1
resolved: @types/node 22.20.1
undici-types: 6.21.0
```

This prevents Node 26-only APIs from appearing valid during strict typechecking.

### GitHub Actions

NEXOLAB workflows use:

```yaml
node-version-file: .nvmrc
```

The primary CI workflow additionally verifies that `node --version` exactly matches `.nvmrc` before dependency installation and records the npm version in job evidence.

## Verification

Required exact-head checks:

```text
Node baseline assertion
npm install --no-audit
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
```

Because package and lockfile metadata change, also require:

- all triggered browser acceptance workflows;
- Offline Bundle disconnected load/start;
- update/rollback persistent-volume preservation;
- review audit and expected-head merge.

## Runtime and offline impact

- Node and `@types/node` remain development/build dependencies.
- No production browser API, backend API, Compose service or hardware contract changes.
- No CDN, external telemetry, cloud API, online license or paid runtime dependency is added.
- Existing offline runtime images and persistent-volume identities remain unchanged.

## Rollback

Restore the previous exact metadata pair:

```text
.nvmrc: 22
package engine: >=22.0.0
@types/node manifest: ^20
@types/node lock: 20.19.43
```

Then regenerate `package-lock.json` using the previous repository baseline and rerun the complete quality/build and Offline Bundle gates.

Rollback does not require database migration, persistent-volume deletion, hardware action or production cutover.
