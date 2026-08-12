# NEXOLAB Current State

Updated: 2026-08-12

Canonical repository baseline on `main`: `61998415e334cb31555e54ae4013d938e7607b6e` — PR #401 post-#386 state reconciliation; Chart System foundation remains canonical.

## Completed Work Package — Issue #385

Issue #385 / PR #390 is completed and merged.

Delivered:

- four product roles: `administrator`, `laboratory_manager`, `engineer`, `laboratory_technician`;
- local-only Users & Access workspace at `/settings/users`;
- administrator-managed role/permission lifecycle with session revocation and audit;
- local PostgreSQL persistence and offline-local authentication;
- canonical migration `20260807_0024`.

Verification:

```text
PR #390 merge: e0b124e9a0152be50966daa131974b3543651e87
final exact-head CI: 19/19 GREEN
Raspberry Pi acceptance: PASS
```

## Completed Work Package — Issue #386

Issue #386 / PR #399 is completed and merged as `3b34ec321c2453778b20b6bf8e4cc232970e5e1e`.

Delivered:

- canonical Chart Domain series/quality/freshness/continuity contracts;
- compatible-unit grouping and renderer-independent descriptors;
- evidence-preserving bounded segment-aware min/max reducer;
- ECharts `6.1.0` modular Canvas adapter and reusable Chart Shell/renderer host;
- deterministic renderer benchmark and offline bundle proof.

Raspberry Pi 5 renderer evidence passed the provisional targets: 8×240 median 103.8 ms / p95 169.0 ms, incremental p95 31.2 ms. Final PR head passed 11/11 exact-head checks.

## Active Work Package — Issue #400

Issue #400 / PR #402 migrates the Live Data Explorer to the canonical Chart System while preserving Saved Live Dashboards as a sibling `/live` workspace.

Implemented:

- `/live?workspace=explorer` exposes Live Data without removing Saved Dashboards;
- route-local SVG comparison rendering is replaced by `ChartShell`, `ChartRendererHost` and the canonical ECharts adapter;
- up to eight channels remain supported;
- compatible native units render in synchronized plot groups;
- evidence-preserving segment-aware reduction replaces last-point-per-bucket behavior;
- source gaps and alarm-transition evidence remain truthful;
- shared cursor/x-domain, show/hide/solo, zoom/pan/reset and canonical ranges are supported;
- Live Follow, Pause View and Return to Live remain display-only;
- existing route-persistent REST/history/WebSocket reconciliation remains authoritative;
- no REST/WebSocket schema, database, retention, scheduler, registry, Device Agent, Modbus or hardware changes are in scope.

### Software/offline verification

Frozen pre-hardware software candidate:

`2da08a028f54884acb74ea71cf1fac741426687b`

It passed:

- format: GREEN;
- lint: GREEN;
- typecheck: GREEN;
- 77 test files / 344 tests: GREEN;
- Next.js production build: GREEN;
- Authenticated Dashboard Acceptance: GREEN, including the deterministic 8-channel Live Chart System flow;
- Acquisition Scale Acceptance: GREEN;
- Refrigeration Browser Acceptance: GREEN;
- Offline Bundle: GREEN, including disconnected start and update/rollback persistent-data preservation.

### Raspberry Pi physical acquisition-invariant acceptance

Controlled hardware acceptance completed on 2026-08-12 against exact candidate `2da08a028f54884acb74ea71cf1fac741426687b`.

Evidence directory retained on the Raspberry Pi:

`/home/nexolab/nexolab-400-hardware.5B0rFp/evidence`

Equal-duration 60-second observations:

```text
browser-closed baseline:
  physical requests: 180
  physical request rate: 3.000/s
  retries: 12
  timeouts: 12
  bus executions: 156
  bus busy: 11.928s

8-channel active Chart System:
  physical requests: 181
  physical request rate: 3.017/s
  retries: 12
  timeouts: 12
  bus executions: 157
  bus busy: 11.772s
```

The physical request-rate delta was +0.56%. Scheduler policy remained unchanged, configured targets remained 38, poll-eligible targets remained 38, retries/timeouts were unchanged and bus busy time did not increase. Telemetry continued advancing throughout the active chart window.

Final runtime evidence:

- Telemetry Service `ready`;
- database `ready`;
- MQTT `ready`;
- telemetry queue size 0;
- ingestion lag about 0.136 s;
- Device Agent MQTT connected and queue depth 0;
- Device Agent remained in the same pre-existing degraded condition with 3 failing/cooldown endpoints;
- no Modbus write or hardware write occurred;
- production dashboard service was restored after the controlled candidate test.

Hardware acceptance classification: **PASS**.

## Ready/merge boundary

Issue #400 now has software, offline and Raspberry Pi production acquisition-invariant evidence. The only remaining step is a final exact-head state/check/review audit after these evidence commits. Merge only while the final PR head is GREEN and current with `main`.

Issue #389 remains open and `status:ready`, but `ready_not_selected` while #400 completes. The preserved runtime sequence remains:

```text
#369 -> #366 -> #289
```

## Security boundary

The existing `telemetry-service/libcjson1/CVE-2026-67216` exception expires on 2026-09-05 and was not broadened by Issue #400.

## Next action

Run the final exact-head CI/offline/review audit for PR #402. If GREEN, mark PR #402 Ready, squash-merge Issue #400, reconcile `main`, then perform a fresh Ready audit and create/refine the Saved Live Dashboard canonical Chart System migration as the next Chart Work Package. Keep #389 Ready but not selected and preserve #369 -> #366 -> #289 unless Product Owner explicitly changes priority.
