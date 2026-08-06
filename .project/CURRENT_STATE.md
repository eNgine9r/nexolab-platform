# NEXOLAB Current State

Updated: 2026-08-06
Verified product baseline: `67b471e44201f7c96ef4e51e7c3904e8c78df323`
Active Work Package: Issue #254 / PR #352 — Playwright 1.62 migration, exact-head verified and ready for final merge audit
Branch: `maint/254-playwright-1-62`
Verified implementation head: `0092a1035af913cbe5be22d2e57db2a3fc257e98`
Next Ready Work Package after merge: Issue #355 — canonical Live Dashboard channel inventory without telemetry-history timeout
Active epic: Issue #326 — Engineering governance, critical operator defects and toolchain hardening
Parallel blocked epic: Issue #282 — acquisition software complete; physical Raspberry Pi/RS-485 acceptance pending

## Reconciled predecessor state

- Issue #350 / PR #351 completed the jsdom state reconciliation and merged as `dff88feee94a6e6334f1e6ea2b515cec5ecff5be` from exact head `7b9cefc21022981d0413e4518c19225dd3430609`.
- Issue #353 / PR #354 fixed prompt Telemetry Service WebSocket disconnect detection and merged as `67b471e44201f7c96ef4e51e7c3904e8c78df323` from exact head `4161f0797c3d56b4839093797df3aca8eaa7adf4`.
- PR #352 is based on that current `main` baseline and is zero commits behind.

## Playwright 1.62 migration verified

Issue #254 / PR #352 moves only the Playwright development toolchain:

- `@playwright/test 1.55.0 → 1.62.0`;
- `playwright 1.55.0 → 1.62.0`;
- `playwright-core 1.55.0 → 1.62.0`;
- repository Node baseline remains `22.23.1`, compatible with Playwright engine `>=20`;
- all 13 Playwright configuration hashes remain unchanged;
- test discovery remains 24 tests across the same files and titles;
- removed `_react`, `_vue`, `:light` and `launch({ devtools })` APIs are absent;
- Chromium installation/cache evidence and package/browser rollback are documented in `docs/maintenance/playwright-1.62-migration.md`;
- screenshots, traces, videos and HTML report contracts remain configured;
- the acquisition invariant instrumentation is scoped per document generation and verifies one active server WebSocket after reload without changing application runtime behavior.

Exact-head `0092a1035af913cbe5be22d2e57db2a3fc257e98` is GREEN for:

- CI, including dependency policy, formatting, lint, typecheck, full unit suite and production build;
- Acquisition Scale Acceptance;
- Authenticated Dashboard Acceptance;
- Refrigeration Browser Acceptance;
- Alerts Browser Acceptance;
- Reports Browser Acceptance;
- Rendered Reports Browser Acceptance;
- Nodes Browser Acceptance;
- Test Sessions Browser Acceptance;
- Security Browser Acceptance;
- Offline Auth Acceptance;
- Offline Bundle, including disconnected startup and update/rollback persistent-data preservation.

## Focused diff and review audit

The implementation comparison against current `main` contains five permanent files:

- `package.json`;
- `package-lock.json`;
- `scripts/validate-playwright-migration.py`;
- `e2e/telemetry-acquisition-invariant.production.e2e.ts`;
- `docs/maintenance/playwright-1.62-migration.md`.

This checkpoint adds only the four authoritative `.project` state files. No temporary workflow remains. Unresolved review threads: zero. Production dependencies, runtime containers, database/schema, acquisition scheduler, hardware and Modbus behavior are unchanged.

## Ordered queue

1. **Issue #355 — Ready after PR #352 merge:** canonical Live Dashboard inventory independent of telemetry-history volume.
2. **Issue #252 — queued:** lint-staged 17 migration.
3. **Issue #255 — queued:** TypeScript 6 transition.

Issue #257 remains blocked. Issue #256 remains deferred.

Open dependency Pull Requests #340, #341, #346 and #347 remain unselected and outside Issue #254. PR #347 becomes obsolete after the Playwright 1.62 merge and must not be merged into this Work Package.

## Security and hardware boundaries

The exact `telemetry-service + libcjson1 + CVE-2026-67216` exception expires on **2026-09-05** and remains unbroadened.

Issue #289 remains `software verified; hardware performance acceptance pending`. Hardware-dependent Issues #289, #245, #189, #200, #201 and #202 remain pending controlled Raspberry Pi/RS-485 evidence.

## Next action

Validate this state-only checkpoint on the exact PR head, mark PR #352 Ready, perform the final current-head/check/review audit, squash merge PR #352, confirm Issue #254 closed, and leave Issue #355 as the sole Next Ready Work Package.
