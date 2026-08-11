import { describe, expect, it } from "vitest";

import type { ChartPoint } from "./domain";
import { calculateChartStatistics } from "./statistics";

const points: ChartPoint[] = [
  { id: "a", timestampMs: 0, value: 1, quality: "valid" },
  { id: "b", timestampMs: 1, value: 9, quality: "valid" },
  { id: "c", timestampMs: 2, value: 2, quality: "valid" },
];

describe("chart statistics scope", () => {
  it("carries an explicit full-window scope and sample count", () => {
    expect(calculateChartStatistics(points, "requested_interval", 0, 2)).toEqual({
      current: 2,
      min: 1,
      max: 9,
      average: 4,
      sampleCount: 3,
      scope: "requested_interval",
      fromMs: 0,
      toMs: 2,
    });
  });

  it("labels reduced-point statistics as reduced visualization", () => {
    const result = calculateChartStatistics([points[0], points[2]], "reduced_visualization", 0, 2);
    expect(result.scope).toBe("reduced_visualization");
    expect(result.sampleCount).toBe(2);
  });

  it("selects current by timestamp rather than input order", () => {
    const result = calculateChartStatistics([points[2], points[0]], "requested_interval", 0, 2);
    expect(result.current).toBe(2);
  });
});
