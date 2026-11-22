# Chart density benchmark (#1620 / WP-E)

Purpose: justify the user-selectable detail modes (Авто / 250 / 500 / 1 000 / 2 500 / 5 000 points per series) and the aggregate point caps in `src/features/charts/density.ts`.

## Method

- Harness: `tests/chart-benchmark` (`runDensity`), driven by `node tests/chart-benchmark/density-matrix.mjs`.
- Scenario: initial ECharts Canvas render of `N` series × `P` points on the canonical `EChartsRendererAdapter` (one scene, 1440×900 viewport), 7 iterations, median and p95; plus the cost of reducing 30 000 raw points to the budget with the evidence-preserving reducer (`reduceChartSegments`).
- Environment: **development workstation**, headless Chromium (Playwright 1.62) on Windows 11, 2026-11-22. This is **not** the Raspberry Pi browser. No Raspberry Pi measurement was taken in this work package.

## Measured results (desktop headless Chromium)

| Series | Points / series | Aggregate points | Median ms |  p95 ms | Reduce 30 000 → budget ms |
| -----: | --------------: | ---------------: | --------: | ------: | ------------------------: |
|      1 |             240 |              240 |      32.9 |    33.8 |                      20.3 |
|      1 |             500 |              500 |      32.9 |    33.8 |                      14.8 |
|      1 |           1 000 |            1 000 |      33.5 |    50.6 |                      16.0 |
|      1 |           2 500 |            2 500 |      50.7 |    54.0 |                      17.8 |
|      1 |           5 000 |            5 000 |      92.0 |   119.3 |                      15.1 |
|      8 |             240 |            1 920 |      47.1 |    48.0 |                      19.9 |
|      8 |             500 |            4 000 |      65.6 |    81.2 |                      17.4 |
|      8 |           1 000 |            8 000 |     124.6 |   144.3 |                      16.7 |
|      8 |           2 500 |           20 000 |     322.2 |   365.1 |                      25.1 |
|      8 |           5 000 |           40 000 |     634.4 |   669.8 |                      13.1 |
|     24 |             240 |            5 760 |      97.3 |   120.2 |                      17.0 |
|     24 |             500 |           12 000 |     187.4 |   207.7 |                      13.7 |
|     24 |           1 000 |           24 000 |     361.0 |   386.8 |                      16.7 |
|     24 |           2 500 |           60 000 |     946.1 |   965.9 |                      11.1 |
|     24 |           5 000 |          120 000 |   1 818.4 | 1 943.9 |                      12.8 |

Render cost is approximately linear in the **aggregate** number of rendered points (≈ 33 ms base + ≈ 15 ms per 1 000 points on this machine). Reduction cost is small and independent of the target budget (≈ 11–25 ms for 30 000 raw points).

## Consequences encoded in the product

- **Aggregate cap 6 000 points** for every manual mode and **Auto target 3 840 points**. 5 000 × 24 series (120 000 points, ≈ 1.8 s here) can never be requested: it is lowered to 250 per series and the UI says so.
- Auto never exceeds the accepted 240-point default (the #1167 Raspberry Pi decision stands) and only lowers it for many series (24 series → 160).
- A single series may use 5 000 points (≈ 92 ms here).

## What is NOT proven

- Raspberry Pi timings. #1167 measured 8 × 240 at a median of 113 ms on the Pi versus 47 ms here (≈ 2.4×). Extrapolating that factor gives roughly 150 ms (Auto target) and 230–290 ms (cap) on the Pi, against the 250 ms p95 target and 1 s hard ceiling in the chart specification. **This is an estimate**; a measurement on the controlled Raspberry Pi browser is required before the manual modes are described as Pi-validated, and the cap should be lowered if that measurement exceeds the targets.
- Interaction latency (hover/zoom) at high budgets and mobile devices were not measured here.
