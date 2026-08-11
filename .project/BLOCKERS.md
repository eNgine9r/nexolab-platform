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

## Issue #386 — completed

Issue #386 / PR #399 is merged as `3b34ec321c2453778b20b6bf8e4cc232970e5e1e`.

There is no remaining #386 software blocker. Chart performance was measured on the controlled Raspberry Pi 5 arm64 host and passes the provisional renderer targets. Final exact-head CI was 11/11 GREEN, including Offline Bundle and repository acquisition-invariant integration acceptance.

Controlled physical Device Agent/Modbus request-rate acceptance was not performed by the deterministic foundation harness. It remains an explicit acceptance item in Issue #400, the first production Live Data consumer. This limitation does not authorize acquisition, polling, scheduler, registry, Device Agent, Modbus, or hardware changes.

Hard boundaries:

- no production-page migration in this Work Package;
- no public CDN, cloud renderer, remote font or runtime network import;
- no REST/WebSocket, polling, scheduler, registry, Device Agent or Modbus changes;
- no hardware or Modbus writes;
- keep Raspberry Pi renderer evidence separate from the still-pending physical acquisition invariant.

## Issue #389 — unblocked, Ready and not selected

Issue #389 (administrator-only local NEXOLAB Version Management) remains `status:ready`, but is `ready_not_selected` while #400 is the sole active implementation task.

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
- Issue #400 / PR #402 is the selected active Chart Work Package; no parallel implementation lane is allowed.
- Issue #257 remains blocked by ESLint 10 ecosystem compatibility.
- Issue #256 remains deferred pending TypeScript 7 ecosystem compatibility.

## Security boundary

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Issue #385 did not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, privileged hardware containers or unsupported physical-acceptance claims.

## Issue #400 — software GREEN, physical acceptance pending

There is no known software implementation blocker on the pre-state implementation head. Format, lint, typecheck, 77 files / 344 tests, production build, Authenticated Dashboard, Acquisition Scale and Refrigeration Browser gates are GREEN.

The remaining hard acceptance dependency is physical evidence from the controlled Raspberry Pi after a final exact-head software/offline candidate is frozen:

- equal-duration Device Agent request-rate baseline and chart-active observations;
- eight selected channels and active chart interactions;
- no scheduler/polling/registry change;
- no Modbus or hardware write;
- continued telemetry advancement and acceptable browser behavior.

Do not claim production Live Data Raspberry Pi acquisition-invariant acceptance until that evidence is returned.
