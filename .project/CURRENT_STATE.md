# NEXOLAB Current State

Updated: 2026-08-03
Verified main baseline: `47d5124fd96f54800cf7347ff672297a1d421526`
Verified implementation head: `ec273056c2686d1ac65a702a5831e3abb5c25189`
Active Work Package: Issue #261 — Energy Monitoring verified and ready for protected merge
Parent Product Epic: Issue #260 — complete all NEXOLAB operator pages
Next Ready Work Package: Issue #263 — Live Data telemetry explorer
Status confidence: high for repository state, exact-head CI, authenticated browser evidence and addressed review findings.

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
- stable captured-time cursor pagination for complete 1h, 6h and 24h PostgreSQL history windows;
- bounded renderable-only per-meter downsampling with stable absolute time buckets;
- requested-window chart scaling, including sparse intervals;
- incremental WebSocket history-tail merge without periodic full-window reload;
- wall-clock rolling-window advancement and pruning when telemetry stops;
- future-skew rejection before a live sample can move the chart window;
- metric/unit compatibility validation;
- explicit loading, empty, stale, offline, communication-error, permission-denied and configuration states;
- no silent demo fallback in live mode;
- cumulative energy/kWh remains unavailable pending hardware Issue #201.

No package, Compose, container, database migration, Modbus write, production deployment or hardware action is part of this Work Package.

## Exact-head verification

Verified on implementation head `ec273056c2686d1ac65a702a5831e3abb5c25189`:

- CI run `30834722682` GREEN: formatting, ESLint, strict TypeScript, 197 tests and production build;
- Authenticated Dashboard Acceptance run `30834721743` GREEN: energy latest/history, meter selection, WebSocket update and evidence upload;
- focused tests cover stable pagination, absolute-bucket downsampling, renderable sample selection, node scope, future skew, deduplication and rolling-window pruning;
- review findings for pagination, freshness, window scale, rolling updates, unit compatibility, node scope, query load and long-running history distribution are addressed.

Broad path filters may launch unrelated workflows; they do not expand this focused page merge gate.

## Runtime and hardware evidence

```text
energy page software verified; no hardware operation performed; cumulative energy remains hardware-unverified
```

Actual Raspberry Pi standalone acceptance for #245, physical recovery evidence for #189 and hardware investigations #200–#202 remain soft-blocked by controlled hardware access. No Modbus or hardware write is authorized.

## Next Ready Work Package

Resolve addressed PR #262 review threads and merge with expected-head protection. Then start Issue #263 and replace `/live` with the universal authenticated telemetry explorer. Do not insert deferred dependency migrations between product pages.
