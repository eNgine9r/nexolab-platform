# NEXOLAB Current State

Updated: 2026-08-20

## Repository and runtime baseline

Accepted product-code baseline is `ad2a49473c9798dc8e4f374ec031b2144c0606e2`, the GREEN merge of PR #621 — **feat(equipment): add permissioned metadata editing**. Exact repository `main` is `d773bbb08fd9924ede9c2c6c0bfbea68ae720dc2`, the post-#605 state reconciliation commit #625; no later product PR has merged.

The Raspberry Pi repository checkout and `origin/main` are both `d773bbb08fd9924ede9c2c6c0bfbea68ae720dc2`. The active Dashboard was recovered after the #626 freeze from the previously verified #605 artifact, which was proven product-identical to `d773bbb` outside `.project/**`. The real Device Agent AcquisitionRegistry is currently revision **9** with **33 poll-eligible targets**; the monitored XJP60D set is `104-03`, `106-01`, `106-04`, `108-01`, `108-02`, `126-04`. `le01mp-201` remains intentionally disabled while W2 is externally owned.

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

## Issue #620 — complete controlled reliability exception

PR #622 merged as `9f54faa25c2f6c0d7e0f1bf84e772c0e3fa6ab6f` after the explicitly approved one-time Product Owner exception. Core CI `32296176882` and Offline Bundle `32296176711` were GREEN; the only RED check was Authenticated Dashboard `32296176725`, independently proven to be Issue #619. Before approval, a synthetic `main + #620 + #619` head passed format, lint, typecheck, 514/514 tests, lint-staged and production build. #620 changed no production runtime behavior and is complete.

## Issue #619 — complete GREEN

PR #623 merged fully GREEN as `4ab72f1c3c51a8822723e9a53c4881b0415ee9c1` from exact head `dea599312172cab8132782f7db2fef2239db2e02`. The repair makes telemetry-navigation acceptance deterministic without relaxing the <=1,000 ms warm-route budget, isolates dashboard acceptance from the real Raspberry Pi Device Agent, retains the shared equipment catalog under bounded structural-cache pressure, and cleans #604 scale-only Equipment fixtures after their own proof.

Final exact-head GitHub gates:

- Core CI `32329087115`: PASS;
- Authenticated Dashboard Acceptance `32329087128`: PASS;
- Refrigeration Browser Acceptance `32329087103`: PASS;
- Disaster Recovery Browser `32329087134`: PASS;
- Offline Bundle `32329087175`: PASS.

Rebased local verification also passed 113/113 test files / 514/514 tests, format, lint, typecheck, lint-staged, production build and focused navigation 3/3. Acquisition evidence kept physical request rate around 20 requests/s with discovery delta 0, configuration mutation delta 0, GET-only Device Agent control calls and WebSocket maximum 1 per document. No Modbus write, hardware write or runtime deployment occurred.

Issue #618 remains an independent Saved Dashboard CSV browser-download reliability lane. It reproduced in one local full matrix, while the final #623 GitHub Authenticated Dashboard Acceptance passed, so it does not block the current Equipment product lane.

## Issue #605 — complete GREEN

PR #621 merged fully GREEN as `ad2a49473c9798dc8e4f374ec031b2144c0606e2` from exact head `5e7ff9bdc34cf3fa2c495ada51608116b3b52e3b`. The Equipment workspace now supports permission-gated administrative metadata editing while keeping Modbus/acquisition identity read-only. Measurement-device and physical-sensor mutations are narrow, organization-scoped, audited and optimistic-concurrency protected; refrigeration editing reuses its canonical repository contract.

Final exact-head GitHub gates were GREEN: Core CI `32334582905`, Telemetry service `32334582949`, Authenticated Dashboard `32334582859`, Refrigeration Browser `32334582959`, Security Browser `32334582871`, Offline Bundle `32334582980`, and Offline Auth `32334583017` after one transient first-attempt runner failure. Local rebased verification passed backend metadata tests 5/5, focused frontend tests 18/18, full Vitest 114/114 files / 519/519 tests, format, typecheck and lint-staged. No package/lock changes, Modbus writes, hardware writes or runtime deployment occurred.

The Raspberry Pi verification host was hard-reset after repository-wide ESLint exhausted host resources; post-reboot repository/worktree integrity was clean. Full repository lint/build is therefore kept on GitHub CI for heavy gates on this 4 GiB host.

## Issue #606 — implementation checkpoint paused by critical #627

Issue #606 remains open `status:in-progress` with recoverable branch `feat/606-local-lan-discovery` at `af52c19ff67538f21399e258fbcc6aeef7ba96ab`. Its last published checkpoint had clean Git state, Equipment discovery frontend tests 3/3 PASS, and discovery repository tests 2/2 failing with `EquipmentDiscoveryRepositoryError: invalid_response`. It is paused, not abandoned, while the Product Owner-prioritized critical monitoring defect #627 is repaired.

## Issue #626 — active critical Raspberry Pi deployment safety prerequisite

Issue #626 is the current Work Package on `fix/626-atomic-pi-deploy`. Two previous in-place frontend builds hard-froze the 4 GiB Raspberry Pi, so the active dashboard must never be used as a build workspace again. The implementation now keeps each candidate in an immutable release directory, bounds the fallback container build with memory/CPU/PID limits, verifies a candidate on an isolated loopback port before activation, and restores the previous systemd unit if activation or health checks fail.

The missing off-device artifact consumer is now implemented locally. `deploy-current-head-raspberry-pi.sh --frontend-artifact PATH` verifies exact source SHA, SHA-256 artifact/package evidence, package/lock identity, baked LOCAL_LAN public runtime values, repository Node baseline, and the real installed runtime dependency snapshot. With an artifact supplied it skips `npm ci` and `next build` on the Pi and snapshots the verified `.next` plus matching existing `node_modules` into the candidate release. Artifact verification failure is fail-closed and does not silently fall back to a local build.

Local verification is GREEN: frontend/deployment tests **17/17**, version-management/update pytest regression **42/42**, YAML parse, shell parse, `git diff --check`, and a real-Pi runtime dependency snapshot (`543` installed lock entries matched the target lock and `npm ls --omit=dev --all` passed). Exact-head PR/CI and isolated portable-artifact Pi acceptance are still required before #626 can merge.

## Issue #627 — software/CI GREEN, Pi acceptance waiting on #626

PR #628 for Issue #627 is open on exact head `6596bc25292a5badea13b0e4dea84804f3301ba1`. The monitoring/display ownership repair is implemented and all triggered exact-head GitHub gates are GREEN, including Core CI/production build `32363682430`, Authenticated Dashboard acquisition invariant `32363682812`, Offline Bundle `32363682463`, Acquisition Scale `32363682454`, Refrigeration Browser, Device Agent Fleet, Container Supply Chain, MQTT/DR TLS and Edge image.

The remaining #627 acceptance is deliberately blocked on #626: a real Raspberry Pi Overview-only visibility change must run the exact #627 production artifact without compiling Next.js on the Pi, then prove registry revision/configured targets remain unchanged and monitored PostgreSQL telemetry continues with the browser closed. No Modbus write, hardware write or site cutover is authorized.

## Current execution boundary

Current Work Package: **Issue #626 — Make Raspberry Pi frontend deployment atomic and resource-safe**.

Next action: publish the artifact-consumer checkpoint, open the focused #626 PR, require exact-head CI and its portable recovery artifact, then perform isolated Raspberry Pi candidate acceptance without touching the active Dashboard. After GREEN #626 merge, build the exact #627 artifact through the merged reusable workflow, complete the real Overview acquisition invariant, merge #627, reconcile state, and resume #606 from `af52c19ff67538f21399e258fbcc6aeef7ba96ab`.

Planned sequence: **#626 → #627 Pi acceptance/merge → resume #606 → #607 → #589 → #590**. #618 remains an independent Saved Dashboard CSV reliability lane; #585 remains blocked on physical W2/Unit 201 handback.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
