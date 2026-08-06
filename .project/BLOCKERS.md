# NEXOLAB Blockers

Updated: 2026-08-06

## Active Work Package boundary: Playwright 1.62.x

Issue #254 is the sole Next Ready Work Package after Issue #350 merges.

Allowed scope:

- update only `@playwright/test` from 1.55.x to exact 1.62.x;
- update only the lockfile closure required by Playwright;
- review official 1.56–1.62 breaking changes and browser revisions;
- preserve existing Playwright config names, `testMatch` contracts, single-worker behavior, timeouts and evidence locations unless a required change is explicitly documented;
- verify browser installation/cache behavior and every browser acceptance workflow;
- verify Offline Bundle and document browser-cache rollback.

Hard boundaries:

- do not combine React types, lucide, Vite plugin, lint-staged, TypeScript, ESLint, Node types, jsdom or production dependency changes;
- preserve Node 22 and `@types/node` major 22;
- do not merge open Dependabot PRs #340 or #341 inside Issue #254;
- do not rewrite selectors or product behavior unless Playwright 1.62 removed an API and the focused compatibility change is documented;
- no runtime API, database, acquisition, hardware, Modbus, secret or production/site deployment changes.

Required checks:

- dependency-policy validator and 11 fixtures;
- all Playwright configs load without compatibility warnings;
- all existing browser acceptance suites pass on the exact PR head;
- screenshots, traces, videos and HTML evidence remain available on failure;
- formatting, lint, typecheck, full unit tests and production build;
- deterministic browser installation/cache review;
- Offline Bundle and update/rollback preservation;
- rollback by restoring the prior manifest/lockfile and cleaning/reinstalling browser binaries.

## Completed jsdom migration evidence

Issue #253 / PR #349 merged as `0f871d91124a70110a1948065554d55af6f183d2` from exact head `68242400e9604f6d8fcf446667d6543ec917a862`.

Verified:

- exact `jsdom 30.0.0` on Node `22.23.1`;
- focused DOM contract GREEN 6/6;
- complete Vitest suite and production build GREEN;
- browser acceptance, Offline Auth Acceptance and Offline Bundle GREEN;
- production runtime/offline closure unchanged.

## Dependency lane evidence

Issue #328 / PR #337 established focused lanes. Issue #343 / PR #344 excluded Playwright `>=1.56` from automation until Issue #254.

PR status:

- #272 and #339 closed unmerged;
- #340 open and unselected;
- #341 open and unselected.

## Queued sequence

```text
#254 Playwright 1.62.x
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

Merge Issue #350 as an exact four-file state-only checkpoint. Then execute Issue #254 as one focused Playwright 1.62.x migration.
