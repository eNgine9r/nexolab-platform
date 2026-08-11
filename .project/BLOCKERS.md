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

## Issue #386 — active; acquisition-invariant acceptance pending

Issue #386 is `status:in-progress` on `feat/386-chart-domain-renderer-benchmark` after the Product Owner priority override.

There is no software implementation blocker. Chart performance was measured on the controlled Raspberry Pi 5 arm64 host and passes the provisional renderer targets. The physical acquisition invariant cannot be proven by disconnected deterministic fixtures and remains pending a controlled Device Agent/Modbus request-rate test.

Local format, lint, typecheck, full unit/component tests, production build and the disconnected deterministic browser benchmark are GREEN. Publication, exact-head GitHub CI, the repository Offline Bundle job and review-thread audit are still pending and must not be reported as complete before they run.

Hard boundaries:

- no production-page migration in this Work Package;
- no public CDN, cloud renderer, remote font or runtime network import;
- no REST/WebSocket, polling, scheduler, registry, Device Agent or Modbus changes;
- no hardware or Modbus writes;
- keep Raspberry Pi renderer evidence separate from the still-pending physical acquisition invariant.

## Issue #389 — unblocked, Ready and not selected

Issue #389 (administrator-only local NEXOLAB Version Management) remains `status:ready`, but is `ready_not_selected` while #386 is the sole active implementation task.

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

The existing runtime sequence remains preserved and is not replanned by #386:

```text
#369 -> #366 -> #289
```

Other known boundaries:

- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #386 is the selected active Work Package.
- Issue #257 remains blocked by ESLint 10 ecosystem compatibility.
- Issue #256 remains deferred pending TypeScript 7 ecosystem compatibility.

## Security boundary

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Issue #385 did not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, privileged hardware containers or unsupported physical-acceptance claims.
