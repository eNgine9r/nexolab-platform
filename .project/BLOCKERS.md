# NEXOLAB Blockers

Updated: 2026-08-06

## Active Work Package boundary: jsdom 30

Issue #253 is the sole Next Ready Work Package after Issue #345 merges.

Allowed scope:

- update only `jsdom` from major 29 to major 30;
- update only the lockfile closure required by jsdom;
- verify Vitest and Testing Library environment compatibility;
- add targeted tests only where jsdom 30 changes observable test behavior;
- document transitive/offline impact and rollback.

Hard boundaries:

- do not combine Playwright, Vite plugin, React types, lint-staged, TypeScript, ESLint, Node types or production dependency changes;
- preserve Node 22 and `@types/node` major 22;
- do not merge open Dependabot PRs #340 or #341 inside Issue #253;
- no runtime API, database, acquisition, hardware, Modbus, secret or deployment changes.

Required checks:

- dependency-policy validator and 11 fixtures;
- formatting, lint, typecheck, full unit tests and production build;
- focused jsdom/Vitest/Testing Library tests;
- transitive dependency and offline closure review;
- rollback by restoring the prior manifest and lockfile state.

## Dependency lane evidence

Issue #328 / PR #337 established focused lanes. Issue #343 / PR #344 corrected live behavior by excluding Playwright `>=1.56` from automation until Issue #254.

PR status:

- #272 closed unmerged; GitHub branch recreation prevented reopening;
- #339 closed unmerged as an invalid grouped migration;
- #340 open and unselected;
- #341 open and unselected.

## Queued sequence

```text
#253 jsdom 30
→ #254 Playwright 1.62.x
→ #252 lint-staged 17
→ #255 TypeScript 6
```

Issue #257 remains blocked. Issue #256 remains deferred.

## Security and hardware blockers

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Do not broaden it.

Issue #289 remains `software verified; hardware performance acceptance pending`. Hardware-dependent Issues #289, #245, #189, #200, #201 and #202 remain pending controlled Raspberry Pi/RS-485 evidence.

`/lockers`, physical cameras, ONVIF/RTSP and NVR remain blocked or unverified by their existing evidence requirements.

## Global hard-stop rules

Stop before destructive data/volume operations, production cutover, hardware writes, secret exposure, mandatory online runtime dependencies, grouped migrations or unsupported physical acceptance claims.

## Next action

Merge Issue #345 as an exact four-file state-only checkpoint. Then execute Issue #253 as one focused jsdom 30 migration.
