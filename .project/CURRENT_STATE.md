# NEXOLAB Current State

Updated: 2026-08-12

Canonical repository baseline on `main`: `457923927052ed91a23f396b2285e0cfaf6096ad` — Issue #406 / PR #407 Live Data chart continuity regression fix.

## Completed — Issue #385

Issue #385 / PR #390 is merged as `e0b124e9a0152be50966daa131974b3543651e87`. Local users, four roles, administrator-managed permissions and offline-local authentication are software- and Raspberry-Pi-verified.

## Completed — Issue #386

Issue #386 / PR #399 is merged as `3b34ec321c2453778b20b6bf8e4cc232970e5e1e`. The canonical Chart Domain, evidence-preserving reducer, compatible-unit grouping, ECharts 6.1.0 local Canvas adapter, Chart Shell and renderer host are canonical.

## Completed — Issue #400

Issue #400 / PR #402 is merged as `afdfa387a7aa988a49e010d75c27d59a7cdf74d2`. Live Data uses the canonical Chart System. Controlled Raspberry Pi acquisition-invariant acceptance was PASS. Evidence remains at `/home/nexolab/nexolab-400-hardware.5B0rFp/evidence`.

## Completed — Issue #403

Issue #403 / PR #405 is merged as `c5977f846b87d0a498f84feec5b2e8f966a61d94`.

## Completed — Issue #406

Issue #406 / PR #407 fixed the post-#400 chart disappearance regression and squash-merged as `457923927052ed91a23f396b2285e0cfaf6096ad`.

Final PR head: `4b82acf750fbd52b2c4e5b7eca0210742a6b0fe2`.

Root cause:

- persisted-history loading depended on selected identity arrays rebuilt from mutable latest telemetry samples;
- each normal live point could restart history loading, clear history state and replace the mounted chart with the loading placeholder.

Delivered correction:

- stable `selectedKey` controls history selection reloads;
- current selected identity samples are retained independently from the loader trigger;
- mutable `selectedIdentities` and rebuilt `reconciledSelectedKeys` no longer retrigger persisted history;
- actual selection/range/retry/scope/live-coverage changes still reload as required;
- WebSocket tail, gaps, quality, alarm and bounded-history semantics remain unchanged.

Exact-head verification on `4b82acf...`:

- CI GREEN — contracts, format, lint, typecheck, full tests, production build;
- Authenticated Dashboard Acceptance GREEN — 11/11 production browser tests;
- modified Live Chart test published a real sample through local MQTT and proved renderer hosts stayed mounted, history loading did not reappear and no extra history request occurred;
- acquisition-invariant browser acceptance GREEN;
- Refrigeration Browser Acceptance GREEN;
- Offline Bundle GREEN — disconnected load/start, blocked egress and update/rollback persistent-data preservation.

No new physical Raspberry Pi acceptance was run for #406 and none is claimed. No REST/WebSocket schema, database, retention, polling, scheduler, registry, Device Agent, Modbus or hardware change occurred.

## Active Work Package — Issue #404

**Issue #404 — Migrate Saved Live Dashboards to the canonical NEXOLAB Chart System** is now the sole selected implementation lane.

Product outcome:

- map persisted Saved Dashboard line/area series into canonical Chart Domain;
- replace independent `SeriesChart` SVG with ChartShell + ChartRendererHost + ECharts;
- preserve saved colors/order/time-window and display-only refresh semantics;
- truthful continuity/gaps/quality/freshness;
- compatible-unit synchronized plot groups;
- shared cursor, show/hide/solo, zoom/pan/reset;
- value/gauge regression protection;
- persistent renderer lifecycle, no duplicate WebSocket/subscription;
- responsive/offline/acquisition-invariant verification;
- controlled Raspberry Pi acceptance reported separately after software gates.

Issue #404 remains distinct from #369: #404 is renderer migration; #369 is Raspberry Pi inventory/filter/select/save editor acceptance.

Issue #389 remains Ready/not selected. Preserved runtime sequence remains:

```text
#369 -> #366 -> #289
```

## Security boundary

The `telemetry-service/libcjson1/CVE-2026-67216` exception expires on 2026-09-05. Issue #406 did not broaden it.

## Next action

Merge this state-only reconciliation while GREEN, then start Issue #404 from the reconciled `main` as the sole implementation lane.
