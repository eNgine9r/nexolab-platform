import { describe, expect, it } from "vitest";

import { computeIntervalStatistics, type IntervalStatistics } from "@/features/charts/interval-statistics";
import { columnsFromRawSamples } from "@/features/charts/raw-sample-statistics";
import { isLiveHistorySegmentStart } from "@/features/live/live-history";
import { recordLiveIntervalSamples } from "@/features/live/live-interval-columns";
import { liveChannelKey } from "@/features/live/live-telemetry";
import type { TelemetrySample } from "@/lib/telemetry/types";

import { buildOverviewChartBase, overviewChartGroupsForDomain } from "./overview-chart";
import {
  createOverviewHistoryStore,
  overviewDisplayHistory,
  overviewRecentTimestamps,
  overviewSeriesStatistics,
  overviewViewportDetail,
  recordOverviewSamples,
} from "./overview-history";

const T0 = Date.parse("2026-11-25T00:00:00Z");
const STEP = 10_000;
const DAY = 8_640;

function probe(index: number, overrides: Partial<TelemetrySample> = {}): TelemetrySample {
  return {
    event_id: `106-01-${index}`,
    node_id: "edge-01",
    captured_at: new Date(T0 + index * STEP).toISOString(),
    metric: "temperature",
    value: 4 + Math.sin(index / 40),
    unit: "degC",
    quality: "valid",
    source: "xjp60d",
    equipment_id: "XJP60D-1",
    channel_id: "106-01",
    alarm: null,
    raw_value: 40,
    raw_status: null,
    ...overrides,
  };
}

/** One day at 10 s: a sharp peak, a communication error and a 10 min silent gap. */
function day(): TelemetrySample[] {
  const samples: TelemetrySample[] = [];
  for (let index = 0; index < DAY; index += 1) {
    if (index >= 7_000 && index < 7_060) continue;
    if (index === 5_000) samples.push(probe(index, { value: 30 }));
    else if (index === 6_000) samples.push(probe(index, { value: null, quality: "communication_error" }));
    else samples.push(probe(index));
  }
  return samples;
}

const window = { from: new Date(T0), to: new Date(T0 + DAY * STEP) };

function loaded(samples = day()) {
  const store = createOverviewHistoryStore();
  // Slices arrive newest first and out of order, as the sliced loader delivers them.
  for (let end = samples.length; end > 0; end -= 1_000)
    recordOverviewSamples(store, samples.slice(Math.max(0, end - 1_000), end));
  return store;
}

describe("Overview RAW history columns (P0 charts)", () => {
  const raw = day();
  const store = loaded(raw);
  const key = liveChannelKey(raw[0]);

  it("keeps the peak and real breaks in the reduced display history", () => {
    const display = overviewDisplayHistory(store, window, 240, T0 + DAY * STEP);
    expect(display.length).toBeLessThanOrEqual(260);
    expect(display.map((sample) => sample.value)).toContain(30);
    const breaks = display
      .filter(isLiveHistorySegmentStart)
      .map((sample) => (Date.parse(sample.captured_at) - T0) / STEP);
    // After the communication error and after the silent gap; nothing joins across them.
    expect(breaks.some((index) => index > 6_000 && index <= 6_001)).toBe(true);
    expect(breaks.some((index) => index >= 7_060 && index <= 7_061)).toBe(true);
  });

  it("shows every original measurement of a zoomed window", () => {
    const detail = overviewViewportDetail(
      store,
      { fromMs: T0 + 4_990 * STEP, toMs: T0 + 5_010 * STEP },
      240,
      T0 + DAY * STEP,
    );
    expect(detail.samples).toHaveLength(41);
    expect(detail.samples.map((sample) => sample.value)).toContain(30);
  });

  it("gives exactly the statistics of the RAW samples, cached until the columns change", () => {
    const cache = new Map<string, IntervalStatistics | null>();
    const fromMs = T0 + 4_000 * STEP;
    const toMs = T0 + 8_000 * STEP;
    const expected = computeIntervalStatistics(columnsFromRawSamples(raw), fromMs, toMs);
    const first = overviewSeriesStatistics(store, cache, key, fromMs, toMs);
    expect(first).toEqual(expected);
    expect(overviewSeriesStatistics(store, cache, key, fromMs, toMs)).toBe(first);
    recordOverviewSamples(store, [probe(DAY, { value: 50 })]);
    expect(overviewSeriesStatistics(store, cache, key, fromMs, T0 + (DAY + 1) * STEP)?.max).toBe(50);
  });

  it("answers freshness from the newest RAW poll, including a failed one", () => {
    const failing = loaded([...day(), probe(DAY + 1, { value: null, quality: "communication_error" })]);
    expect(failing.latest.get(key)?.quality).toBe("communication_error");
    expect(overviewRecentTimestamps(failing.columns[key], 3).at(-1)).toBe(T0 + (DAY + 1) * STEP);
  });

  it("builds chart segments from the RAW breaks and keeps viewport detail within the bound", () => {
    const display = overviewDisplayHistory(store, window, 240, T0 + DAY * STEP);
    const zoom = { fromMs: T0 + 4_990 * STEP, toMs: T0 + 5_010 * STEP };
    const detail = overviewViewportDetail(store, zoom, 240, T0 + DAY * STEP);
    const merged = [
      ...display.filter((sample) => {
        const at = Date.parse(sample.captured_at);
        return at < detail.fromMs || at > detail.coveredToMs;
      }),
      ...detail.samples,
    ].sort((left, right) => Date.parse(left.captured_at) - Date.parse(right.captured_at));
    const rawSource = {
      latestFor: (seriesKey: string) => store.latest.get(seriesKey),
      recentTimestampsFor: (seriesKey: string) => overviewRecentTimestamps(store.columns[seriesKey], 20),
    };
    const [group] = overviewChartGroupsForDomain(
      buildOverviewChartBase({
        samples: merged,
        status: "live",
        historical: false,
        rawSource,
        now: T0 + DAY * STEP,
      }),
      zoom,
    );
    const series = group.scene.series[0];
    const inside = series.segments
      .flatMap((segment) => segment.points)
      .filter((point) => point.timestampMs >= detail.fromMs && point.timestampMs <= detail.toMs);
    expect(inside).toHaveLength(41);
    expect(series.segments.length >= 3).toBe(true);
  });

  it("merges slices in any order exactly like row-by-row recording (duplicates and failures included)", () => {
    const rows = day();
    rows.push(probe(10, { event_id: "duplicate-10", value: 99 })); // same timestamp: first one wins
    const slices: TelemetrySample[][] = [];
    for (let start = 0; start < rows.length; start += 700) slices.push(rows.slice(start, start + 700));
    const order = [...slices.slice(3), ...slices.slice(0, 3).reverse()];
    // The same slice order recorded row by row: the first recorded copy of a timestamp wins in both.
    const reference = createOverviewHistoryStore();
    for (const slice of order) recordLiveIntervalSamples(reference.columns, slice);
    const merged = createOverviewHistoryStore();
    for (const slice of order) recordOverviewSamples(merged, slice);
    const key = liveChannelKey(rows[0]);
    expect(merged.columns[key]).toEqual(reference.columns[key]);
  });

  it("records 30 days of newest-first slices in bounded time", () => {
    const store = createOverviewHistoryStore();
    const started = performance.now();
    for (let slice = 119; slice >= 0; slice -= 1) {
      const rows: TelemetrySample[] = [];
      for (let index = slice * 2_160; index < (slice + 1) * 2_160; index += 1) rows.push(probe(index));
      recordOverviewSamples(store, rows);
    }
    expect(store.columns[key].validTimestamps).toHaveLength(259_200);
    // Row-by-row insertion of older slices took ~36 s; the merge takes well under a few seconds.
    expect(performance.now() - started).toBeLessThan(8_000);
  });
});
