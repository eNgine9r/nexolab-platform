# NEXOLAB Blockers

Updated: 2026-08-12

## Issue #400 — completed

Issue #400 / PR #402 is merged as `afdfa387a7aa988a49e010d75c27d59a7cdf74d2`. Raspberry Pi evidence remains at `/home/nexolab/nexolab-400-hardware.5B0rFp/evidence`.

## Issue #406 — completed

Issue #406 / PR #407 is merged as `457923927052ed91a23f396b2285e0cfaf6096ad`. The Live Data chart-disappearance regression is fixed; exact-head CI/browser/offline gates were GREEN. No new physical Raspberry Pi claim was made for #406.

## Issue #408 — completed

Issue #408 / PR #409 is merged as `f3462861db2a3593e2072a7bad70d557c009b323`.

## Issue #404 — active merge blocker: Raspberry Pi visual continuity

Issue #404 remains the sole active implementation lane for Saved Live Dashboard canonical Chart System migration. PR #410 remains Draft.

The first controlled Raspberry Pi test of candidate `2b508d8a1c22ab28069c24833b792261b16193e6` produced a split result:

- acquisition invariant: **PASS**;
- chart visual continuity: **FAIL**.

Equal 60-second windows showed no browser-driven acquisition amplification: browser closed `156` physical requests / `2.600 req/s`; active Saved Dashboard `144` / `2.400 req/s`. Scheduler policy, 38 configured targets, 38 poll-eligible targets and 4 degraded/cooldown endpoints remained unchanged; telemetry advanced.

The visual failure blocks Ready/merge until a repeated physical acceptance passes.

A corrective slice is implemented:

- Saved Dashboard ECharts rolling scene refreshes are non-animated to avoid blank transition frames on Raspberry Pi;
- one mounted `ChartRendererHost` and one ECharts instance remain authoritative;
- production browser acceptance now publishes a real local MQTT point across the dashboard refresh interval and asserts the same host and Canvas DOM nodes survive without an additional history reload.

Corrective source head `67846013a8c7d357716321e2149509a2fb526f43` passed CI, Authenticated Dashboard Acceptance, Acquisition Scale Acceptance, Refrigeration Browser Acceptance and Offline Bundle. A final exact-head cycle is still required after the canonical state checkpoint, followed by a repeated Raspberry Pi test.

The repeated physical acceptance must separate:

1. continuous chart observation while new real points arrive, with no route/library navigation;
2. intentional library close/reopen lifecycle, checked separately for cleanup/reinitialization.

The first script mixed these phases, so intentional navigation could also cause an expected unmount. The original FAIL remains recorded; the repeat test removes that ambiguity.

### Acceptance-harness cleanup

An orphan `next-server` from the earlier #400 temporary handoff was found holding port 3000 and driving `nexolab-dashboard.service` into repeated `EADDRINUSE` restarts. It was terminated and production dashboard stability was restored (`active/running`, `NRestarts=0`, HTTP 200) before the #404 baseline. No production data, backend service, Device Agent configuration or hardware state was changed.

No backend, database, polling, scheduler, registry, Device Agent, Modbus or hardware change is required to resolve #404.

Known truthful limitation: the existing Saved Dashboard delivery hook reports `reconnecting` freshness but does not expose a timestamped reconnect event. The chart therefore does not invent a reconnect-break timestamp; it preserves reconnecting as freshness and uses actual missing/source-gap evidence for continuity.

## Issue #369 — Ready, separate scope

Issue #369 remains `status:ready` for Raspberry Pi Live Dashboard inventory/filter/select/save editor acceptance. It is not absorbed by #404.

Preserved runtime sequence:

```text
#369 -> #366 -> #289
```

## Issue #389 — Ready and not selected

Issue #389 remains `status:ready` for administrator-only local Version Management, but Product Owner Chart System priority keeps it `ready_not_selected`.

## Other known boundaries

- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #257 remains blocked by ESLint 10 ecosystem compatibility.
- Issue #256 remains deferred pending TypeScript 7 ecosystem compatibility.
- `max_parallel_implementation_tasks` remains 1.

## Security boundary

The `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Issue #404 does not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, privileged hardware containers or unsupported physical-acceptance claims.
