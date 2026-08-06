# NEXOLAB Blockers

Updated: 2026-08-06

## Active Work Package boundary: jsdom 30

Issue #253 is the sole Next Ready Work Package after Issue #338 merges.

Allowed scope:

- migrate only `jsdom` from major 29 to major 30;
- update the exact lockfile closure required by jsdom;
- inspect Vitest and Testing Library environment compatibility;
- add or adjust targeted tests only where jsdom 30 changes observable test behavior;
- document migration and rollback evidence.

Hard scope boundaries:

- do not combine Playwright, lint-staged, TypeScript, ESLint, Node types or unrelated package updates;
- do not change production dependencies;
- preserve Node 22 and the `@types/node` major 22 boundary;
- no product, runtime API, database, acquisition, hardware, Modbus, secret or deployment changes;
- no automatic merge before exact-head CI and test-environment verification are GREEN.

Required checks:

- dependency-policy validator and fixtures;
- formatting, lint, typecheck, full unit tests and production build;
- focused jsdom/Vitest/Testing Library tests;
- transitive dependency diff and offline closure review;
- rollback by restoring the prior manifest and lockfile state.

## Dependency automation policy completed

Issue #328 / PR #337 is completed. Broad production/development groups are retired. Production runtime updates remain individual; dev patch/minor groups are limited by verification surface; npm major automation and automatic major merge are prohibited; `@types/node >=23` is blocked while Node 22 is active.

PR #271 remains closed unmerged. PR #272 remains open and outside the jsdom migration scope.

## Queued software constraints

Ordered sequence:

```text
#253 jsdom 30
→ #254 Playwright 1.62.x
→ #252 lint-staged 17
→ #255 TypeScript 6
```

Blocked or deferred:

- **#257 ESLint 10:** blocked until a compatible Next.js and plugin graph is demonstrated.
- **#256 TypeScript 7:** deferred until TypeScript 6 is complete and ecosystem support exists.

## cJSON exception: reviewed, narrow and time-bounded

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception remains owned by `platform-security`, affected with no fixed version, and expires on **2026-09-05**. It is not a blocker for current software work, but it must be reviewed again by that date. Do not broaden it.

## Parallel hardware blocker

Issue #289 remains:

```text
software verified; hardware performance acceptance pending
```

Hardware-dependent Issues:

- **#245:** standalone Raspberry Pi acceptance pending;
- **#189:** physical reboot, power-loss and media restore pending;
- **#200:** physical RS-485 topology and single-master proof pending;
- **#201:** LE-01MP cumulative energy validation pending;
- **#202:** extended XJP60D semantics validation pending.

These blockers do not prevent focused jsdom/toolchain work.

## Other product blockers

`/lockers` remains blocked pending concrete inventory, a read-only protocol/API contract, a defined operator workflow and physical evidence.

Physical cameras, ONVIF/RTSP media and NVR remain unverified.

## Global hard-stop rules

Stop before:

- destructive database or persistent-volume operations;
- production/site cutover without explicit approval;
- Modbus, camera, locker or other hardware writes;
- credential exposure or unauthorized secret rotation;
- mandatory internet, cloud, CDN, external API or paid runtime dependencies;
- claiming physical performance acceptance without controlled evidence;
- merging a grouped major dependency migration;
- broadening the cJSON exception beyond the exact image/package/CVE tuple.

## Next action

Merge Issue #338 as an exact four-file state-only checkpoint. Then implement Issue #253 as a focused jsdom 30 migration with targeted test-environment evidence and no unrelated dependency changes.
