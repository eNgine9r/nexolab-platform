import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CHART_AGGREGATE_POINT_CAP,
  CHART_AUTO_AGGREGATE_POINTS,
  CHART_DENSITY_MODES,
  chartDensityLabel,
  isChartDensityMode,
  readStoredChartDensity,
  resolveChartPointBudget,
  storeChartDensity,
} from "./density";
import { CHART_POINT_BUDGET_DEFAULT } from "./point-budget";

describe("chart density budget resolution", () => {
  it("offers exactly Auto / 250 / 500 / 1000 / 2500 / 5000", () => {
    expect([...CHART_DENSITY_MODES]).toEqual(["auto", 250, 500, 1000, 2500, 5000]);
    expect(chartDensityLabel("auto")).toBe("Авто");
  });

  it("Auto keeps the accepted default for ordinary dashboards and never exceeds it", () => {
    for (const count of [1, 4, 8, 16]) {
      expect(resolveChartPointBudget("auto", count).perSeries).toBe(CHART_POINT_BUDGET_DEFAULT);
    }
  });

  it("Auto lowers the per-series budget for many series, bounded by the aggregate target", () => {
    const resolution = resolveChartPointBudget("auto", 24);
    expect(resolution.perSeries).toBe(160);
    expect(resolution.aggregate).toBeLessThanOrEqual(CHART_AUTO_AGGREGATE_POINTS);
    expect(resolveChartPointBudget("auto", 64).perSeries).toBe(100);
  });

  it("honours a manual mode while the aggregate cap allows it", () => {
    expect(resolveChartPointBudget(5000, 1)).toMatchObject({ perSeries: 5000, capped: false });
    expect(resolveChartPointBudget(1000, 4)).toMatchObject({ perSeries: 1000, capped: false });
  });

  it("never allows 5000 × 24 series: the aggregate cap applies and is reported", () => {
    const resolution = resolveChartPointBudget(5000, 24);
    expect(resolution.capped).toBe(true);
    expect(resolution.requested).toBe(5000);
    expect(resolution.perSeries).toBe(250);
    expect(resolution.aggregate).toBeLessThanOrEqual(CHART_AGGREGATE_POINT_CAP);
    for (const mode of CHART_DENSITY_MODES) {
      for (const count of [1, 2, 8, 24, 48]) {
        const resolved = resolveChartPointBudget(mode, count);
        // Only the readability floor can push a huge series count above the cap.
        if (resolved.perSeries > 100)
          expect(resolved.aggregate).toBeLessThanOrEqual(CHART_AGGREGATE_POINT_CAP);
      }
    }
  });

  it("treats a non-finite series count as one series", () => {
    expect(resolveChartPointBudget(250, Number.NaN).perSeries).toBe(250);
  });
});

describe("chart density preference storage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("round-trips a valid preference and ignores invalid values", () => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => store.set(key, value),
    });
    expect(readStoredChartDensity("saved-dashboard")).toBe("auto");
    storeChartDensity("saved-dashboard", 1000);
    expect(readStoredChartDensity("saved-dashboard")).toBe(1000);
    store.set("nexolab:chart-density:saved-dashboard", "777");
    expect(readStoredChartDensity("saved-dashboard")).toBe("auto");
    expect(isChartDensityMode(5000)).toBe(true);
    expect(isChartDensityMode("fast")).toBe(false);
  });

  it("falls back to Auto when storage throws", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    });
    expect(readStoredChartDensity("x")).toBe("auto");
    expect(() => storeChartDensity("x", 500)).not.toThrow();
  });
});
