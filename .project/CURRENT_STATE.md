# NEXOLAB Current State

Updated: 2026-08-03
Verified main baseline: `47d5124fd96f54800cf7347ff672297a1d421526`
Verified implementation head: `0f2cf40dbb0a4d7763cf2ee8948770910fbbb03d`
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

- authenticated local REST latest/history and WebSocket live telemetry;
- `telemetry.read` permission gating before network traffic begins;
- stable captured-time cursor pagination with overlapping page-boundary timestamps;
- bounded per-meter absolute-bucket downsampling with preserved first/latest endpoints;
- source-derived outage segments from raw communication errors and cadence gaps;
- persistent pending outage state across separate WebSocket error/recovery callbacks;
- first-bucket outage markers transferred to the next retained point without losing the earliest endpoint;
- requested-window chart scaling, incremental live tails, wall-clock pruning and future-skew rejection;
- metric/unit compatibility, node `edge-01` scope and explicit stale/offline/error states;
- no demo fallback and no unverified cumulative `kWh`.

No package, Compose, container, database migration, Modbus write, production deployment or hardware action is part of this Work Package.

## Verified implementation evidence

Verified on implementation head `0f2cf40dbb0a4d7763cf2ee8948770910fbbb03d`:

- CI run `30843193403` GREEN: formatting, ESLint, strict TypeScript, full Vitest suite and production build;
- Authenticated Dashboard Acceptance run `30843193556` GREEN: energy latest/history, meter selection, WebSocket update and evidence upload;
- Refrigeration Browser Acceptance run `30843192945` GREEN: existing refrigeration operator flow remains intact;
- focused coverage includes shared timestamp boundaries, endpoint preservation, source/pending outage markers, first-bucket marker transfer, future skew, deduplication and rolling-window pruning.

This state update records the verified implementation SHA; the state-only commit still requires its own repository checks before protected merge.

## Runtime and hardware evidence

```text
energy page software verified; no hardware operation performed; cumulative energy remains hardware-unverified
```

Actual Raspberry Pi standalone acceptance for #245, physical recovery evidence for #189 and hardware investigations #200–#202 remain soft-blocked by controlled hardware access. No Modbus or hardware write is authorized.

## Next Ready Work Package

Complete the state-only gate, resolve addressed PR #262 review threads and merge with expected-head protection. Then start Issue #263 and replace `/live` with the universal authenticated telemetry explorer. Do not insert deferred dependency migrations between product pages.
