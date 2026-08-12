# Issue #404 — Saved Live Dashboard canonical Chart System migration audit

Updated: 2026-08-12

## Final classification

**PASS — completed and squash-merged.**

Issue #404 / PR #410 merged into `main` as `d4068e28402aa113f4485dc3afecb1f8eb44bd7b`.

Final product head before squash merge: `ce2356cfb142e241684a7a68a08969cab884c2f5`.

Base before merge: `f3462861db2a3593e2072a7bad70d557c009b323`.

Issue #369 remains separate and owns Raspberry Pi inventory/filter/select/save editor acceptance.

## Scope delivered

Persisted Saved Live Dashboard `line` and `area` history rendering now uses the canonical NEXOLAB Chart System established by Issue #386 and already used by Live Data.

Delivered behavior:

- legacy independent Saved Dashboard SVG history renderer removed;
- persisted `LiveDashboardItem` / `LiveDashboardSeries` mapped into canonical stable Chart Domain identities;
- persisted item order, saved colors and exact native units preserved;
- quality, delivery freshness and continuity remain independent dimensions;
- invalid-quality and source-gap evidence breaks continuity instead of being bridged;
- alarm transitions preserve adjacent evidence and canonical event markers;
- visualization reduction uses the canonical evidence-preserving reducer with bounded fallback;
- compatible exact units share synchronized groups; incompatible quantities remain separate;
- cumulative energy remains semantically separate from instantaneous power;
- `line` and `area` render through `ChartShell`, `ChartRendererHost` and the local ECharts 6.1 Canvas adapter;
- `areaFillOpacity` is an optional canonical presentation property and does not change existing line-only consumers;
- shared cursor, show/hide, solo, zoom/pan and Reset zoom are canonical;
- persisted `dashboard.time_window` remains the initial/reset viewport;
- `refresh_seconds` remains a display flush preference only and does not change physical acquisition cadence;
- persisted `value` and `gauge` remain truthful current-value cards;
- one renderer instance remains mount-scoped and is disposed on unmount;
- rolling Saved Dashboard scene updates are non-animated to prevent blank transition frames on Raspberry Pi;
- canonical cursor/inspector layout is stable under hover and tooltip updates.

No dashboard CRUD/version/ETag contract, telemetry REST/WebSocket schema, database migration, Device Agent, scheduler, registry, Modbus path or dependency version changed.

## Automated verification

Final exact-head gates on `ce2356cfb142e241684a7a68a08969cab884c2f5`:

- CI run #2910 — GREEN;
- Authenticated Dashboard Acceptance run #1607 — GREEN, 12/12 production Playwright;
- Acquisition Scale Acceptance run #84 — GREEN;
- Refrigeration Browser Acceptance run #1581 — GREEN;
- Offline Bundle run #990 — GREEN, including disconnected startup and update/rollback persistent-data preservation;
- unresolved PR review threads — 0;
- final compare against base — ahead 48, behind 0.

Production browser coverage includes:

- persisted Saved Dashboard canonical Canvas rendering;
- no legacy plot SVG;
- line and area rendering;
- value/gauge truthfulness;
- show/hide/solo;
- zoom/pan/reset;
- responsive 360/1440/1920 layouts;
- zero dashboard/acquisition mutations from interactions;
- zero mandatory public runtime requests;
- bounded close/reopen WebSocket lifecycle;
- real local MQTT live-point continuity across `refresh_seconds` with the same `ChartRendererHost` and ECharts Canvas DOM nodes and no extra history request;
- cursor movement regression asserting stable chart host top/height and stable `window.scrollY`.

## Physical acceptance history

### First attempt — acquisition PASS, visual continuity FAIL

Candidate `2b508d8a1c22ab28069c24833b792261b16193e6` built on the controlled Raspberry Pi.

Equal 60-second windows:

| Metric              | Browser closed | Active Saved Dashboard |
| ------------------- | -------------: | ---------------------: |
| physical requests   |            156 |                    144 |
| physical requests/s |          2.600 |                  2.400 |
| retries             |             18 |                     12 |
| timeouts            |             24 |                     12 |
| bus executions      |            126 |                    120 |
| bus busy seconds    |         13.819 |                 10.110 |

Scheduler policy, configured targets `38 -> 38`, poll eligibility `38 -> 38`, degraded/cooldown endpoints `4 -> 4`, service-operation counters and telemetry progression remained stable.

Acquisition invariant: **PASS**.

Operator recorded `chart_visual_continuity=FAIL`; therefore the PR remained Draft.

The first protocol also mixed continuous viewing with intentional library navigation, so the repeat protocol separated those phases instead of rewriting the historical FAIL.

### Acceptance-harness cleanup

An orphan `next-server` from the earlier #400 temporary handoff held port 3000 and drove `nexolab-dashboard.service` into `EADDRINUSE` restart churn.

The process was identified by PID/cwd, terminated, port 3000 released, and production restored. No backend data, acquisition configuration or hardware state changed.

Later candidate runs were moved to a transient systemd unit to guarantee cleanup and avoid orphan processes.

### Corrective acquisition retest — PASS

On the corrective lineage, equal 60-second windows produced:

| Metric              | Browser closed | Active Saved Dashboard |
| ------------------- | -------------: | ---------------------: |
| physical requests   |            192 |                    181 |
| physical requests/s |          3.200 |                  3.017 |
| retries             |             18 |                     12 |
| success             |            168 |                    169 |
| timeouts            |             24 |                     12 |
| bus executions      |            162 |                    157 |
| bus executions/s    |          2.700 |                  2.617 |
| bus busy seconds    |         15.564 |                 11.653 |

Invariants:

- scheduler policy unchanged;
- configured targets `38 -> 38`;
- poll eligible targets `38 -> 38`;
- degraded endpoints `3 -> 3`;
- cooldown endpoints `3 -> 3`;
- service operations `{}` -> `{}`;
- aggregate telemetry advanced.

Conclusion: **PASS**. Opening the Saved Dashboard did not amplify physical acquisition or alter scheduler/registry state.

### Deterministic exact-series visual continuity — PASS

Read-only PostgreSQL inventory established an existing real Saved Dashboard target:

- dashboard: `111`;
- visualization: `line`;
- channel: `104-03`;
- metric: `temperature.probe`;
- source: `dixell-xjp60d`;
- historical window: 24 h with thousands of valid points;
- current device events: truthful `communication_error` samples with null value.

During the controlled candidate run, exact real series events advanced through:

- `2026-08-12 10:47:34.583778+00`;
- `2026-08-12 10:47:39.583776+00`;
- `2026-08-12 10:47:44.583766+00`.

All were `communication_error`, which is valid evidence for the canonical gap/error path and must not erase existing valid historical evidence.

Operator verdict:

- graph disappeared during events: **NO**;
- existing 24 h graph stayed visible: **YES**;
- dashboard remained usable: **YES**;
- library -> reopen: **PASS**.

Conclusion: **visual continuity PASS**. Real invalid/error events create truthful continuity gaps without blanking the existing historical chart.

## Cursor-layout defect and final exact-head Pi retest

After visual continuity passed, the Product Owner identified a separate interaction defect: moving the cursor caused the chart/card to jump vertically.

Root cause was cursor-dependent layout movement in the canonical Chart Shell/inspection surface rather than a data or Y-scale change.

Corrective slice:

- inspection rows remain layout-stable across cursor states;
- legend footprint does not reflow with changing cursor values;
- browser scroll anchoring/layout movement is prevented for the cursor surface;
- ECharts uses a vertical time pointer without a moving horizontal crosshair;
- tooltip position transition is disabled;
- production Playwright asserts chart host `top`/`height` and `window.scrollY` remain unchanged during cursor movement.

Final exact Raspberry Pi cursor retest on `ce2356cfb142e241684a7a68a08969cab884c2f5`:

- cursor movement vertical jump: **NO**;
- graph/card stays fixed while cursor moves: **YES**;
- zoom / pan / Reset zoom: **PASS**;
- dashboard remains usable: **YES**.

The candidate ran as controlled transient systemd unit, stopped cleanly and released port 3000. Production then restored as:

- `ActiveState=active`;
- `SubState=running`;
- `Result=success`;
- `NRestarts 0 -> 0` over the stability observation;
- HTTP 200;
- no orphan candidate process remained.

## Offline and safety boundary

No mandatory runtime internet dependency, CDN, remote font, analytics, cloud renderer or paid runtime service was added.

Issue #404 made no polling cadence, scheduler policy, registry eligibility, Device Agent configuration, Modbus behavior or hardware-state change.

No Modbus write, hardware write, database mutation, volume deletion or production/site cutover occurred.

## Truthful limitation

The existing Saved Dashboard telemetry hook exposes delivery states such as `reconnecting`, but not a timestamped reconnect-boundary event. The Chart System therefore preserves reconnecting as freshness state and uses actual observed missing/source-gap evidence for continuity. It does not invent a reconnect timestamp.

## Merge evidence

Final pre-merge conditions:

- PR #410 Ready, mergeable;
- exact head `ce2356cfb142e241684a7a68a08969cab884c2f5`;
- base `main=f3462861db2a3593e2072a7bad70d557c009b323` unchanged;
- branch ahead 48, behind 0;
- five required workflows GREEN;
- unresolved review threads 0;
- physical acceptance PASS.

PR #410 was squash-merged with exact-head guard into:

`d4068e28402aa113f4485dc3afecb1f8eb44bd7b`

Issue #404 closed as completed.

## Post-merge state boundary

The feature branch intentionally retained the pre-final-acceptance state checkpoint so the exact tested product head was not changed only to rewrite metadata before merge.

Issue #411 owns the focused post-merge state reconciliation. After #411 merges, the next required action is a fresh repository-backed Ready audit. Product Owner priority favors continuing the Chart System migration with Overview if that audit confirms it is the next unblocked Work Package.

Preserved independent runtime sequence remains:

```text
#369 -> #366 -> #289
```

Issue #389 remains Ready/not selected until the fresh audit or Product Owner changes priority.
