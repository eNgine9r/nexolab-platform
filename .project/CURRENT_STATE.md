# NEXOLAB Current State

Updated: 2026-08-03
Verified main baseline: `47d5124fd96f54800cf7347ff672297a1d421526`
Verified implementation head: `d8b03f6ed496362c7fa4ff0243ec82ed42c16fad`
Active Work Package: Issue #261 — Energy Monitoring finalization in progress
Parent Product Epic: Issue #260 — complete all NEXOLAB operator pages
Next Ready Work Package: Issue #263 — Live Data telemetry explorer
Status confidence: high for repository state, implementation-head CI, authenticated browser evidence and addressed review findings.

## Product route status

Implemented workflow routes:

- `/` — Overview dashboard;
- `/nodes` — Nodes;
- `/sessions` — Test sessions;
- `/refrigeration` — Refrigeration equipment;
- `/alerts` — Alerts;
- `/reports` — Reports;
- `/energy` — verified LE-01MP Energy Monitoring implementation in PR #262.

Remaining placeholder routes:

- `/live` — next Work Package #263;
- `/equipment-layouts` — Equipment layouts;
- `/lockers` — Smart lockers, blocked pending inventory and read-only protocol scope;
- `/cameras` — Cameras;
- `/equipment` — Equipment and metrology registry;
- `/settings` — Settings.

Optional toolchain migrations #252–#257 remain deferred unless they become a security, support or concrete product-delivery blocker.

## Issue #261 outcome

PR #262 replaces `/energy` with an authenticated operator workspace for KK1 LE-01MP meters W1–W4.

Delivered behavior:

- deterministic W1–W4 cards for Unit IDs 200–203, scoped to production node `edge-01`;
- confirmed voltage, current, frequency, active/reactive/apparent power, power factor and meter temperature;
- authenticated local REST snapshot and WebSocket live updates;
- `telemetry.read` permission is checked before REST or WebSocket traffic starts;
- stable captured-time cursor pagination for complete 1h, 6h and 24h PostgreSQL history windows;
- overlapping timestamp-boundary pagination so rows sharing the page-edge capture time are retained;
- bounded renderable-only per-meter downsampling with stable absolute time buckets and preserved first/latest endpoints;
- raw communication-error records and source-cadence gaps are converted to explicit chart segment boundaries before downsampling, without consuming the renderable point quota;
- requested-window chart scaling, including sparse intervals;
- incremental WebSocket history-tail merge without periodic full-window reload;
- wall-clock rolling-window advancement and pruning when telemetry stops;
- future-skew rejection before a live sample can move the chart window;
- metric/unit compatibility validation;
- explicit loading, empty, stale, offline, communication-error, permission-denied and configuration states;
- no silent demo fallback in live mode;
- cumulative energy/kWh remains unavailable pending hardware Issue #201.

No package, Compose, container, database migration, Modbus write, production deployment or hardware action is part of this Work Package.

## Verified implementation evidence

Verified on implementation head `d8b03f6ed496362c7fa4ff0243ec82ed42c16fad`:

- CI run `30841237042` GREEN: formatting, ESLint, strict TypeScript, 201 Vitest tests and production build;
- Authenticated Dashboard Acceptance run `30841237450` GREEN: energy latest/history, meter selection, WebSocket update and evidence upload;
- focused tests cover stable pagination, shared timestamp boundaries, absolute-bucket downsampling, source-derived outage path breaks, renderable sample selection, endpoint preservation, node scope, future skew, deduplication and rolling-window pruning;
- review findings for pagination, permission gating, freshness, window scale, outage visibility, rolling updates, unit compatibility, node scope, query load and long-running history distribution are addressed.

This state update records the verified implementation SHA; the state-only commit still requires its own repository checks before protected merge.

## Runtime and hardware evidence

```text
energy page software verified; no hardware operation performed; cumulative energy remains hardware-unverified
```

Actual Raspberry Pi standalone acceptance for #245, physical recovery evidence for #189 and hardware investigations #200–#202 remain soft-blocked by controlled hardware access. No Modbus or hardware write is authorized.

## Next Ready Work Package

Complete the state-only gate, resolve the addressed PR #262 review threads and merge with expected-head protection. Then start Issue #263 and replace `/live` with the universal authenticated telemetry explorer. Do not insert deferred dependency migrations between product pages.
