import { describe, expect, it } from "vitest";

import type { ChartPoint, ChartSegment } from "./domain";
import {
  CHART_POINT_BUDGET_DEFAULT,
  CHART_POINT_BUDGET_EXCEPTIONS,
  chartPointBudget,
  reduceChartSegmentsToPointBudget,
  type ChartPointBudgetSurface,
} from "./point-budget";

function point(id: string, timestampMs: number, value: number, pin = false): ChartPoint {
  return {
    id,
    timestampMs,
    value,
    quality: "valid",
    ...(pin ? { pinReasons: ["alarm"] as const } : {}),
  };
}

function segment(points: ChartPoint[]): ChartSegment {
  return { id: "segment-1", seriesKey: "series-1", points };
}

const SURFACES: readonly ChartPointBudgetSurface[] = [
  "overview",
  "live-history",
  "saved-dashboard",
  "energy-history",
  "refrigeration-controller",
  "renderer-live-tail",
];

describe("canonical chart point-budget policy", () => {
  it("uses one 240-point per-series target with no current surface exceptions", () => {
    expect(CHART_POINT_BUDGET_DEFAULT).toBe(240);
    expect(CHART_POINT_BUDGET_EXCEPTIONS).toEqual({});
    expect(SURFACES.map((surface) => chartPointBudget(surface))).toEqual(SURFACES.map(() => 240));
  });

  it("preserves extrema while reducing ordinary history to the policy target", () => {
    const source = Array.from({ length: 500 }, (_, index) =>
      point(`p-${index}`, index, index === 173 ? -80 : index === 311 ? 140 : index % 17),
    );
    const reduced = reduceChartSegmentsToPointBudget([segment(source)], "overview");
    const points = reduced.flatMap((item) => item.points);

    expect(points.length).toBeLessThanOrEqual(CHART_POINT_BUDGET_DEFAULT);
    expect(points[0]?.id).toBe("p-0");
    expect(points.at(-1)?.id).toBe("p-499");
    expect(points.some((item) => item.value === -80)).toBe(true);
    expect(points.some((item) => item.value === 140)).toBe(true);
  });

  it("allows evidence-only overflow instead of discarding required pins", () => {
    const source = Array.from({ length: 241 }, (_, index) => point(`pin-${index}`, index, index, true));
    const reduced = reduceChartSegmentsToPointBudget([segment(source)], "refrigeration-controller");

    expect(reduced.flatMap((item) => item.points)).toHaveLength(241);
  });
});
