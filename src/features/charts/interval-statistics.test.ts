import { describe, expect, it } from "vitest";

import {
  appendIntervalSample,
  computeIntervalStatistics,
  createIntervalSampleColumns,
  pruneIntervalSamplesBefore,
} from "./interval-statistics";

const T0 = Date.parse("2026-11-22T00:00:00Z");

function columnsEvery(cadenceMs: number, count: number, valueAt: (index: number) => number) {
  const columns = createIntervalSampleColumns();
  for (let index = 0; index < count; index += 1) {
    appendIntervalSample(columns, T0 + index * cadenceMs, valueAt(index));
  }
  return columns;
}

describe("interval statistics from raw persisted samples", () => {
  it("reports exact min/max/average/count and full coverage for a regular 10 s series", () => {
    const columns = columnsEvery(10_000, 61, (index) => index); // 0..60 over 10 minutes
    const stats = computeIntervalStatistics(columns, T0, T0 + 600_000);
    expect(stats).toMatchObject({
      min: 0,
      max: 60,
      average: 30,
      averageStatus: "available",
      validCount: 61,
      invalidCount: 0,
      cadenceMs: 10_000,
      expectedCount: 61,
      coverageStatus: "sufficient",
      basis: "raw_persisted",
    });
    expect(stats.coverageRatio).toBe(1);
    expect(stats.gaps).toEqual({ count: 0, totalMs: 0, longestMs: 0 });
  });

  it("works for 60 s cadence and an arbitrary sub-interval (zoom)", () => {
    const columns = columnsEvery(60_000, 121, (index) => 100 + index); // 2 hours
    const stats = computeIntervalStatistics(columns, T0 + 30 * 60_000, T0 + 60 * 60_000);
    expect(stats.validCount).toBe(31);
    expect(stats.min).toBe(130);
    expect(stats.max).toBe(160);
    expect(stats.average).toBe(145);
    expect(stats.cadenceMs).toBe(60_000);
    expect(stats.coverageStatus).toBe("sufficient");
  });

  it("keeps a short extreme excursion in min/max (never reduced away)", () => {
    const columns = columnsEvery(10_000, 361, () => 4);
    appendIntervalSample(columns, T0 + 1_805_000, 41.5);
    const stats = computeIntervalStatistics(columns, T0, T0 + 3_600_000);
    expect(stats.max).toBe(41.5);
    expect(stats.min).toBe(4);
  });

  it("counts non-valid samples separately and never treats them as zero", () => {
    const columns = columnsEvery(10_000, 31, () => 5);
    appendIntervalSample(columns, T0 + 15_000, null);
    appendIntervalSample(columns, T0 + 25_000, Number.NaN);
    const stats = computeIntervalStatistics(columns, T0, T0 + 300_000);
    expect(stats.invalidCount).toBe(2);
    expect(stats.validCount).toBe(31);
    expect(stats.min).toBe(5);
    expect(stats.average).toBe(5);
  });

  it("withholds the average when half the interval has no measurements, but keeps min/max and gaps", () => {
    const columns = createIntervalSampleColumns();
    for (let index = 0; index < 30; index += 1) appendIntervalSample(columns, T0 + index * 10_000, 2 + index);
    // sensor silent for 20 minutes, then two last points
    appendIntervalSample(columns, T0 + 1_500_000, 8);
    appendIntervalSample(columns, T0 + 1_510_000, 9);
    const stats = computeIntervalStatistics(columns, T0, T0 + 1_800_000);
    expect(stats.average).toBeNull();
    expect(stats.averageStatus).toBe("insufficient_coverage");
    expect(stats.coverageStatus).toBe("insufficient");
    expect(stats.coverageRatio).toBeLessThan(0.8);
    expect(stats.min).toBe(2);
    expect(stats.max).toBe(31);
    expect(stats.gaps.count).toBe(1);
    expect(stats.gaps.longestMs).toBe(1_500_000 - 290_000);
  });

  it("returns an explicit no-data result instead of zeros", () => {
    const stats = computeIntervalStatistics(createIntervalSampleColumns(), T0, T0 + 60_000);
    expect(stats).toMatchObject({
      min: null,
      max: null,
      average: null,
      averageStatus: "no_data",
      validCount: 0,
      coverageStatus: "no_data",
    });
  });

  it("does not report an average from fewer than three samples", () => {
    const columns = columnsEvery(10_000, 2, () => 3);
    const stats = computeIntervalStatistics(columns, T0, T0 + 10_000);
    expect(stats.validCount).toBe(2);
    expect(stats.average).toBeNull();
    expect(stats.min).toBe(3);
  });

  it("ignores duplicate timestamps and keeps out-of-order inserts sorted", () => {
    const columns = createIntervalSampleColumns();
    appendIntervalSample(columns, T0 + 20_000, 2);
    appendIntervalSample(columns, T0, 0);
    appendIntervalSample(columns, T0 + 10_000, 1);
    appendIntervalSample(columns, T0 + 10_000, 99);
    expect(columns.validTimestamps).toEqual([T0, T0 + 10_000, T0 + 20_000]);
    expect(columns.validValues).toEqual([0, 1, 2]);
  });

  it("prunes samples that left a rolling window", () => {
    const columns = columnsEvery(10_000, 10, (index) => index);
    appendIntervalSample(columns, T0 + 5_000, null);
    pruneIntervalSamplesBefore(columns, T0 + 50_000);
    expect(columns.validTimestamps[0]).toBe(T0 + 50_000);
    expect(columns.invalidTimestamps).toEqual([]);
  });

  it("uses an explicitly supplied cadence for coverage", () => {
    const columns = columnsEvery(60_000, 11, () => 1);
    const stats = computeIntervalStatistics(columns, T0, T0 + 600_000, { cadenceMs: 10_000 });
    expect(stats.expectedCount).toBe(61);
    expect(stats.coverageStatus).toBe("insufficient");
  });
});
