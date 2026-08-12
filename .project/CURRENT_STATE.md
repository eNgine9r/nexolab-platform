# NEXOLAB Current State

Updated: 2026-08-12

Canonical repository baseline on `main`: `c5977f846b87d0a498f84feec5b2e8f966a61d94` — Issue #403 / PR #405 post-#400 state reconciliation merge.

## Completed — Issue #385

Issue #385 / PR #390 is merged as `e0b124e9a0152be50966daa131974b3543651e87`.

Local users, four product roles, administrator-managed permissions, session revocation, audit and offline-local authentication are software- and Raspberry-Pi-verified.

## Completed — Issue #386

Issue #386 / PR #399 is merged as `3b34ec321c2453778b20b6bf8e4cc232970e5e1e`.

The canonical NEXOLAB Chart System foundation is production-available: Chart Domain identity/quality/freshness/continuity contracts, compatible-unit grouping, evidence-preserving reduction, ECharts 6.1.0 local Canvas adapter, Chart Shell and renderer host.

## Completed — Issue #400

Issue #400 / PR #402 is squash-merged as `afdfa387a7aa988a49e010d75c27d59a7cdf74d2`.

Live Data uses the canonical Chart System. Final exact-head software/browser/offline gates were GREEN. Controlled Raspberry Pi acquisition-invariant acceptance was PASS against candidate `2da08a028f54884acb74ea71cf1fac741426687b`.

Evidence remains at:

`/home/nexolab/nexolab-400-hardware.5B0rFp/evidence`

Equal 60-second observations were 180 physical requests / 3.000 req/s with browser closed versus 181 / 3.017 req/s with an active eight-channel chart (+0.56%), with identical retry/timeout counts, unchanged scheduler policy and 38 configured/poll-eligible targets.

## Completed — Issue #403

Issue #403 / PR #405 is completed and squash-merged as `c5977f846b87d0a498f84feec5b2e8f966a61d94`.

The repository state was reconciled after #400 and Issue #404 was established as the next Saved Live Dashboard Chart System migration.

## Active critical regression — Issue #406

Product Owner reported that the Live Data chart repeatedly disappears while new points arrive.

Issue #406 — **Keep Live Data charts mounted while live samples arrive** — is the sole active implementation lane on branch `fix/406-live-chart-history-continuity`.

Repository-backed root cause:

- `selectedIdentities` was derived from mutable latest `TelemetrySample` objects;
- `reconciledSelectedKeys` was also rebuilt whenever `view.samples` changed;
- the persisted-history effect depended on those rebuilt arrays;
- every normal live point could therefore abort/restart `loadCompleteLiveHistory`, clear `historySamples`, set `historyStatus=loading`, and cause the UI to replace the chart with the loading placeholder.

Focused correction implemented:

- keep selected identity samples in a ref updated independently from the history loader;
- use stable `selectedKey` as the history selection trigger;
- remove mutable `selectedIdentities` and rebuilt `reconciledSelectedKeys` from the history-effect dependency boundary;
- preserve history reloads for actual selection, range, retry, scope/configuration and live-coverage changes;
- preserve WebSocket-tail reconciliation and all gap/quality/alarm semantics;
- add a production browser regression that publishes a real acceptance sample through local MQTT and requires the existing ChartRendererHost instances to remain mounted with no extra `/telemetry/history` request.

Targeted implementation verification already run on the feature branch:

- Prettier touched files: GREEN;
- TypeScript typecheck: GREEN;
- focused `live-history` and `live-chart` tests: GREEN.

Full PR/browser/offline verification is still required before merge.

No backend schema, database, retention, polling, scheduler, registry, Device Agent, Modbus or hardware change is in scope.

## Next selected Chart Work Package after #406

**Issue #404 — Migrate Saved Live Dashboards to the canonical NEXOLAB Chart System.**

It remains open, assigned, `priority:high` and `status:ready`, but implementation is paused while the critical #406 regression is resolved.

Issue #404 remains distinct from #369:

- #404 migrates the persisted Saved Dashboard line/area renderer;
- #369 remains the Raspberry Pi inventory/filter/select/save acceptance for the dashboard editor.

Issue #389 remains Ready/not selected. The preserved runtime sequence remains:

```text
#369 -> #366 -> #289
```

## Security boundary

The existing `telemetry-service/libcjson1/CVE-2026-67216` exception expires on 2026-09-05. Issue #406 does not broaden it.

## Next action

Complete Issue #406 with focused PR, full format/lint/typecheck/tests/build, deterministic Live Chart browser acceptance, acquisition-invariant checks and Offline Bundle. Merge only while exact-head checks are GREEN and the diff is focused. Reconcile state after merge, then start Issue #404 as the sole implementation lane.
