# NEXOLAB Blockers

Updated: 2026-08-11

## Issue #385 — completed

Issue #385 / PR #390 is merged as `e0b124e9a0152be50966daa131974b3543651e87`.

Its software and Raspberry Pi acceptance gates are complete:

```text
final exact-head CI: 19/19 GREEN
Raspberry Pi acceptance: PASS
architecture: aarch64 / linux/arm64
production build: PASS
local-auth browser tests: 4 passed
persistence/recreation test: 1 passed
acceptance exit_code: 0
```

There is no remaining #385 blocker.

## Issue #389 — unblocked and Ready

Issue #389 (administrator-only local NEXOLAB Version Management) is now `status:ready`.

Its #385 dependency is satisfied because `project_versions.manage` and the administrator-only authorization boundary are canonical on `main`.

Before implementation, inventory the repository's existing deployment/update/rollback/offline contracts and narrow the permitted implementation paths. Do not create a second deployment engine.

Hard stops specific to #389 remain:

- target package/version identity cannot be verified;
- required PostgreSQL backup fails;
- migration or rollback compatibility is unknown;
- rollback would require destructive schema/data downgrade;
- named volumes or edge SQLite cannot be preserved;
- secrets would be exposed;
- action would cross into unapproved production/site cutover.

## Remaining prepared sequence

After the selected version-management lane:

```text
#369 -> #366 -> #289
```

Other known boundaries:

- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #386 remains Ready but not selected.
- Issue #257 remains blocked by ESLint 10 ecosystem compatibility.
- Issue #256 remains deferred pending TypeScript 7 ecosystem compatibility.

## Security boundary

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Issue #385 did not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, privileged hardware containers or unsupported physical-acceptance claims.
