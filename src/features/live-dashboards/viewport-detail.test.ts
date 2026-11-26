import { describe, expect, it } from "vitest";

import {
  appendIntervalSample,
  computeIntervalStatistics,
  createIntervalSampleColumns,
  type IntervalSampleColumns,
  type IntervalStatistics,
} from "@/features/charts/interval-statistics";
import { isLiveHistorySegmentStart, markSegmentStart } from "@/features/live/live-history";
import type { TelemetrySample } from "@/lib/telemetry/types";

import {
  cachedIntervalStatistics,
  mergeSavedDashboardDetail,
  savedDashboardViewportDetail,
} from "./viewport-detail";

const T0 = Date.parse("2026-11-26T00:00:00Z");
const STEP = 10_000;

function sample(timestampMs: number, value: number | null, overrides: Partial<TelemetrySample> = {}) {
  return {
    event_id: `e-${timestampMs}`,
    node_id: "edge-01",
    equipment_id: "XJP60D-1",
    channel_id: "ch-1",
    metric: "temperature",
    unit: "degC",
    source: "test",
    captured_at: new Date(timestampMs).toISOString(),
    value,
    quality: value === null ? "communication_error" : "valid",
    alarm: null,
    raw_value: null,
    raw_status: null,
    ...overrides,
  } satisfies TelemetrySample;
}

function columnsOf(points: Array<[number, number | null]>): IntervalSampleColumns {
  const columns = createIntervalSampleColumns();
  for (const [timestampMs, value] of points) appendIntervalSample(columns, timestampMs, value);
  return columns;
}

/** One day at 10 s with a single sharp peak; one sample per index. */
function dayColumns(peakIndex: number, peakValue: number): IntervalSampleColumns {
  const points: Array<[number, number | null]> = [];
  for (let index = 0; index < 8_640; index += 1) {
    points.push([T0 + index * STEP, index === peakIndex ? peakValue : 4 + Math.sin(index / 50)]);
  }
  return columnsOf(points);
}

describe("savedDashboardViewportDetail (#1821)", () => {
  it("returns every original measurement of a narrow viewport plus margin", () => {
    const columns = dayColumns(4_000, 30);
    const domain = { fromMs: T0 + 3_990 * STEP, toMs: T0 + 4_010 * STEP };
    const detail = savedDashboardViewportDetail(
      [{ key: "item-1", identity: sample(T0, 4), columns, sourceGapMs: 30_000 }],
      domain,
      240,
      T0 + 9_000 * STEP,
    );
    const points = detail["item-1"].samples;
    // 20 steps visible, ±50 % margin: 40 steps → 41 samples, all original.
    expect(points).toHaveLength(41);
    expect(points.map((point) => point.value)).toContain(30);
    expect(points.every((point) => point.quality === "valid")).toBe(true);
    expect(points.some(isLiveHistorySegmentStart)).toBe(false);
  });

  it("keeps the peak and the extremes when the viewport exceeds the budget", () => {
    const columns = dayColumns(5_123, -18.5);
    const detail = savedDashboardViewportDetail(
      [{ key: "item-1", identity: sample(T0, 4), columns, sourceGapMs: 30_000 }],
      { fromMs: T0 + 3_000 * STEP, toMs: T0 + 7_000 * STEP },
      240,
      T0 + 9_000 * STEP,
    );
    const values = detail["item-1"].samples.map((point) => point.value);
    expect(values.length).toBeLessThanOrEqual(240 + 8);
    expect(values).toContain(-18.5);
  });

  it("breaks at a silent gap and at an invalid sample, never interpolating", () => {
    const points: Array<[number, number | null]> = [];
    for (let index = 0; index < 100; index += 1) {
      if (index >= 40 && index < 60) continue; // 200 s silent gap
      points.push([T0 + index * STEP, 5]);
    }
    points.push([T0 + 75 * STEP + 1, null]); // communication error between 75 and 76
    const detail = savedDashboardViewportDetail(
      [{ key: "item-1", identity: sample(T0, 5), columns: columnsOf(points), sourceGapMs: 30_000 }],
      { fromMs: T0 + 30 * STEP, toMs: T0 + 90 * STEP },
      240,
      T0 + 200 * STEP,
    );
    const starts = detail["item-1"].samples
      .filter(isLiveHistorySegmentStart)
      .map((point) => (Date.parse(point.captured_at) - T0) / STEP);
    expect(starts).toEqual([60, 76]);
  });

  it("plots operator-derived display values as they are (no second conversion)", () => {
    const embraco = sample(T0, null, {
      equipment_id: "EMBRACO-2",
      channel_id: "2-cabinet-temperature",
      metric: "temperature.cabinet",
      source: "embraco-sync",
      quality: "unknown",
      raw_value: 65_514,
    });
    const columns = columnsOf([
      [T0, -0.22],
      [T0 + STEP, -0.21],
      [T0 + 2 * STEP, -0.2],
    ]);
    const detail = savedDashboardViewportDetail(
      [{ key: "embraco", identity: embraco, columns, sourceGapMs: 30_000 }],
      { fromMs: T0, toMs: T0 + 2 * STEP },
      240,
      T0 + 10 * STEP,
    );
    expect(detail.embraco.samples.map((point) => [point.value, point.quality, point.raw_value])).toEqual([
      [-0.22, "valid", null],
      [-0.21, "valid", null],
      [-0.2, "valid", null],
    ]);
  });

  it("skips series without measurements in the viewport", () => {
    const detail = savedDashboardViewportDetail(
      [
        {
          key: "item-1",
          identity: sample(T0, 4),
          columns: columnsOf([[T0, 4]]),
          sourceGapMs: undefined,
        },
      ],
      { fromMs: T0 + 1_000 * STEP, toMs: T0 + 1_010 * STEP },
      240,
    );
    expect(detail).toEqual({});
  });
});

describe("mergeSavedDashboardDetail (#1821)", () => {
  it("replaces coarse points inside the detail and keeps newer live points", () => {
    const coarse = [0, 50, 100, 150].map((index) => sample(T0 + index * STEP, 1));
    const live = sample(T0 + 151 * STEP, 9);
    const columns = columnsOf(
      Array.from({ length: 151 }, (_, index) => [T0 + index * STEP, 2] as [number, number]),
    );
    const detail = savedDashboardViewportDetail(
      [{ key: "item-1", identity: coarse[0], columns, sourceGapMs: 30_000 }],
      { fromMs: T0 + 40 * STEP, toMs: T0 + 60 * STEP },
      240,
      T0 + 150 * STEP,
    );
    const merged = mergeSavedDashboardDetail([...coarse, live], detail["item-1"]);
    const timestamps = merged.map((point) => (Date.parse(point.captured_at) - T0) / STEP);
    expect(timestamps[0]).toBe(0);
    expect(timestamps).toContain(45);
    // Inside the detail range only original measurements (value 2) remain, no coarse point (1).
    const inside = merged.filter((point) => {
      const index = (Date.parse(point.captured_at) - T0) / STEP;
      return index >= 30 && index <= 70;
    });
    expect(inside.length).toBe(41);
    expect(inside.every((point) => point.value === 2)).toBe(true);
    expect(timestamps.at(-1)).toBe(151);
    expect(timestamps).toEqual([...timestamps].sort((left, right) => left - right));
  });

  it("keeps a coarse break at the detail boundary", () => {
    const coarse = [sample(T0, 1), markSegmentStart(sample(T0 + 50 * STEP, 1)), sample(T0 + 100 * STEP, 1)];
    const columns = columnsOf([
      [T0, 1],
      [T0 + 50 * STEP, 1],
      [T0 + 60 * STEP, 1],
      [T0 + 100 * STEP, 1],
    ]);
    const detail = savedDashboardViewportDetail(
      // Tolerance large enough that the detail itself sees no gap inside its range.
      [{ key: "item-1", identity: coarse[0], columns, sourceGapMs: 1_000_000 }],
      { fromMs: T0 + 45 * STEP, toMs: T0 + 65 * STEP },
      240,
      T0 + 100 * STEP,
    );
    const merged = mergeSavedDashboardDetail(coarse, detail["item-1"]);
    const boundary = merged.find((point) => Date.parse(point.captured_at) === T0 + 50 * STEP);
    expect(boundary && isLiveHistorySegmentStart(boundary)).toBe(true);
  });

  it("returns the history unchanged without detail", () => {
    const coarse = [sample(T0, 1), sample(T0 + STEP, 2)];
    expect(mergeSavedDashboardDetail(coarse, undefined)).toEqual(coarse);
  });
});

describe("cachedIntervalStatistics (#1821)", () => {
  it("returns the exact statistics and reuses them until the columns change", () => {
    const columns = dayColumns(100, 25);
    const cache = new Map<string, IntervalStatistics | null>();
    const first = cachedIntervalStatistics(cache, "item-1", columns, T0, T0 + 1_000 * STEP);
    expect(first).toEqual(computeIntervalStatistics(columns, T0, T0 + 1_000 * STEP));
    expect(cachedIntervalStatistics(cache, "item-1", columns, T0, T0 + 1_000 * STEP)).toBe(first);
    appendIntervalSample(columns, T0 + 8_640 * STEP, 40);
    const after = cachedIntervalStatistics(cache, "item-1", columns, T0, T0 + 9_000 * STEP);
    expect(after?.max).toBe(40);
    expect(cachedIntervalStatistics(cache, "item-1", undefined, T0, T0 + STEP)).toBeNull();
  });

  it("invalidates when an invalid sample arrives", () => {
    const columns = columnsOf([
      [T0, 1],
      [T0 + STEP, 2],
    ]);
    const cache = new Map<string, IntervalStatistics | null>();
    const before = cachedIntervalStatistics(cache, "item-1", columns, T0, T0 + 2 * STEP);
    appendIntervalSample(columns, T0 + STEP / 2, null);
    const after = cachedIntervalStatistics(cache, "item-1", columns, T0, T0 + 2 * STEP);
    expect(before?.invalidCount).toBe(0);
    expect(after?.invalidCount).toBe(1);
  });
});
