# Issue #413 — Overview temperature canonical Chart System audit

Updated: 2026-08-12

## Status

**Product implementation complete; corrective Raspberry Pi cursor retest PASS; final state-only exact-head merge audit pending on Draft PR #414.**

Base `main`: `e89560cd2f52b59ed1c9fda4adca38e4c634a3b7`.

## Product scope delivered

Issue #413 replaces the independent Overview XJP60D temperature-history SVG with the canonical NEXOLAB Chart System while preserving the existing Overview live cards, active sensor selection, authenticated latest/history/WebSocket path and 1h/6h/24h product contract.

Delivered behavior:

- exact stable node/equipment/channel/metric/native-unit identity;
- invalid-quality and source-gap continuity boundaries;
- canonical evidence-preserving reduction;
- deterministic canonical series identity and compatible-unit grouping;
- `ChartShell` + `ChartRendererHost` + local ECharts Canvas;
- persistent non-animated live updates;
- canonical exact cursor and external Exact inspector;
- show/hide/solo and zoom/pan/reset;
- responsive footer behavior that prevents inspector/legend overlap;
- no extra history requests from cursor, visibility, zoom or live updates;
- no chart-driven acquisition mutation;
- zero mandatory public runtime requests.

## First physical acceptance and defect isolation

First frozen candidate `634dcdfd8561d7e0ebe844b871ffa9f44d9fbcb5` passed CI #2942, Authenticated Dashboard #1630, Refrigeration #1604 and Offline Bundle #1013.

Controlled Raspberry Pi acceptance used a real active series:

- channel `126-04`;
- metric `temperature.probe`;
- source `dixell-xjp60d`;
- 120 real events in the preceding 10 minutes;
- 16,594 valid samples in the preceding 24 hours.

Equal 60-second physical acquisition evidence:

- browser closed: 144 physical requests, 132 success, 12 timeout, 12 retries, 9.92298 s bus busy;
- active Overview: 153 physical requests, 132 success, 21 timeout, 17 retries, 12.871187 s bus busy;
- discovery delta 0;
- configuration mutation delta 0;
- Modbus write attempts 0;
- polling policy remained `priority_adaptive_v1`;
- configured targets remained `38 -> 38`;
- registry revision and summary unchanged;
- service-operation delta `{}`.

The raw rate comparison was classified `REVIEW_EQUAL_DURATION_COUNTERS`; successful polls were identical in both windows and the higher raw active count coincided with additional timeout/retry activity. No browser-driven scheduler or registry mutation was observed.

The exact real series advanced from event `1b19f5f5-4f4f-4734-83d6-b896d9a61438` at `2026-08-12 18:35:03.216544+00` to `508e5cf9-be2f-44dc-8a61-f15fd089fcab` at `2026-08-12 18:35:08.227509+00`, both valid at 25.9 °C.

All physical UI observations passed except cursor visual stability. The first acceptance recorded:

```text
cursor_vertical_jump=YES
graph_card_stays_fixed=YES
```

Because the graph/card itself remained fixed, the defect was isolated from the earlier responsive ChartShell reflow issue.

## Corrective shared renderer fix

Corrective product head: `0b0b239911c729e31c791c8fa2eb2c6f433bfcce`.

The shared ECharts adapter previously rendered moving HTML axis-tooltip content even though NEXOLAB already rendered the stable canonical Exact inspector. The corrective fix:

- keeps the vertical time axis pointer;
- keeps `updateAxisPointer` cursor events;
- sets ECharts tooltip `showContent: false`;
- stops dispatching `showTip` from shared cursor movement;
- keeps the external canonical Exact inspector as the value presentation surface;
- adds a unit regression for this contract.

No data mapping, continuity, telemetry API, WebSocket, Device Agent, scheduler, registry, polling or hardware behavior changed.

## Corrective software/browser/offline verification

On product head `0b0b239911c729e31c791c8fa2eb2c6f433bfcce`:

- CI #2944 — GREEN;
- Authenticated Dashboard Acceptance #1632 — GREEN, including acquisition invariant;
- Refrigeration Browser Acceptance #1606 — GREEN;
- Offline Bundle #1015 — GREEN.

## Targeted controlled Raspberry Pi retest

The Product Owner repeated the affected visual interaction on the corrective product code and reported:

```text
chart_visual_continuity=PASS
post_event_overview_render=PASS
cursor_vertical_jump=NO
graph_card_stays_fixed=YES
hide_show_solo=PASS
zoom_pan_reset=PASS
range_1h_6h_24h=PASS
route_reopen=PASS
dashboard_remains_usable=YES
```

This closes the #413 physical cursor blocker. The full earlier physical acquisition/control-plane evidence is carried forward under proportional verification because the corrective product diff is renderer/test-only and introduces no runtime acquisition change.

## Product Owner follow-up

During the successful retest, the Product Owner requested a more natural desktop pan interaction: hold the left mouse button and drag horizontally through a zoomed chart.

This is recorded separately as Issue #415 — **Add left-button drag panning to canonical NEXOLAB charts**. It is not a blocker for #413 and does not expand the hardware-tested #413 product code after acceptance.

## Final merge protocol

After the final state/audit-only completion commits:

1. confirm product code after `0b0b2399...` is unchanged;
2. require current exact-head CI GREEN;
3. confirm `main` still equals `e89560cd2f52b59ed1c9fda4adca38e4c634a3b7`;
4. confirm focused PR diff and no `.github` workflow changes;
5. confirm zero unresolved review threads and no blocking reviews;
6. mark PR #414 Ready;
7. squash-merge with an exact-head SHA guard;
8. perform focused post-merge state reconciliation and fresh Ready audit.

## Safety boundary

No backend schema, database migration, telemetry API, Device Agent, scheduler, registry, discovery, Modbus, hardware or dependency change is part of #413.

No Modbus write, hardware write, destructive data/volume operation or production/site cutover is permitted. No mandatory CDN, remote font, analytics, cloud renderer, external API or paid runtime dependency is introduced.

## Completion classification

```text
software/browser/offline verified
hardware verified on corrective product code
final state-only exact-head merge audit pending
```
