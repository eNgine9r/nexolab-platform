import { describe, expect, it, vi } from "vitest";

import type {
  HistoryAggregateQuery,
  HistoryAggregateResponse,
  HistoryIntervalStatisticsWire,
} from "@/lib/telemetry/history-aggregate";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

import {
  aggregateEligible,
  DashboardServerStatistics,
  resolveDashboardIdentities,
} from "./aggregate-history";
import type { LiveDashboardItem } from "./types";

const T0 = Date.parse("2026-11-26T00:00:00Z");

function item(overrides: Partial<LiveDashboardItem> = {}): LiveDashboardItem {
  return {
    id: "item-1",
    position: 1,
    channel_ref_id: "ref-1",
    channel_id: "106-01",
    metric: "temperature.probe",
    native_unit: "degC",
    visualization: "line",
    color: null,
    display_unit: "degC",
    ...overrides,
  } as LiveDashboardItem;
}

function sample(channelId: string): TelemetrySample {
  return {
    event_id: `latest-${channelId}`,
    node_id: "edge-01",
    captured_at: new Date(T0).toISOString(),
    metric: "temperature.probe",
    value: 4,
    unit: "degC",
    quality: "valid",
    source: "xjp60d",
    equipment_id: "XJP60D-1",
    channel_id: channelId,
    alarm: null,
    raw_value: 40,
    raw_status: null,
  };
}

function statistics(maximum: number): HistoryIntervalStatisticsWire {
  return {
    valid_count: 10,
    invalid_count: 0,
    minimum: 1,
    maximum,
    valid_sum: 50,
    first_valid_ms: T0,
    last_valid_ms: T0 + 90_000,
    median_spacing_ms: 10_000,
    gap_count: 0,
    gap_total_ms: 0,
    gap_longest_ms: 0,
    recent_valid_ms: [T0 + 80_000, T0 + 90_000],
  };
}

function aggregateAdapter(maximumFor: (query: HistoryAggregateQuery) => number) {
  const queries: HistoryAggregateQuery[] = [];
  const historyAggregate = vi.fn(async (query: HistoryAggregateQuery): Promise<HistoryAggregateResponse> => {
    queries.push(query);
    return {
      fromMs: query.from.getTime(),
      toMs: query.to.getTime(),
      bucketMs: query.to.getTime() - query.from.getTime(),
      snapshotAt: "2026-11-26T12:00:00.000Z",
      series: query.series.map((key) => ({
        ...key,
        unit: "degC",
        mode: "aggregate" as const,
        count: 10,
        validCount: 10,
        raw: [],
        buckets: [],
        statistics: statistics(maximumFor(query)),
      })),
    };
  });
  const adapter = {
    historyAggregate,
    history: vi.fn(),
    latest: vi.fn(),
    readiness: vi.fn(),
    subscribe: vi.fn(),
  };
  return { adapter: adapter as unknown as TelemetryAdapter, queries };
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

describe("Saved Dashboard aggregated history (P0 charts)", () => {
  it("keeps operator-derived Embraco temperatures and digital state lanes on the raw path", () => {
    expect(aggregateEligible(item())).toBe(true);
    expect(
      aggregateEligible(
        item({
          channel_ref_id: null,
          node_id: "edge-01",
          equipment_id: "EMBRACO-2",
          channel_id: "2-cabinet-temperature",
          metric: "temperature.cabinet",
        }),
      ),
    ).toBe(false);
  });

  it("resolves the real series identity of each item from its newest sample", async () => {
    const latest = vi.fn(async (query: { channel_id?: string }) => ({
      items: query.channel_id === "106-02" ? [] : [sample(String(query.channel_id))],
      count: 1,
      limit: 1,
      offset: 0,
      next_offset: null,
    }));
    const adapter = { latest } as unknown as TelemetryAdapter;
    const identities = await resolveDashboardIdentities(
      adapter,
      [item(), item({ id: "item-2", channel_ref_id: "ref-2", channel_id: "106-02" })],
      new AbortController().signal,
    );
    expect([...identities.values()].map((identity) => identity.equipment_id)).toEqual(["XJP60D-1"]);
  });

  it("answers the loaded window exactly, batches a viewport request and reuses a sliding window", async () => {
    const { adapter, queries } = aggregateAdapter(
      (query) => (query.to.getTime() - query.from.getTime()) / 1_000,
    );
    let changes = 0;
    let now = T0 + 3_600_000;
    const stats = new DashboardServerStatistics(
      () => (changes += 1),
      () => now,
    );
    const identity = sample("106-01");
    const window = { fromMs: T0, toMs: T0 + 3_600_000 };
    stats.reset(
      adapter,
      new Map([["item-1", identity]]),
      new Map([["item-1", { fromMs: T0 } as never]]),
      window,
    );

    expect(stats.get("item-1", window.fromMs, window.toMs)).toMatchObject({ fromMs: T0 });
    // A rolling window 5 s later reuses the loaded statistics without a request.
    expect(stats.get("item-1", window.fromMs + 5_000, window.toMs + 5_000)).toMatchObject({ fromMs: T0 });
    expect(queries).toHaveLength(0);

    // A zoomed viewport: no number until the server answers, one batched request.
    expect(stats.get("item-1", T0 + 600_000, T0 + 1_200_000)).toBeNull();
    expect(stats.get("item-1", T0 + 600_000, T0 + 1_200_000)).toBeNull();
    await wait(500);
    expect(queries).toHaveLength(1);
    expect(queries[0].statistics).toBe(true);
    expect(queries[0].buckets).toBe(1);
    expect(changes).toBe(1);
    expect(stats.get("item-1", T0 + 600_000, T0 + 1_200_000)?.max).toBe(600);

    // After 15 s the sliding window is refreshed once while the older numbers are still shown.
    now += 16_000;
    expect(stats.get("item-1", window.fromMs + 16_000, window.toMs + 16_000)).not.toBeNull();
    await wait(500);
    expect(queries).toHaveLength(2);
    stats.dispose();
  });

  it("shows no statistics after a failure and retries the range only after 10 s", async () => {
    let fail = true;
    const historyAggregate = vi.fn(async () => {
      if (fail) throw new Error("offline");
      return aggregateAdapter(() => 7).adapter.historyAggregate!({
        from: new Date(T0),
        to: new Date(T0 + 60_000),
        series: [],
        buckets: 1,
      });
    });
    let now = T0;
    const stats = new DashboardServerStatistics(
      () => undefined,
      () => now,
    );
    stats.reset({ historyAggregate } as unknown as TelemetryAdapter, new Map([["item-1", sample("106-01")]]));
    expect(stats.get("item-1", T0, T0 + 60_000)).toBeNull();
    await wait(500);
    expect(historyAggregate).toHaveBeenCalledTimes(1);
    expect(stats.get("item-1", T0, T0 + 60_000)).toBeNull();
    await wait(500);
    expect(historyAggregate).toHaveBeenCalledTimes(1);
    fail = false;
    now += 11_000;
    expect(stats.get("item-1", T0, T0 + 60_000)).toBeNull();
    await wait(500);
    expect(historyAggregate).toHaveBeenCalledTimes(2);
    stats.dispose();
  });

  it("gives every row one range and never cancels a slow compatible request in flight", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const { adapter, queries } = aggregateAdapter(() => 9);
    const slow = {
      historyAggregate: vi.fn(async (query: HistoryAggregateQuery) => {
        await gate;
        return adapter.historyAggregate!(query);
      }),
    } as unknown as TelemetryAdapter;
    let now = T0 + 3_600_000;
    const stats = new DashboardServerStatistics(
      () => undefined,
      () => now,
    );
    const window = { fromMs: T0, toMs: T0 + 3_600_000 };
    stats.reset(
      slow,
      new Map([["item-1", sample("106-01")]]),
      new Map([["item-1", { fromMs: T0 } as never]]),
      window,
    );

    // 20 s later the window has moved; every row still uses the loaded range while a refresh loads.
    now += 20_000;
    expect(stats.effectiveRange(T0 + 20_000, T0 + 3_620_000)).toEqual([T0, T0 + 3_600_000]);
    await wait(500);
    expect(slow.historyAggregate).toHaveBeenCalledTimes(1);
    // The window keeps moving while the request is slow: no second request, no cancellation.
    for (const shift of [25_000, 30_000]) {
      now = T0 + 3_600_000 + shift;
      stats.effectiveRange(T0 + shift, T0 + 3_600_000 + shift);
      await wait(450);
    }
    expect(slow.historyAggregate).toHaveBeenCalledTimes(1);
    release();
    await wait(50);
    expect(queries).toHaveLength(1);
    expect(stats.effectiveRange(T0 + 20_000, T0 + 3_620_000)).toEqual([T0 + 20_000, T0 + 3_620_000]);
    expect(stats.exactFor("item-1", T0 + 20_000, T0 + 3_620_000)?.max).toBe(9);
    stats.dispose();
  });

  it("uses the requested range unchanged when no series is aggregated", () => {
    const stats = new DashboardServerStatistics(() => undefined);
    expect(stats.effectiveRange(T0, T0 + 1_000)).toEqual([T0, T0 + 1_000]);
  });

  it("requests the zoomed viewport and the full window independently, neither cancelling the other", async () => {
    const signals: AbortSignal[] = [];
    const { adapter } = aggregateAdapter((query) => (query.to.getTime() - query.from.getTime()) / 60_000);
    const slow = {
      historyAggregate: vi.fn(async (query: HistoryAggregateQuery, signal?: AbortSignal) => {
        if (signal) signals.push(signal);
        await wait(300);
        return adapter.historyAggregate!(query);
      }),
    } as unknown as TelemetryAdapter;
    const stats = new DashboardServerStatistics(
      () => undefined,
      () => T0 + 3_600_000,
    );
    stats.reset(slow, new Map([["item-1", sample("106-01")]]));
    // The table (viewport) and the density counter (full window) ask alternately while loading.
    for (let round = 0; round < 3; round += 1) {
      stats.effectiveRange(T0 + 600_000, T0 + 1_200_000);
      stats.effectiveRange(T0, T0 + 3_600_000);
      await wait(150);
    }
    await wait(1_000);
    expect(signals.every((signal) => !signal.aborted)).toBe(true);
    expect(stats.exactFor("item-1", T0 + 600_000, T0 + 1_200_000)?.max).toBe(10);
    expect(stats.exactFor("item-1", T0, T0 + 3_600_000)?.max).toBe(60);
    stats.dispose();
  });
});
