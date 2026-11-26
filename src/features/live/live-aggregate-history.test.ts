import { describe, expect, it, vi } from "vitest";

import { computeIntervalStatistics } from "@/features/charts/interval-statistics";
import { TelemetryClientError } from "@/lib/telemetry/errors";
import {
  isAggregateUnsupported,
  type HistoryAggregateQuery,
  type HistoryAggregateSeries,
} from "@/lib/telemetry/history-aggregate";
import { RequestLimiter } from "@/lib/telemetry/request-limiter";
import { TelemetryRestClient, type TelemetryFetch } from "@/lib/telemetry/rest-client";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

import {
  aggregateSeriesToSamples,
  columnsViewportDetail,
  loadAggregatedLiveHistory,
  mergeViewportDetail,
  wireToIntervalStatistics,
} from "./live-aggregate-history";
import { isLiveHistorySegmentStart, liveHistorySegments } from "./live-history";
import { recordLiveIntervalSamples, type LiveIntervalColumns } from "./live-interval-columns";
import { liveChannelKey } from "./live-telemetry";

const T0 = Date.parse("2026-11-26T00:00:00Z");

function identity(channel = "ch-1"): TelemetrySample {
  return {
    event_id: `latest-${channel}`,
    node_id: "edge-01",
    equipment_id: "XJP60D-1",
    channel_id: channel,
    metric: "temperature",
    unit: "degC",
    source: "test",
    captured_at: new Date(T0).toISOString(),
    value: 4,
    quality: "valid",
    alarm: null,
    raw_value: null,
    raw_status: null,
  };
}

function bucket(
  index: number,
  points: { first: [number, number]; min: [number, number]; max: [number, number]; last: [number, number] },
  invalid: [number, number] | null = null,
) {
  return {
    index,
    count: 10,
    validCount: invalid ? 9 : 10,
    invalidCount: invalid ? 1 : 0,
    firstInvalidMs: invalid?.[0] ?? null,
    lastInvalidMs: invalid?.[1] ?? null,
    first: points.first,
    last: points.last,
    minimum: points.min,
    maximum: points.max,
  };
}

function series(buckets: HistoryAggregateSeries["buckets"]): HistoryAggregateSeries {
  return {
    node_id: "edge-01",
    equipment_id: "XJP60D-1",
    channel_id: "ch-1",
    metric: "temperature",
    unit: "degC",
    mode: "aggregate",
    count: buckets.length * 10,
    validCount: buckets.length * 10,
    raw: [],
    buckets,
    statistics: null,
  };
}

describe("aggregated history display (#1813)", () => {
  it("draws only real bucket measurements, keeps the spike and breaks at missing buckets and invalid samples", () => {
    const minute = 60_000;
    const buckets = [
      bucket(0, {
        first: [T0, 4],
        min: [T0 + 10_000, 3.9],
        max: [T0 + 20_000, 19.5],
        last: [T0 + 50_000, 4.1],
      }),
      bucket(1, {
        first: [T0 + minute, 4.2],
        min: [T0 + minute, 4.2],
        max: [T0 + minute + 5_000, 4.3],
        last: [T0 + minute + 50_000, 4.25],
      }),
      // bucket 2 and 3 missing: four minutes of silence
      bucket(
        4,
        {
          first: [T0 + 4 * minute, 4],
          min: [T0 + 4 * minute, 4],
          max: [T0 + 4 * minute, 4],
          last: [T0 + 4 * minute + 40_000, 4.1],
        },
        [T0 + 4 * minute + 20_000, T0 + 4 * minute + 20_000],
      ),
    ];
    const samples = aggregateSeriesToSamples(identity(), series(buckets), minute, 30_000);
    const real = new Set(
      buckets
        .flatMap((item) => [item.first, item.minimum, item.maximum, item.last])
        .map((point) => `${point![0]}:${point![1]}`),
    );
    expect(samples.every((sample) => real.has(`${Date.parse(sample.captured_at)}:${sample.value}`))).toBe(
      true,
    );
    expect(Math.max(...samples.map((sample) => sample.value!))).toBe(19.5);
    // Breaks: after the 4-minute silence, and across the invalid sample in bucket 4.
    expect(liveHistorySegments(samples)).toHaveLength(3);
  });

  it("maps server statistics to the same result as raw-column statistics", () => {
    const columns: LiveIntervalColumns = {};
    const raw: TelemetrySample[] = [];
    for (let index = 0; index < 400; index += 1) {
      if (index >= 200 && index < 230) continue; // 300 s silence
      raw.push({
        ...identity(),
        event_id: `e-${index}`,
        captured_at: new Date(T0 + index * 10_000).toISOString(),
        value: index === 50 ? null : 4 + (index % 9) / 10,
        quality: index === 50 ? "communication_error" : "valid",
      });
    }
    recordLiveIntervalSamples(columns, raw);
    const key = liveChannelKey(raw[0]);
    const fromMs = T0;
    const toMs = T0 + 4_000_000;
    const expected = computeIntervalStatistics(columns[key], fromMs, toMs);
    const valid = raw.filter((sample) => sample.quality === "valid");
    const wire = {
      valid_count: valid.length,
      invalid_count: 1,
      minimum: Math.min(...valid.map((sample) => sample.value!)),
      maximum: Math.max(...valid.map((sample) => sample.value!)),
      valid_sum: valid.reduce((sum, sample) => sum + sample.value!, 0),
      first_valid_ms: T0,
      last_valid_ms: Date.parse(valid.at(-1)!.captured_at),
      median_spacing_ms: 10_000,
      gap_count: expected.gaps.count,
      gap_total_ms: expected.gaps.totalMs,
      gap_longest_ms: expected.gaps.longestMs,
      recent_valid_ms: [],
    };
    const mapped = wireToIntervalStatistics(wire, fromMs, toMs);
    expect(mapped.validCount).toBe(expected.validCount);
    expect(mapped.invalidCount).toBe(expected.invalidCount);
    expect(mapped.min).toBe(expected.min);
    expect(mapped.max).toBe(expected.max);
    expect(mapped.cadenceMs).toBe(expected.cadenceMs);
    expect(mapped.expectedCount).toBe(expected.expectedCount);
    expect(mapped.coverageRatio).toBeCloseTo(expected.coverageRatio!, 12);
    expect(mapped.averageStatus).toBe(expected.averageStatus);
    if (expected.average !== null) expect(mapped.average).toBeCloseTo(expected.average, 9);
    expect(mapped.gaps).toEqual(expected.gaps);
  });
});

describe("viewport detail (#1813)", () => {
  function columnsFor(
    count: number,
    cadenceMs: number,
    spikeAt: number,
  ): { columns: LiveIntervalColumns; key: string } {
    const columns: LiveIntervalColumns = {};
    const raw: TelemetrySample[] = [];
    for (let index = 0; index < count; index += 1) {
      raw.push({
        ...identity(),
        event_id: `e-${index}`,
        captured_at: new Date(T0 + index * cadenceMs).toISOString(),
        value: index === spikeAt ? 25 : index === 300 ? null : 4 + (index % 5) / 10,
        quality: index === 300 ? "communication_error" : "valid",
      });
    }
    recordLiveIntervalSamples(columns, raw);
    return { columns, key: liveChannelKey(raw[0]) };
  }

  it("returns every original measurement of the visible window with real breaks", () => {
    const { columns } = columnsFor(8_640, 10_000, 280);
    const domain = { fromMs: T0 + 2_500_000, toMs: T0 + 3_500_000 }; // ~17 minutes
    const detail = columnsViewportDetail([identity()], columns, domain, 240, () => 30_000, T0 + 86_400_000);
    // 1 000 s viewport + 50 % margin on both sides at 10 s cadence = 201 samples, one invalid.
    expect(detail.samples).toHaveLength(200);
    expect(Math.max(...detail.samples.map((sample) => sample.value!))).toBe(25);
    expect(detail.samples.filter(isLiveHistorySegmentStart)).toHaveLength(1);
  });

  it("reduces a wide viewport to the budget without losing the extreme", () => {
    const { columns } = columnsFor(8_640, 10_000, 4_000);
    const detail = columnsViewportDetail(
      [identity()],
      columns,
      { fromMs: T0 + 20_000_000, toMs: T0 + 60_000_000 },
      240,
      () => 30_000,
    );
    expect(detail.samples.length).toBeLessThanOrEqual(260);
    expect(Math.max(...detail.samples.map((sample) => sample.value!))).toBe(25);
  });

  it("replaces coarse points inside the detail range but keeps newer live points", () => {
    const coarse = [0, 1_000_000, 2_000_000, 3_000_000].map((offset, index) => ({
      ...identity(),
      event_id: `coarse-${index}`,
      captured_at: new Date(T0 + offset).toISOString(),
    }));
    const detail = {
      fromMs: T0 + 500_000,
      toMs: T0 + 2_600_000,
      coveredToMs: T0 + 2_500_000,
      channels: new Set([liveChannelKey(identity())]),
      samples: [{ ...identity(), event_id: "detail-1", captured_at: new Date(T0 + 1_500_000).toISOString() }],
    };
    const merged = mergeViewportDetail(coarse, detail).map((sample) => sample.event_id);
    expect(merged).toEqual(["coarse-0", "detail-1", "coarse-3"]);
    expect(mergeViewportDetail(coarse, null)).toBe(coarse);
  });
});

describe("aggregated load and raw fallback (#1813)", () => {
  it("requests at most four series per request under one snapshot", async () => {
    const queries: HistoryAggregateQuery[] = [];
    const adapter = {
      historyAggregate: vi.fn(async (query: HistoryAggregateQuery) => {
        queries.push(query);
        return {
          fromMs: query.from.getTime(),
          toMs: query.to.getTime(),
          bucketMs: 360_000,
          snapshotAt: "2026-11-26T12:00:00.000Z",
          series: query.series.map((key) => ({
            ...key,
            unit: "degC",
            mode: "raw" as const,
            count: 1,
            validCount: 1,
            raw: [
              [T0 + 1_000, 4, "valid", null, `raw-${key.channel_id}`] as [
                number,
                number,
                string,
                null,
                string,
              ],
            ],
            buckets: [],
            statistics: null,
          })),
        };
      }),
    } as unknown as TelemetryAdapter;
    const identities = Array.from({ length: 24 }, (_, index) => identity(`ch-${index}`));
    const result = await loadAggregatedLiveHistory(
      adapter,
      identities,
      { from: new Date(T0), to: new Date(T0 + 86_400_000) },
      undefined,
      160,
    );
    expect(queries).toHaveLength(6);
    expect(queries.every((query) => query.series.length <= 4)).toBe(true);
    expect(queries.slice(1).every((query) => query.snapshot_at === "2026-11-26T12:00:00.000Z")).toBe(true);
    expect(queries[0].buckets).toBe(40);
    expect(result.samples).toHaveLength(24);
    expect(result.aggregatedChannels.size).toBe(0);
    expect(Object.keys(result.intervalColumns)).toHaveLength(24);
  });

  it("probes an older backend once, then falls back without further aggregate requests", async () => {
    const fetchMock = vi
      .fn<TelemetryFetch>()
      .mockImplementation(async () => new Response("Not Found", { status: 404 }));
    const client = new TelemetryRestClient("http://127.0.0.1:9", {
      fetch: fetchMock,
      historyLimiter: new RequestLimiter(3),
    });
    const query = {
      from: new Date(T0),
      to: new Date(T0 + 60_000),
      series: [{ node_id: "edge-01", equipment_id: "XJP60D-1", channel_id: "ch-1", metric: "temperature" }],
      buckets: 60,
    };
    const first = await client.historyAggregate(query).catch((error: unknown) => error);
    const second = await client.historyAggregate(query).catch((error: unknown) => error);
    expect(isAggregateUnsupported(first)).toBe(true);
    expect(isAggregateUnsupported(second)).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(isAggregateUnsupported(new TelemetryClientError("http", "busy", { status: 503 }))).toBe(false);
  });
});

describe("continuity at aggregate and detail boundaries (#1813 review)", () => {
  it("breaks across one skipped bucket when the points are further apart than the tolerance", () => {
    const buckets = [
      bucket(0, {
        first: [T0 + 10_000, 4],
        min: [T0 + 10_000, 4],
        max: [T0 + 590_000, 4.2],
        last: [T0 + 590_000, 4.2],
      }),
      bucket(2, {
        first: [T0 + 1_200_000, 4.1],
        min: [T0 + 1_200_000, 4.1],
        max: [T0 + 1_210_000, 4.3],
        last: [T0 + 1_210_000, 4.3],
      }),
    ];
    expect(
      liveHistorySegments(aggregateSeriesToSamples(identity(), series(buckets), 600_000, 30_000)),
    ).toHaveLength(2);
  });

  it("keeps a break that lies just before the detail window (raw columns)", () => {
    const columns: LiveIntervalColumns = {};
    recordLiveIntervalSamples(columns, [
      { ...identity(), event_id: "a", captured_at: new Date(T0).toISOString(), value: 4 },
      {
        ...identity(),
        event_id: "bad",
        captured_at: new Date(T0 + 100_000).toISOString(),
        value: null,
        quality: "communication_error",
      },
      { ...identity(), event_id: "b", captured_at: new Date(T0 + 250_000).toISOString(), value: 5 },
      { ...identity(), event_id: "c", captured_at: new Date(T0 + 260_000).toISOString(), value: 5.1 },
    ]);
    // Detail (with its 50 % margin) starts at 150 s: after the invalid sample, before b.
    const detail = columnsViewportDetail(
      [identity()],
      columns,
      { fromMs: T0 + 200_000, toMs: T0 + 300_000 },
      240,
      () => 30_000,
    );
    expect(isLiveHistorySegmentStart(detail.samples[0])).toBe(true);
    const coarse = [
      { ...identity(), event_id: "a", captured_at: new Date(T0).toISOString(), value: 4 },
      ...detail.samples,
    ];
    expect(liveHistorySegments(mergeViewportDetail(coarse, detail))).toHaveLength(2);
  });

  it("keeps a coarse break when an aggregated detail does not show where it lies", () => {
    const before = { ...identity(), event_id: "before", captured_at: new Date(T0).toISOString(), value: 4 };
    const brokenCoarse = {
      ...identity(),
      event_id: "nexolab-live-segment:after-outage",
      captured_at: new Date(T0 + 600_000).toISOString(),
      value: 5,
    };
    const detail = {
      fromMs: T0 + 300_000,
      toMs: T0 + 900_000,
      coveredToMs: T0 + 900_000,
      channels: new Set([liveChannelKey(identity())]),
      samples: [
        { ...identity(), event_id: "d1", captured_at: new Date(T0 + 590_000).toISOString(), value: 5 },
        { ...identity(), event_id: "d2", captured_at: new Date(T0 + 620_000).toISOString(), value: 5.1 },
      ],
    };
    expect(liveHistorySegments(mergeViewportDetail([before, brokenCoarse], detail))).toHaveLength(2);
  });
});
