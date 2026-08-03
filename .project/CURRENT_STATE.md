# NEXOLAB Current State

Updated: 2026-08-03
Verified main baseline: `47d5124fd96f54800cf7347ff672297a1d421526`
Verified implementation head: `6738277080db3388ef241468c0a28e3204ac7f98`
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
- WebSocket subscription established before the initial REST latest snapshot;
- bounded startup event buffer reconciled with the snapshot so capture cycles between REST and subscription cannot be lost;
- startup communication errors retained as per-meter pending breaks even before historical points exist;
- stable captured-time pagination with overlapping page-boundary timestamps;
- bounded per-meter absolute-bucket downsampling with first/latest endpoint preservation;
- source-derived, cross-callback and first-bucket outage segmentation;
- requested-window scaling, incremental live tails, wall-clock pruning and future-skew rejection;
- metric/unit compatibility, production node scope and explicit stale/offline/error states;
- no demo fallback and no unverified cumulative `kWh`.

No package, Compose, container, database migration, Modbus write, production deployment or hardware action is part of this Work Package.

## Verified implementation evidence

Verified on implementation head `6738277080db3388ef241468c0a28e3204ac7f98`:

- CI run `30844693579` GREEN: formatting, ESLint, strict TypeScript, full Vitest suite and production build;
- Authenticated Dashboard Acceptance run `30844693548` GREEN: energy latest/history, meter selection, WebSocket update and evidence upload;
- Refrigeration Browser Acceptance run `30844693576` GREEN: existing refrigeration operator flow remains intact;
- focused coverage includes buffered snapshot-window events, startup pending outages, shared timestamp boundaries, endpoint preservation, source/pending/first-bucket outage markers, future skew, deduplication and rolling-window pruning.

This state update records the verified implementation SHA; the state-only commit still requires its own repository checks before protected merge.

## Runtime and hardware evidence

```text
energy page software verified; no hardware operation performed; cumulative energy remains hardware-unverified
```

Actual Raspberry Pi standalone acceptance for #245, physical recovery evidence for #189 and hardware investigations #200–#202 remain soft-blocked by controlled hardware access. No Modbus or hardware write is authorized.

## Next Ready Work Package

Complete the state-only gate, resolve the addressed PR #262 review threads and merge with expected-head protection. Then start Issue #263 and replace `/live` with the universal authenticated telemetry explorer. Do not insert deferred dependency migrations between product pages.
