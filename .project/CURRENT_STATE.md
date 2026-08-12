# NEXOLAB Current State

Updated: 2026-08-12

Canonical repository baseline on `main`: `e89560cd2f52b59ed1c9fda4adca38e4c634a3b7` — Issue #411 / PR #412 post-#404 state reconciliation merge.

## Completed Chart System foundation and migrations

- Issue #386 / PR #399 — canonical Chart Domain, truthful continuity, compatible-unit grouping, evidence-preserving reduction, ECharts 6.1.0 Canvas adapter, Chart Shell and renderer host — merged as `3b34ec321c2453778b20b6bf8e4cc232970e5e1e`.
- Issue #400 / PR #402 — Live Data canonical Chart System migration — merged as `afdfa387a7aa988a49e010d75c27d59a7cdf74d2`; controlled Raspberry Pi acquisition invariant PASS.
- Issue #406 / PR #407 — Live Data chart-disappearance regression — merged as `457923927052ed91a23f396b2285e0cfaf6096ad`.
- Issue #404 / PR #410 — Saved Live Dashboard canonical Chart System migration — merged as `d4068e28402aa113f4485dc3afecb1f8eb44bd7b`; controlled Raspberry Pi acquisition, visual continuity, library reopen and cursor-layout acceptance PASS.
- Issue #411 / PR #412 — focused post-#404 state reconciliation — merged as current `main=e89560cd2f52b59ed1c9fda4adca38e4c634a3b7` after CI #2918 GREEN.

## Active Work Package — Issue #413 / Draft PR #414

Issue #413 migrates Overview XJP60D temperature history from the route-local SVG renderer to the canonical NEXOLAB Chart System while preserving the existing live cards, active-sensor selection, authenticated latest/history/WebSocket path and 1h/6h/24h product contract.

Implemented scope:

- exact canonical node/equipment/channel/metric/unit identities;
- invalid-quality and >30 s source-gap continuity boundaries;
- canonical evidence-preserving reduction with 240-point target;
- deterministic canonical series tokens and compatible-unit grouping;
- `ChartShell` + `ChartRendererHost` + local ECharts Canvas;
- persistent non-animated live updates;
- exact cursor/inspector, show/hide/solo, zoom/pan/reset;
- no legacy Overview telemetry SVG;
- responsive shared ChartShell footer fix so inspector cannot overlap legend controls in the narrow Overview card;
- production browser assertions for Canvas lifecycle, exact range requests, cursor layout stability, no extra history/acquisition requests, responsive overflow and zero public runtime requests.

## First final software freeze and physical acceptance

Frozen candidate `634dcdfd8561d7e0ebe844b871ffa9f44d9fbcb5` passed:

- CI #2942 — GREEN;
- Authenticated Dashboard Acceptance #1630 — GREEN, including acquisition invariant;
- Refrigeration Browser Acceptance #1604 — GREEN;
- Offline Bundle #1013 — GREEN, including disconnected startup and update/rollback persistent-data preservation.

Controlled Raspberry Pi acceptance then used a real active Overview series:

- channel `126-04`;
- metric `temperature.probe`;
- source `dixell-xjp60d`;
- 120 events in the preceding 10 minutes;
- 16,594 valid samples in the preceding 24 hours.

Equal 60-second physical acquisition windows:

| Metric | Browser closed | Active Overview |
| --- | ---: | ---: |
| Physical requests | 144 | 153 |
| Requests/s | 2.400 | 2.550 |
| Successful requests | 132 | 132 |
| Timeouts | 12 | 21 |
| Retries | 12 | 17 |
| Bus busy seconds | 9.92298 | 12.871187 |

The rate comparison was classified `REVIEW_EQUAL_DURATION_COUNTERS`, not an automatic failure. The active window did not produce additional successful polls; the higher raw request count coincided with additional timeout/retry activity. More importantly, the physical acquisition control plane remained unchanged:

- discovery delta 0;
- configuration mutation delta 0;
- Modbus write attempts 0;
- polling policy `priority_adaptive_v1` unchanged;
- configured targets `38 -> 38`;
- registry revision and summary unchanged;
- service-operation delta `{}`.

Exact real-series continuity advanced from event `1b19f5f5-4f4f-4734-83d6-b896d9a61438` at `2026-08-12 18:35:03.216544+00` to event `508e5cf9-be2f-44dc-8a61-f15fd089fcab` at `2026-08-12 18:35:08.227509+00`, both valid at 25.9 °C.

Physical UI results:

- existing history continuity — PASS;
- post-event Overview usability — PASS;
- Hide/Show/Solo — PASS;
- zoom/pan/reset — PASS;
- 1h -> 6h -> 24h — PASS;
- route reopen — PASS;
- dashboard usability — YES;
- graph/card stays fixed — YES;
- **cursor vertical jump — YES**.

Therefore candidate `634dcdfd...` is a **product FAIL for cursor visual stability** and is not mergeable as accepted hardware evidence. Production restored cleanly with `NRestarts 0 -> 0` and no orphan candidate process.

## Corrective cursor fix

Because the graph/card itself stayed fixed, the remaining defect was isolated from the earlier ChartShell responsive reflow issue. The shared ECharts adapter still rendered its own moving HTML axis-tooltip content even though NEXOLAB already exposes the stable canonical `Exact inspector`.

Corrective product head `0b0b239911c729e31c791c8fa2eb2c6f433bfcce`:

- keeps the vertical time axis pointer;
- keeps canonical exact cursor events and the external `Exact inspector`;
- sets ECharts tooltip `showContent: false`;
- no longer dispatches `showTip` for shared cursor movement;
- adds a unit regression proving no moving renderer tooltip is opened.

Corrective verification already completed:

- CI #2944 — GREEN: format, lint, strict typecheck, full tests and production build;
- Authenticated Dashboard Acceptance #1632 — GREEN, including acquisition invariant;
- Refrigeration Browser Acceptance #1606 — GREEN;
- Offline Bundle #1015 was still running when this state checkpoint was prepared.

The corrective change is frontend renderer/test-only and does not alter telemetry APIs, Device Agent, scheduler, registry, polling cadence or hardware state.

## Preserved independent lanes

Issue #369 remains Ready and separate. Preserved runtime sequence:

```text
#369 -> #366 -> #289
```

Issue #389 remains Ready/not selected. Issue #245 remains a separate Raspberry Pi validation track. Issue #257 remains blocked. Issue #256 remains deferred.

## Safety boundary

No Modbus write or hardware write is permitted. Issue #413 changes no backend schema, PostgreSQL migration, Device Agent, acquisition scheduler/registry, discovery path or dependency version. No mandatory CDN, remote font, analytics, cloud renderer, external API or paid runtime service is introduced.

The `telemetry-service/libcjson1/CVE-2026-67216` exception still expires on 2026-09-05 and is not broadened by #413.

## Next action

Finish the batched corrective state/audit checkpoint, require all canonical workflows GREEN on the resulting exact head, freeze that head, then run a **targeted Raspberry Pi cursor visual retest** on the exact corrective candidate. Carry forward the already proven real-series continuity, controls, route-reopen, production-restore and physical acquisition control-plane evidence because the corrective diff is limited to renderer tooltip presentation plus tests/state. If any new product/runtime scope enters the final diff, rerun the full physical acquisition matrix before merge.
