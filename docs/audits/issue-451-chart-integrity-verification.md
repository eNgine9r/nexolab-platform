# Issue 451 — Chart integrity verification matrix

Parent Epic: #450  
Implementation PR: #452

## Safety boundary

- frontend/read-model only;
- no Modbus write;
- no hardware write;
- no acquisition scheduler/configuration mutation;
- no database migration;
- no dependency upgrade;
- no mandatory cloud/runtime service.

## Source-backed defect coverage

| Risk | Implementation evidence | Automated evidence |
|---|---|---|
| false 30 s chart gaps | cadence-aware continuity threshold | `continuity.test.ts`, Overview tests, production Live fixture |
| explicit communication loss hidden/renamed | failure provenance has precedence over silent timestamp gap | `continuity.test.ts`, production accessible continuity-break count |
| malformed renderer input | non-finite timestamp/value rejected before valid point render | `continuity.test.ts`, formatter tests |
| history/live duplicate/remount | stable event dedupe and stable segment identity | continuity tests + production renderer host/canvas persistence |
| Exact Inspector selects only one global point | one cursor snapshot resolves every visible series | ECharts adapter and ChartShell tests + production inspector rows |
| slow cadence inspector flicker | per-series cadence-aware cursor tolerance | ECharts adapter slow-source test |
| inspector borrows across real gap | explicit segment boundary is a hard cursor boundary | ECharts adapter gap-safe cursor test |
| excessive floating precision | centralized two-decimal presentation default | formatter/component tests + production `9.876 → 9.88` assertion |
| value and placeholder overlap | mutually exclusive inspector value state | ChartShell component test |
| phantom `Alarm context` annotations | telemetry sample alarm context no longer synthesizes event/pin | Overview/Live/Saved tests + production `alarm='high'` fixture |
| duplicate/colliding event labels | stable-ID event dedupe, source validation, hidden default labels | ECharts adapter test |
| chart interaction changes acquisition | unchanged read-model boundary | Authenticated Dashboard Acceptance zero-mutation assertions |
| cloud/offline regression | no new runtime dependency | disconnected Offline Bundle workflow |

## Required final gates

The Work Package is software-complete only when the exact final PR head has:

- repository format check GREEN;
- lint GREEN;
- TypeScript typecheck GREEN;
- Vitest suite GREEN;
- production build GREEN;
- Authenticated Dashboard Acceptance GREEN;
- Refrigeration Browser Acceptance GREEN where triggered;
- disconnected Offline Bundle GREEN;
- focused diff/review audit complete;
- project state reconciled.

Raspberry Pi browser evidence is a separate acceptance class and must not be inferred from CI.
