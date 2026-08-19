# NEXOLAB Current State

Updated: 2026-08-19

## Repository and runtime baseline

Accepted product-code baseline on `main` is `f1d13bc2401ba16ef76b95bec5f31e9a9d969c76`, the squash merge of PR #616 — **feat: scale Equipment Registry operator workspace**. State-only reconciliation commits may advance repository HEAD without changing this accepted product baseline; use GitHub `main` for the exact repository HEAD.

The Raspberry Pi source runtime remains deployed at `7a19f53950492a40255c53b1d2018bbdff9466e2`. The persisted local AcquisitionRegistry remains revision 8 with `le01mp-201` intentionally `disabled` while W2 is externally owned. No source deployment was performed by Issues #584 or #586.

## Issue #584 — complete

Temporary Unit 201 exclusion is complete and verified on the real Raspberry Pi. Evidence remains `runtime/deployments/issue-584-20260818T185455Z`.

## Issue #585 — blocked restoration lane

Do not restore Unit 201 until the Product Owner confirms that the external controller no longer owns W2 and explicitly approves any required physical handback. The 2026-08-21 through 2026-08-23 review window is not authorization by itself.

## Issue #586 — complete

Issue #586 is closed `status:done`. PR #592 merged GREEN as `75c6f5471d77d781b124fbd40c33ba924aec26f8`.

Real Raspberry Pi browser-closed evidence proved the acquisition and persistence planes are independent of browser lifetime:

- 60 sampled checks observed zero established browser/API connections on ports 3000/8081/8082;
- AcquisitionRegistry remained `8 -> 8`;
- Device Agent `normal.physical_requests_total` advanced `5049 -> 5392` (`+343`);
- PostgreSQL `telemetry_samples` advanced `4,665,493 -> 4,665,722` (`+229`);
- newest persisted `captured_at` advanced from `2026-08-18 19:18:52.033946+00` to `2026-08-18 19:20:28.276628+00`.

Evidence: `runtime/deployments/issue-586-browser-closed-20260818T191852Z`.

The merged repair now provides:

- one canonical complete-history loader with stable `snapshot_at`, captured-time pagination and event deduplication;
- Live Data reuse of that canonical loader;
- complete persisted Overview bootstrap instead of a single `limit=1000` page;
- deterministic buffered history-to-live reconciliation;
- duplicate and out-of-order tail rejection;
- preservation of newer non-valid samples for truthful Chart System gaps;
- no duplicate route-local latest buffer appended after reconciliation.

Final PR #592 gates on head `6ef7c65b1e0838e75ebaff60d85881f4718cd7c7`:

- Core CI `32179697028`: PASS;
- Authenticated Dashboard Acceptance `32179696964`: PASS;
- Offline Bundle `32179696933`: PASS.

No backend schema, acquisition scheduler, physical polling cadence, dependency graph, Modbus behavior or hardware configuration changed in #586.

## Issue #594 — complete

The Product Owner explicitly authorized provisioning a dedicated read-only LOCAL_LAN identity for the MCP gateway. The account `nexolab-mcp` is active under the supported `laboratory_technician` product role with exactly two explicit grants: `telemetry.read` and `nodes.read`. The password was generated outside Git, was never printed or committed, and remains in a mode-600 local secret file pending any separately approved persistent deployment.

Real Raspberry Pi acceptance on `nexolab-edge-01` proved:

- MCP modern protocol negotiation `2026-07-28`;
- exactly six approved tools, all read-only/non-destructive;
- real `system_health`, node list, node status, latest telemetry, bounded history and active-alarm calls PASS;
- local-session access-token refresh PASS and rotated the access token;
- Device Agent remained healthy and Telemetry API/database/MQTT remained ready with queue depth 0;
- the ephemeral acceptance container was removed and port 8787 returned free;
- no Modbus write, hardware write, site exposure or persistent MCP service enablement occurred.

PR #593 merged GREEN as `b46e518f8769f83ba22c608bacd5a368776e1701` and Issue #594 is closed `status:done`. Persistent systemd enablement, external tunnel/reverse-proxy exposure and production credential relocation remain a separate cutover decision.

## Issue #598 — container supply-chain baseline restored

Issue #598 is closed `status:done`. PR #599 merged GREEN as `b25ae18e196eb84fc56ae951003d0820a22dc579`.

A fresh Container Supply Chain scan surfaced HIGH `CVE-2026-14456` in Debian 13 OpenSSL packages used by Device Agent and telemetry-service. Debian describes the affected path as an OpenSSL QUIC server listener pending-connection exhaustion path. Repository/runtime audit proved neither NEXOLAB image creates a QUIC/HTTP3 listener or accepts QUIC Initial packets.

The repository's existing HIGH/no-fix policy was used without weakening global gates: four exact image/package/CVE decisions were added, owned by `platform-security`, expiring **2026-08-26**. Wildcards, Critical exceptions, `ignore-unfixed`, dependency changes and runtime changes remain forbidden.

Exact PR #599 gates:

- Core CI `32219771902`: PASS;
- Telemetry Service `32219771893`: PASS;
- Container Supply Chain `32219772068`: PASS.

No application runtime, dependency version, database, deployment, Modbus or hardware behavior changed.

## Issue #587 — complete

Issue #587 is closed `status:done`. PR #597 merged GREEN as `84584640246f8985c0c303654def99365c8458c4`.

Saved Live Dashboards now provide view-only `1h`, `6h`, `24h`, `7d`, `30d` and timezone-aware Custom ranges using the canonical complete persisted-history loader from #586. One stable snapshot boundary is shared across selected series, live overlap is reconciled without duplicate replay, and chart reduction occurs only after the complete logical persisted set is established.

CSV export is read-only and generated from persisted telemetry rather than chart/browser memory. It is organization-scoped through canonical node/equipment/channel/metric identity, deterministic, UTF-8, preserves null/invalid quality truthfully, respects the 31-day history bound and fails closed above 100,000 rows instead of truncating.

Final exact-head gates:

- Core CI `32220599757`: PASS;
- Telemetry Service `32220599759`: PASS;
- Authenticated Dashboard Acceptance `32220599864`: PASS;
- Offline Bundle `32220599751`: PASS;
- Acquisition Scale Acceptance `32220599830`: PASS;
- Container Supply Chain `32220599753`: PASS;
- all other triggered browser/fleet/capacity/DR gates: PASS.

No acquisition-registry mutation, physical polling cadence change, Modbus write, hardware write, migration, dependency upgrade or mandatory cloud runtime dependency was introduced.

## Issue #608 — complete CI reliability interrupt

Issue #608 is closed `status:done`. PR #609 merged GREEN as `3e13800f413eb2255b992b6ff9f3aec935acf602`. The blocking browser gates now use a preinstalled GitHub-runner Chrome executable and install only Playwright's ffmpeg artifact for retained failure video; they no longer invoke `playwright install --with-deps chromium` or live Ubuntu APT dependency installation.

Exact-head #609 gates on `6ee2919d784048bf737e6d6f67427a08be0a228d`:

- Core CI `32237282201`: PASS;
- Authenticated Dashboard Acceptance `32237282110`: PASS;
- Refrigeration Browser Acceptance `32237282106`: PASS;
- Acquisition Scale Acceptance `32237282105`: PASS.

No application runtime, dependency version, database, acquisition, Modbus or hardware behavior changed.

## Issue #611 — complete browser-readiness reliability interrupt

Issue #611 is closed `status:done`. PR #612 merged GREEN as `57908efc7f27598f5a991e2a009aaab0f6b92676`. The terminal Live Data retry acceptance no longer treats an aged seed sample as proof of a live stream: it first proves exactly one routed WebSocket transport, publishes a fresh local telemetry sample, and only then asserts the truthful Live UI state. The Authenticated Dashboard workflow now also triggers whenever this acceptance file changes.

Exact-head #612 gates on `60bc5ac749abe52107d358b85e4302f29f6d46be`:

- Core CI `32242665739`: PASS;
- Authenticated Dashboard Acceptance `32242665728`: PASS;
- Refrigeration Browser Acceptance `32242665724`: PASS;
- Acquisition Scale Acceptance `32242665721`: PASS.

No product runtime, acquisition, database, dependency, Modbus or hardware behavior changed.

## Issue #588 — complete

Issue #588 is closed. PR #602 merged GREEN as `62e94ea02b2f4c7da03d1a5fa11cc1e24459f6f7` after the Energy history surface was migrated to the canonical NEXOLAB Chart System. The final implementation preserves persisted history and real gaps, adds adaptive date/time axes, unit-aware Y axes, exact pointer/keyboard inspection and deterministic visible-series handling without changing acquisition behavior.

Exact-head `0da49e2ac1037efab78367cf76e201ce5a5133a4` gates:

- Core CI `32246136302`: PASS;
- Refrigeration Browser Acceptance `32246136115`: PASS;
- Authenticated Dashboard Acceptance `32246136164`: PASS after rerun of an unrelated Equipment URL-filter timing failure;
- Offline Bundle `32246136097`: PASS.

Local Raspberry Pi worktree checks on the exact branch content also passed `format:check`, lint, typecheck and 18 focused chart/energy tests. The diff contains no package/lockfile, service, infrastructure, script or workflow changes. No acquisition mutation, Modbus write, hardware write, dependency upgrade or mandatory cloud runtime dependency was introduced.

## Issue #604 — complete

Issue #604 is closed. PR #616 merged GREEN as `f1d13bc2401ba16ef76b95bec5f31e9a9d969c76`. The Equipment Registry now publishes progressive results while bounded chamber loads continue, keeps partial failures truthful, bounds large inventories to 80 rendered asset rows per page, adds deterministic sorting/grouping/risk filters, persists only local operator view preferences, and provides a non-blocking read-only inspector.

Measured evidence did **not** justify a second universal asset persistence model or new universal backend endpoint; existing canonical repositories remain authoritative.

Final verification included:

- Core CI `32263137097`: PASS;
- Refrigeration Browser Acceptance `32263134788`: PASS;
- Offline Bundle `32263135467`: PASS;
- local focused Equipment Registry production browser acceptance with large seeded inventory: PASS;
- local acquisition-invariant browser acceptance: 3/3 PASS;
- full local unit suite: 113 files / 513 tests PASS;
- production build: PASS.

No dependency, backend schema, acquisition cadence, Modbus, hardware, runtime deployment or mandatory cloud dependency changed. Issue #615 separately tracks the non-blocking default Compose project-name defect in the authenticated-dashboard runner.

## Issue #605 — implementation complete, CI-blocked

Issue #605 implementation is published as draft PR #621 from `feat/605-equipment-metadata-editing`, exact head `71ce5cf4c1a25f77f841dbf6162fdc3605643923`. Local backend/frontend/browser verification for the scoped metadata workflow is complete, including zero acquisition-registry mutations and protected transport identity checks.

PR #621 cannot merge while required checks are red. The two blocking failures reproduce on exact `main` and are tracked separately:

- #620 breaks Core CI `Quality and build` through date-drifting persisted Live Dashboard unit fixtures;
- #619 breaks Authenticated Dashboard Acceptance through the repeated-navigation bounded read-model assertion.

Issue #605 is therefore `status:blocked` only on repository-baseline CI reliability prerequisites; its focused product diff remains isolated.

## Issue #620 — active CI reliability interrupt

Exact-main reproduction proved the persisted Live Dashboard tests were tied to fixed `2026-08-18` telemetry while the `24h` preset correctly anchors to real current time. Once wall-clock time moved beyond that fixture window, persisted samples were truthfully filtered and the live-tail event appeared stale/out-of-window.

The scoped repair freezes only `Date` inside `use-live-dashboard-telemetry.test.ts` at the fixture anchor. Production range, history and reconciliation logic are unchanged. Local verification on the #620 branch currently passes:

- focused hook test twice: 2/2 PASS each run;
- `npm run typecheck`: PASS;
- touched ESLint: PASS;
- `npm run format:check`: PASS;
- `npm test`: 113 files / 513 tests PASS, including lint-staged regression;
- `npm run build`: PASS with a normal local dependency tree.

## Reliability findings #618 and #619

Issue #618 tracks a Saved Dashboard CSV browser-download acceptance defect that reproduces on exact `main` locally. It did not fail PR #621 GitHub Authenticated Dashboard run and is not the immediate dependency for #605.

Issue #619 is `status:ready` and is the next CI reliability prerequisite after #620. PR #621 Authenticated Dashboard Acceptance completed 15/16 tests and failed only the repeated-navigation active-alert read bound (`expected 1, received 2`). Exact-main focused navigation acceptance is also unstable, so #619 remains isolated from #605.

## Current execution boundary

Active Work Package: **Issue #620 — Restore persisted Live Dashboard history bootstrap and live-tail reconciliation tests**. This is a CI reliability interrupt required to restore Core CI on exact `main`.

Dependency sequence is **#620 → #619 → resume #605 / PR #621 → #606 → #607 → #589 → #590**. Issue #618 remains a separate high-priority Saved Dashboard export reliability lane and must not be mixed into the #620/#619 fixes.

Issue #585 remains independently blocked on physical W2/Unit 201 handback. No second RS-485 adapter installation, wiring move or hardware cutover is authorized.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
