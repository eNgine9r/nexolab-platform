# NEXOLAB Current State

Updated: 2026-08-12

Canonical repository baseline on `main`: `afdfa387a7aa988a49e010d75c27d59a7cdf74d2` — Issue #400 / PR #402 Live Data canonical Chart System migration merge.

## Completed — Issue #385

Issue #385 / PR #390 is merged as `e0b124e9a0152be50966daa131974b3543651e87`.

Local users, four product roles, administrator-managed permissions, session revocation, audit and offline-local authentication are software- and Raspberry-Pi-verified.

## Completed — Issue #386

Issue #386 / PR #399 is merged as `3b34ec321c2453778b20b6bf8e4cc232970e5e1e`.

The canonical NEXOLAB Chart System foundation is production-available:

- Chart Domain identity, quality, freshness and continuity contracts;
- compatible-unit grouping;
- evidence-preserving segment-aware reduction;
- ECharts `6.1.0` local Canvas adapter;
- reusable Chart Shell and renderer host;
- Raspberry Pi 5 renderer benchmark and offline bundle proof.

## Completed — Issue #400

Issue #400 / PR #402 is completed and squash-merged as `afdfa387a7aa988a49e010d75c27d59a7cdf74d2`.

Delivered:

- `/live?workspace=explorer` exposes Live Data as a sibling of Saved Live Dashboards;
- the Live Data route-local SVG renderer is replaced by the canonical Chart System;
- up to eight channels, compatible-unit synchronized groups, shared cursor/x-domain, show/hide/solo and canonical time controls are supported;
- source gaps, alarm evidence, measurement quality and freshness remain truthful and independent;
- Live Follow, Pause View, Return to Live, zoom/pan/reset remain display-only;
- existing REST/history/WebSocket reconciliation remains authoritative;
- no REST/WebSocket schema, database, retention, scheduler, registry, Device Agent, Modbus or hardware behavior changed.

Final exact PR head before merge:

`4cdeae018348c5c831874321b0dad221f6113a98`

Final exact-head gates were GREEN:

- CI — format, lint, typecheck, 77 test files / 344 tests and production build;
- Authenticated Dashboard Acceptance;
- Acquisition Scale Acceptance;
- Refrigeration Browser Acceptance;
- Offline Bundle including disconnected start and update/rollback persistent-data preservation.

### Raspberry Pi acquisition-invariant evidence

Hardware-tested candidate:

`2da08a028f54884acb74ea71cf1fac741426687b`

Evidence directory:

`/home/nexolab/nexolab-400-hardware.5B0rFp/evidence`

Equal 60-second observations:

```text
browser closed:
  physical requests: 180
  request rate: 3.000/s
  retries: 12
  timeouts: 12
  bus executions: 156
  bus busy: 11.928s

active 8-channel Chart System:
  physical requests: 181
  request rate: 3.017/s
  retries: 12
  timeouts: 12
  bus executions: 157
  bus busy: 11.772s
```

Physical request-rate delta was +0.56%. Scheduler policy was unchanged, configured targets stayed 38, poll-eligible targets stayed 38, retry/timeout counts were unchanged and telemetry continued advancing. Telemetry Service/database/MQTT were ready, queue size was 0, and the Device Agent remained in the same pre-existing degraded condition with three failing/cooldown endpoints. Production dashboard service was restored after the test. No Modbus write or hardware write occurred.

Issue #400 hardware acceptance: **PASS**.

## Current control task — Issue #403

Issue #403 is a state-only post-merge reconciliation. Branch: `chore/403-post-400-state`.

No product code, dependency, runtime, database or hardware changes are permitted in #403.

Fresh repository audit after #400 merge found open `status:ready` Issues:

- #369 — Raspberry Pi browser acceptance for canonical Live Dashboard inventory;
- #389 — administrator-only local version management;
- #404 — Saved Live Dashboard canonical Chart System renderer migration.

No existing open Issue or PR duplicated the Saved Live Dashboard renderer migration, so Issue #404 was created as the next focused Chart Work Package.

## Next selected Chart Work Package

**Issue #404 — Migrate Saved Live Dashboards to the canonical NEXOLAB Chart System.**

It is open, assigned, `priority:high` and `status:ready`.

The package is intentionally distinct from #369:

- #404 migrates the persisted Saved Dashboard line/area history renderer to the canonical Chart System;
- #369 remains the Raspberry Pi inventory/filter/select/save acceptance for the dashboard editor.

Issue #389 remains Ready but not selected while the Product Owner Chart System priority is active.

The preserved runtime sequence remains:

```text
#369 -> #366 -> #289
```

## Security boundary

The existing `telemetry-service/libcjson1/CVE-2026-67216` exception expires on 2026-09-05. Issue #400 did not broaden it.

## Next action

Complete and merge state-only Issue #403 while GREEN. Then select Issue #404 as the sole implementation lane. Keep #389 Ready/not selected and preserve #369 -> #366 -> #289 unless a later repository audit or explicit Product Owner priority change establishes a different order.
