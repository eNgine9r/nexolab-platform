# NEXOLAB Current State

Updated: 2026-08-12

Canonical repository baseline on `main`: `e89560cd2f52b59ed1c9fda4adca38e4c634a3b7` — Issue #411 / PR #412 post-#404 state reconciliation merge.

## Completed Chart System foundation and migrations

- Issue #386 / PR #399 — canonical Chart Domain, truthful continuity, compatible-unit grouping, evidence-preserving reduction, ECharts 6.1.0 Canvas adapter, Chart Shell and renderer host — merged as `3b34ec321c2453778b20b6bf8e4cc232970e5e1e`.
- Issue #400 / PR #402 — Live Data canonical Chart System migration — merged as `afdfa387a7aa988a49e010d75c27d59a7cdf74d2`; controlled Raspberry Pi acquisition invariant PASS.
- Issue #406 / PR #407 — Live Data chart-disappearance regression — merged as `457923927052ed91a23f396b2285e0cfaf6096ad`.
- Issue #404 / PR #410 — Saved Live Dashboard canonical Chart System migration — merged as `d4068e28402aa113f4485dc3afecb1f8eb44bd7b` from exact tested head `ce2356cfb142e241684a7a68a08969cab884c2f5`; acquisition, visual continuity, library reopen and cursor-layout Raspberry Pi acceptance PASS.
- Issue #411 / PR #412 — focused post-#404 state reconciliation — merged as current `main=e89560cd2f52b59ed1c9fda4adca38e4c634a3b7` after CI #2918 GREEN.

## Fresh Ready audit after #411

Repository-backed audit on current `main` found:

- open `status:ready` Issue #369 — critical, preserved Raspberry Pi Live Dashboard inventory/filter/select/save editor acceptance;
- open `status:ready` Issue #389 — high, administrator-only local Version Management, Ready/not selected;
- no conflicting product PR; open PRs are isolated Dependabot lanes;
- Overview remains an independent Chart System surface and does not depend on #369 editor acceptance;
- `src/components/dashboard/temperature-chart.tsx` still owned a custom SVG history renderer that filtered invalid samples before path construction and could visually bridge communication/quality gaps;
- Overview already has its own authenticated latest/history/WebSocket delivery path through `useDashboardTelemetry`.

Product Owner Chart System priority therefore selected a new focused Overview migration without changing the preserved runtime sequence.

## Active Work Package — Issue #413

Issue #413 — **Migrate Overview temperature history to the canonical NEXOLAB Chart System** — is active on branch `feat/413-overview-chart-system`, Draft PR #414.

Implemented product slice:

- pure Overview temperature telemetry -> canonical Chart Domain mapper;
- exact stable node/equipment/channel/metric/unit identity;
- invalid-quality and >30 s source gaps become explicit continuity boundaries;
- canonical evidence-preserving reduction with 240-point target and evidence-safe fallback;
- deterministic canonical series tokens and compatible-unit grouping;
- Overview history uses `ChartShell` + `ChartRendererHost` + local ECharts Canvas instead of its independent telemetry SVG;
- shared exact cursor/inspector, show/hide/solo, zoom/pan/reset;
- rolling live updates use the persistent non-animated renderer path;
- live value cards, active XJP60D sensor-management selection and existing 1h/6h/24h history query contract remain separate and unchanged;
- authenticated production browser coverage checks Canvas/no-SVG, exact range request count, live host/canvas continuity, cursor layout stability, interaction side effects, responsive overflow and zero public runtime requests;
- shared `ChartShell` footer remains stacked until `2xl`, preventing the inspector from overlapping legend controls inside the narrower Overview card.

### GREEN software/offline checkpoint

Clean product/state head `cb65b4b08cd0087ea6b405de72c0a16f561e7541` passed:

- CI #2937 — GREEN: formatting, zero-warning lint, strict typecheck, 357 tests and production build;
- Authenticated Dashboard Acceptance #1625 — GREEN, 12/12 production Playwright;
- Refrigeration Browser Acceptance #1599 — GREEN;
- Offline Bundle #1008 — GREEN, including clean transferred-host simulation, blocked container egress, disconnected startup and update/rollback persistent-data preservation.

The earlier Authenticated Dashboard timeout on `373a9ac8...` was trace-diagnosed rather than timeout-relaxed. The Overview `Hide` control was overlapped by the shared Chart inspector because viewport `lg` enabled a two-column footer inside a narrow half-width chart card. The canonical footer now switches to two columns only at `2xl`. The next Authenticated Dashboard run passed 12/12 with the original interaction assertion intact.

The state/audit checkpoint recording these GREEN results changes branch SHA once more. All required canonical gates must rerun on that final checkpoint head before it is frozen for Raspberry Pi acceptance.

## Preserved independent lanes

Issue #369 remains Ready and separate. Preserved runtime sequence:

```text
#369 -> #366 -> #289
```

Issue #389 remains Ready/not selected.

Issue #245 remains a separate Raspberry Pi validation track. Issue #257 remains blocked. Issue #256 remains deferred.

## Safety boundary

Issue #413 changes no backend schema, PostgreSQL migration, telemetry REST/WebSocket contract, Device Agent, scheduler, registry, discovery, Modbus path, dependency version or hardware state.

No Modbus write or hardware write is permitted. No mandatory CDN, remote font, telemetry, external API, cloud renderer or paid runtime dependency is introduced.

The `telemetry-service/libcjson1/CVE-2026-67216` exception still expires on 2026-09-05 and is not broadened by #413.

## Next action

Complete the final state/audit checkpoint, rerun all canonical exact-head software/browser/offline gates, and freeze the resulting SHA only if GREEN. Then run controlled Raspberry Pi Overview acceptance on that exact frozen candidate before Ready/merge. Preserve #369, #389 and all hardware/write safety boundaries.
