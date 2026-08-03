# NEXOLAB Current State

Updated: 2026-08-04
Verified main baseline: `47d5124fd96f54800cf7347ff672297a1d421526`
Verified implementation head: `c8dc696f2b344a6c412e4cbc2a4fddd24a6fccd7`
Active Work Package: Issue #261 — Energy Monitoring verified and ready for protected merge
Parent Product Epic: Issue #260 — complete all NEXOLAB operator pages
Next Ready Work Package: Issue #263 — Live Data telemetry explorer
Status confidence: high for repository state, exact-source-head CI, PostgreSQL telemetry integration, browser acceptance and disconnected offline evidence.

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
- authenticated WebSocket coverage before latest and history snapshots;
- bounded startup event reconciliation;
- complete history pagination against a commit-stable ingestion watermark;
- production `SessionAwareDatabase` insertion barrier and `clock_timestamp()` receipt time;
- bounded renderable-only downsampling with source-derived outage boundaries;
- metric-switch ordering state seeded from retained latest/history samples;
- explicit history error when WebSocket startup reaches a terminal state;
- stale values retained and labelled instead of being converted to empty data;
- requested-window scaling, live tails, wall-clock pruning and future-skew rejection;
- strict metric/unit validation and production node scope;
- no demo fallback and no unverified cumulative `kWh`.

No package, dependency, Compose, container schema migration, Modbus write, production deployment or hardware action is part of this Work Package.

## Exact-source-head verification

Verified on source head `c8dc696f2b344a6c412e4cbc2a4fddd24a6fccd7`:

- CI `30851054746` GREEN;
- Telemetry Service `30851054848` GREEN;
- Authenticated Dashboard Acceptance `30851054739` GREEN;
- Refrigeration Browser Acceptance `30851054803` GREEN;
- Security Browser Acceptance `30851054878` GREEN;
- Test Sessions Browser Acceptance `30851054753` GREEN;
- Reports Browser Acceptance `30851054966` GREEN;
- Offline Auth Acceptance `30851054770` GREEN;
- Offline Bundle `30851054862` GREEN;
- Capacity Release Gate `30851054836` GREEN;
- Device Agent Fleet Acceptance `30851054875` GREEN;
- MQTT TLS Fleet Acceptance `30851054783` GREEN;
- Broker Control Acceptance `30851054893` GREEN;
- Container Supply Chain `30851054778` GREEN;
- Disaster Recovery Domain Completeness `30851054789` GREEN;
- Disaster Recovery TLS Fleet `30851054810` GREEN;
- Disaster Recovery Browser `30851054866` GREEN.

The current commit changes only `.project` source-of-truth files. It requires its own exact-head repository gate before merge; executable source remains the verified `c8dc696…` tree.

## Runtime, offline and hardware evidence

```text
energy page software verified; PostgreSQL/REST/WebSocket/browser/offline bundle verified; no hardware operation performed; cumulative energy remains hardware-unverified
```

Actual Raspberry Pi standalone acceptance for #245, physical recovery evidence for #189 and hardware investigations #200–#202 remain soft-blocked by controlled hardware access. No Modbus or hardware write is authorized.

## Next Ready Work Package

After protected merge of PR #262, create `feat/263-live-telemetry-explorer` from updated `main` and replace `/live` with the universal authenticated telemetry explorer. Do not insert deferred dependency migrations between product pages.
