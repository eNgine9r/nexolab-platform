import { describe, expect, it } from "vitest";

import type { ChartSeries } from "./domain";
import { assessHistoryCoverage } from "./history-coverage";

const T0 = Date.parse("2026-11-10T00:00:00Z");
const HOUR = 3_600_000;

function series(firstAtMs: number | null, visible = true): ChartSeries {
  return {
    identity: { metric: "m" } as ChartSeries["identity"],
    name: "m",
    colorToken: "c",
    dashStyle: "solid",
    markerShape: "circle",
    freshness: "live",
    segments:
      firstAtMs === null
        ? []
        : [
            {
              id: "s",
              seriesKey: "k",
              points: [{ id: "p", timestampMs: firstAtMs, value: 1, quality: "valid" }],
            },
          ],
    visible,
    semanticMode: "instantaneous",
  };
}

describe("history coverage (#1677)", () => {
  const window = { fromMs: T0, toMs: T0 + 168 * HOUR };

  it("reports a partial range when history starts well after the requested start", () => {
    const coverage = assessHistoryCoverage([series(T0 + 144 * HOUR)], window);
    expect(coverage?.kind).toBe("partial");
    expect(coverage?.availableFromMs).toBe(T0 + 144 * HOUR);
    expect(coverage?.coverageRatio).toBeCloseTo(24 / 168, 5);
  });

  it("is full when data reaches the start within poll slack and uses the earliest visible series", () => {
    expect(assessHistoryCoverage([series(T0 + 60_000)], window)?.kind).toBe("full");
    const mixed = assessHistoryCoverage(
      [series(T0 + 100 * HOUR), series(T0 + 2_000), series(T0, false)],
      window,
    );
    expect(mixed?.kind).toBe("full");
  });

  it("reports none without plotted data and ignores an invalid window", () => {
    expect(assessHistoryCoverage([series(null)], window)?.kind).toBe("none");
    expect(assessHistoryCoverage([series(T0)], { fromMs: 5, toMs: 5 })).toBeNull();
  });
});
