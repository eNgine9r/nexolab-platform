import { afterEach, describe, expect, it } from "vitest";

import { CHART_AUTO_AGGREGATE_POINTS, CHART_AUTO_MINIMUM_POINTS, resolveChartPointBudget } from "./density";
import { CHART_POINT_BUDGET_DEFAULT } from "./point-budget";
import {
  CHART_ADAPTIVE_AGGREGATE_MAX,
  CHART_ADAPTIVE_AGGREGATE_MIN,
  CHART_DEFAULT_PLOT_WIDTH_PX,
  adaptiveAggregatePoints,
  chartPlotWidthPx,
  recordChartRenderCost,
  reportChartPlotWidth,
  resetChartViewportBudgetState,
  resolveViewportPointBudget,
  subscribeChartPlotWidth,
} from "./viewport-budget";

afterEach(() => resetChartViewportBudgetState());

describe("#1844 adaptive viewport point budget", () => {
  it("gives a single wide chart about two points per pixel instead of 240", () => {
    expect(
      resolveViewportPointBudget({
        mode: "auto",
        seriesCount: 1,
        plotWidthPx: 1_280,
        aggregatePoints: 3_840,
      }),
    ).toBe(2_560);
    expect(
      resolveViewportPointBudget({
        mode: "auto",
        seriesCount: 6,
        plotWidthPx: 1_280,
        aggregatePoints: 3_840,
      }),
    ).toBe(640);
  });

  it("keeps 24 series within the accepted Raspberry Pi total", () => {
    const perSeries = resolveViewportPointBudget({
      mode: "auto",
      seriesCount: 24,
      plotWidthPx: 1_920,
      aggregatePoints: CHART_AUTO_AGGREGATE_POINTS,
    });
    expect(perSeries).toBe(160);
    expect(perSeries * 24).toBeLessThanOrEqual(CHART_AUTO_AGGREGATE_POINTS);
    expect(
      resolveViewportPointBudget({
        mode: "auto",
        seriesCount: 64,
        plotWidthPx: 1_920,
        aggregatePoints: 3_840,
      }),
    ).toBe(CHART_AUTO_MINIMUM_POINTS);
  });

  it("never goes below the accepted default on a narrow plot, and respects manual modes", () => {
    expect(
      resolveViewportPointBudget({ mode: "auto", seriesCount: 1, plotWidthPx: 60, aggregatePoints: 3_840 }),
    ).toBe(CHART_POINT_BUDGET_DEFAULT);
    expect(resolveViewportPointBudget({ mode: 500, seriesCount: 4, plotWidthPx: 3_000 })).toBe(
      resolveChartPointBudget(500, 4).perSeries,
    );
  });

  it("follows the widest mounted plot, quantized, and notifies only on a real change", () => {
    let notifications = 0;
    const unsubscribe = subscribeChartPlotWidth(() => (notifications += 1));
    expect(chartPlotWidthPx()).toBe(CHART_DEFAULT_PLOT_WIDTH_PX);
    reportChartPlotWidth("a", 700);
    expect(chartPlotWidthPx()).toBe(640);
    reportChartPlotWidth("b", 1_500);
    expect(chartPlotWidthPx()).toBe(1_536);
    // A few pixels of resize change nothing.
    reportChartPlotWidth("b", 1_510);
    expect(notifications).toBe(2);
    reportChartPlotWidth("b", null);
    expect(chartPlotWidthPx()).toBe(640);
    reportChartPlotWidth("a", null);
    expect(chartPlotWidthPx()).toBe(CHART_DEFAULT_PLOT_WIDTH_PX);
    unsubscribe();
  });

  it("adapts the page total to the measured render cost within fixed bounds", () => {
    expect(adaptiveAggregatePoints()).toBe(CHART_AUTO_AGGREGATE_POINTS);
    // Small renders and too few measurements do not count.
    recordChartRenderCost(100, 50);
    recordChartRenderCost(4_000, 2);
    recordChartRenderCost(4_000, 2);
    expect(adaptiveAggregatePoints()).toBe(CHART_AUTO_AGGREGATE_POINTS);
    // A fast PC: 4 000 points in 2 ms → capped at 2.5 × the Pi target.
    recordChartRenderCost(4_000, 2);
    expect(adaptiveAggregatePoints()).toBe(CHART_ADAPTIVE_AGGREGATE_MAX);

    resetChartViewportBudgetState();
    // A slow device: 4 000 points in 60 ms → never below half the Pi target.
    for (let index = 0; index < 4; index += 1) recordChartRenderCost(4_000, 60);
    expect(adaptiveAggregatePoints()).toBe(CHART_ADAPTIVE_AGGREGATE_MIN);

    resetChartViewportBudgetState();
    // 4 000 points in 10 ms: 16 ms fits 6 400, published as a multiple of 480.
    for (let index = 0; index < 4; index += 1) recordChartRenderCost(4_000, 10);
    expect(adaptiveAggregatePoints()).toBe(6_240);
  });

  it("does not change the budget on ordinary render-time variation (review)", () => {
    for (let index = 0; index < 4; index += 1) recordChartRenderCost(4_000, 10);
    const published = adaptiveAggregatePoints();
    const budgets = new Set<number>();
    for (let index = 0; index < 40; index += 1) {
      recordChartRenderCost(4_000, index % 2 === 0 ? 10 : 11);
      expect(adaptiveAggregatePoints()).toBe(published);
      budgets.add(resolveViewportPointBudget({ mode: "auto", seriesCount: 6, plotWidthPx: 1_280 }));
    }
    expect(budgets.size).toBe(1);
  });
});

describe("#1844 review: aggregate detail never exceeds the API bucket limit", () => {
  it("caps buckets at the server's 2 000 even when the budget asks for more", async () => {
    const { aggregateBucketCount, AGGREGATE_MAX_BUCKETS } =
      await import("@/features/live/live-aggregate-history");
    const budget = resolveViewportPointBudget({
      mode: "auto",
      seriesCount: 1,
      plotWidthPx: 4_608,
      aggregatePoints: CHART_ADAPTIVE_AGGREGATE_MAX,
    });
    expect(budget).toBeGreaterThan(8_000);
    expect(aggregateBucketCount(budget)).toBe(AGGREGATE_MAX_BUCKETS);
    expect(aggregateBucketCount(240)).toBe(60);
    expect(aggregateBucketCount(1)).toBe(1);
  });
});
