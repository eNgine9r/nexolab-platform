import { describe, expect, it, vi } from "vitest";

import {
  CADENCE_OBSERVATION_LIMIT,
  EMPTY_CADENCE_OBSERVATIONS,
  isLiveSampleFresh,
  liveFreshnessFor,
  observedCadenceMs,
  seedCadenceFromSamples,
} from "./freshness";
import { liveChannelKey } from "./live-telemetry";

import type {
  TelemetryAdapter,
  TelemetryCollectionResponse,
  TelemetryHistoryQuery,
  TelemetrySample,
} from "@/lib/telemetry/types";

import {
  advanceLiveHistoryWindow,
  downsampleLiveHistory,
  isLiveHistorySegmentStart,
  liveHistorySegments,
  loadCompleteLiveHistory,
  seedCadenceFromHistoryLoad,
  mergeLiveHistoryTail,
  reconcileLiveHistoryEvents,
  seedLiveHistoryOrderingState,
} from "./live-history";

function sample(overrides: Partial<TelemetrySample> = {}): TelemetrySample {
  return {
    event_id: "event-1",
    node_id: "edge-01",
    captured_at: "2026-08-03T21:00:00.000Z",
    metric: "temperature",
    value: 4.2,
    unit: "degC",
    quality: "valid",
    source: "xjp60d",
    equipment_id: "DIXELL-106",
    channel_id: "106-03",
    alarm: null,
    raw_value: 42,
    raw_status: null,
    ...overrides,
  };
}

function response(
  items: TelemetrySample[],
  snapshotAt = "2026-08-03T21:10:00.000Z",
  nextOffset: number | null = null,
): TelemetryCollectionResponse {
  return {
    items,
    count: items.length,
    limit: 1_000,
    offset: 0,
    next_offset: nextOffset,
    snapshot_at: snapshotAt,
  };
}

function adapter(history: TelemetryAdapter["history"]): TelemetryAdapter {
  return {
    readiness: vi.fn(),
    latest: vi.fn(),
    history,
    subscribe: vi.fn(),
  };
}

const window = {
  from: new Date("2026-08-03T20:00:00.000Z"),
  to: new Date("2026-08-03T21:10:00.000Z"),
};

describe("live history loading", () => {
  it("reuses one ingestion watermark across every selected channel", async () => {
    const temperature = sample();
    const power = sample({
      event_id: "power",
      equipment_id: "LE01MP-200",
      channel_id: "200-active-power",
      metric: "electrical.power.active",
      unit: "W",
      value: 720,
    });
    const queries: TelemetryHistoryQuery[] = [];
    const history = vi.fn(async (query: TelemetryHistoryQuery) => {
      queries.push(query);
      return query.metric === "temperature" ? response([temperature]) : response([power]);
    });

    const result = await loadCompleteLiveHistory(adapter(history), [temperature, power], window);

    expect(result.snapshotAt).toBe("2026-08-03T21:10:00.000Z");
    expect(queries).toHaveLength(2);
    expect(queries[0].snapshot_at).toBeUndefined();
    expect(queries[1].snapshot_at).toBe(result.snapshotAt);
    expect(result.samples).toHaveLength(2);
  });

  it("#1522: exposes raw newest samples so downsampled history cannot inflate the observed cadence", async () => {
    const dayWindow = {
      from: new Date("2026-08-02T21:10:00.000Z"),
      to: new Date("2026-08-03T21:10:00.000Z"),
    };
    const start = dayWindow.from.getTime();
    // 24 h of a 60 s channel = 1440 raw samples, far above the 240-point chart budget.
    const raw = Array.from({ length: 1_440 }, (_, index) =>
      sample({
        event_id: `raw-${index}`,
        captured_at: new Date(start + index * 60_000).toISOString(),
        // Realistic varying signal: the chart reducer keeps only shape-relevant points.
        value: 4 + Math.sin(index / 7) * 3 + (index % 5) * 0.4,
      }),
    );
    const history = vi.fn(async () => response(raw));

    const result = await loadCompleteLiveHistory(adapter(history), [raw[0]], dayWindow);
    const key = liveChannelKey(raw[0]);

    // The chart series is reduced, so its spacing is NOT the acquisition cadence.
    expect(result.samples.length).toBeLessThan(raw.length);
    const reducedCadence = observedCadenceMs(
      seedCadenceFromSamples(EMPTY_CADENCE_OBSERVATIONS, result.samples, liveChannelKey)[key],
    );
    expect(reducedCadence).toBeGreaterThan(60_000);

    // The dedicated raw tail is exact and bounded.
    expect(result.cadenceSamples).toHaveLength(CADENCE_OBSERVATION_LIMIT);
    expect(result.cadenceSamples.at(-1)?.event_id).toBe("raw-1439");
    const seeded = seedCadenceFromSamples(EMPTY_CADENCE_OBSERVATIONS, result.cadenceSamples, liveChannelKey);
    expect(observedCadenceMs(seeded[key])).toBe(60_000);
    expect(liveFreshnessFor(raw[1_439], key, seeded).staleAfterMs).toBe(105_000);
  });

  it("#1522: seeds Live cadence only from the raw tail of a history load", () => {
    const at = (seconds: number, id: string) =>
      sample({ event_id: id, captured_at: new Date(window.from.getTime() + seconds * 1_000).toISOString() });
    const reducedChart = [0, 300, 600, 900].map((s) => at(s, `chart-${s}`));
    const rawTail = [720, 780, 840, 900].map((s) => at(s, `raw-${s}`));
    const key = liveChannelKey(rawTail[0]);

    const seeded = seedCadenceFromHistoryLoad(EMPTY_CADENCE_OBSERVATIONS, {
      cadenceSamples: rawTail,
      // A full result also carries the reduced chart series; it must be ignored.
      ...({ samples: reducedChart } as object),
    });

    expect(observedCadenceMs(seeded[key])).toBe(60_000);
    // A dead 60 s channel turns stale after 105 s, not after ~7.75 min.
    const latest = rawTail.at(-1)!;
    const freshness = liveFreshnessFor(latest, key, seeded);
    expect(isLiveSampleFresh(latest, Date.parse(latest.captured_at) + 106_000, freshness)).toBe(false);
  });

  it("#1522: keeps the raw cadence tail per channel and ignores rejected samples", async () => {
    const temperature = Array.from({ length: 10 }, (_, index) =>
      sample({
        event_id: `t-${index}`,
        captured_at: new Date(window.from.getTime() + index * 10_000).toISOString(),
      }),
    );
    const power = Array.from({ length: 3 }, (_, index) =>
      sample({
        event_id: `p-${index}`,
        equipment_id: "LE01MP-200",
        channel_id: "200-active-power",
        metric: "electrical.power.active",
        unit: "W",
        captured_at: new Date(window.from.getTime() + index * 120_000).toISOString(),
      }),
    );
    const future = sample({ event_id: "future", captured_at: "2099-01-01T00:00:00.000Z" });
    const history = vi.fn(async (query: TelemetryHistoryQuery) =>
      query.metric === "temperature" ? response([...temperature, future]) : response(power),
    );

    const result = await loadCompleteLiveHistory(adapter(history), [temperature[0], power[0]], window);
    const byKey = seedCadenceFromSamples(EMPTY_CADENCE_OBSERVATIONS, result.cadenceSamples, liveChannelKey);

    expect(result.cadenceSamples.some((item) => item.event_id === "future")).toBe(false);
    expect(observedCadenceMs(byKey[liveChannelKey(temperature[0])])).toBe(10_000);
    expect(observedCadenceMs(byKey[liveChannelKey(power[0])])).toBe(120_000);
  });

  it("fails closed when a later channel changes the snapshot watermark", async () => {
    const temperature = sample();
    const power = sample({
      event_id: "power",
      equipment_id: "LE01MP-200",
      channel_id: "200-active-power",
      metric: "electrical.power.active",
      unit: "W",
    });
    const history = vi
      .fn<TelemetryAdapter["history"]>()
      .mockResolvedValueOnce(response([temperature]))
      .mockResolvedValueOnce(response([power], "2026-08-03T21:11:00.000Z"));

    await expect(loadCompleteLiveHistory(adapter(history), [temperature, power], window)).rejects.toThrow(
      "snapshot changed",
    );
  });

  it("fails closed when the backend omits the watermark", async () => {
    const history = vi.fn(async () => ({ ...response([sample()]), snapshot_at: null }));

    await expect(loadCompleteLiveHistory(adapter(history), [sample()], window)).rejects.toThrow(
      "did not provide",
    );
  });
});

describe("live history downsampling", () => {
  it("keeps first and last samples after bounded downsampling", () => {
    const samples = Array.from({ length: 20 }, (_, index) =>
      sample({
        event_id: `event-${index}`,
        captured_at: new Date(window.from.getTime() + index * 5_000).toISOString(),
        value: index,
      }),
    );

    const result = downsampleLiveHistory(samples, window, 5);

    expect(result.length).toBeGreaterThanOrEqual(2);
    expect(result.length).toBeLessThanOrEqual(5);
    expect(result[0].event_id).toBe("event-0");
    expect(result.at(-1)?.event_id).toBe("event-19");
  });

  it("preserves both short local extrema instead of a last-point-only bucket", () => {
    const samples = Array.from({ length: 40 }, (_, index) =>
      sample({
        event_id: `event-${index}`,
        captured_at: new Date(window.from.getTime() + index * 5_000).toISOString(),
        value: index === 18 ? -12 : index === 19 ? 31 : 4 + index / 100,
      }),
    );

    const result = downsampleLiveHistory(samples, window, 10);
    const values = result.map((item) => item.value);

    expect(values).toContain(-12);
    expect(values).toContain(31);
    expect(result.length).toBeLessThanOrEqual(10);
  });

  it("preserves alarm entry and recovery context under reduction", () => {
    const samples = Array.from({ length: 40 }, (_, index) =>
      sample({
        event_id: `event-${index}`,
        captured_at: new Date(window.from.getTime() + index * 5_000).toISOString(),
        value: index,
        alarm: index >= 18 && index <= 20 ? "high" : null,
      }),
    );

    const result = downsampleLiveHistory(samples, window, 10);
    const eventIds = result.map((item) => item.event_id.replace("nexolab-live-segment:", ""));

    expect(eventIds).toContain("event-17");
    expect(eventIds).toContain("event-18");
    expect(eventIds).toContain("event-20");
    expect(eventIds).toContain("event-21");
  });

  it("preserves a communication failure as a separate recovery segment", () => {
    const samples = [
      sample({ event_id: "before", captured_at: "2026-08-03T21:00:00.000Z", value: 4.1 }),
      sample({
        event_id: "failure",
        captured_at: "2026-08-03T21:00:05.000Z",
        quality: "communication_error",
        value: null,
      }),
      sample({ event_id: "recovery", captured_at: "2026-08-03T21:00:10.000Z", value: 4.3 }),
    ];

    const result = downsampleLiveHistory(samples, window, 10);

    expect(result).toHaveLength(2);
    expect(isLiveHistorySegmentStart(result[1])).toBe(true);
    expect(liveHistorySegments(result)).toHaveLength(2);
  });

  it("does not let delayed replay close a newer pending outage", () => {
    const latest = sample({ event_id: "latest", captured_at: "2026-08-03T21:00:20.000Z" });
    const failure = sample({
      event_id: "failure",
      captured_at: "2026-08-03T21:00:25.000Z",
      quality: "communication_error",
      value: null,
    });
    const delayed = sample({ event_id: "delayed", captured_at: "2026-08-03T21:00:10.000Z" });
    const recovery = sample({ event_id: "recovery", captured_at: "2026-08-03T21:00:30.000Z" });
    const afterFailure = reconcileLiveHistoryEvents([failure], seedLiveHistoryOrderingState([latest]));
    const afterDelayed = reconcileLiveHistoryEvents([delayed], afterFailure.state);
    const afterRecovery = reconcileLiveHistoryEvents([recovery], afterDelayed.state);

    expect(afterDelayed.samples).toEqual([]);
    expect(afterRecovery.samples).toHaveLength(1);
    expect(isLiveHistorySegmentStart(afterRecovery.samples[0])).toBe(true);
  });

  it("advances the live window to a newer selected sample and preserves its duration", () => {
    const incoming = sample({
      event_id: "new-tail",
      captured_at: "2026-08-03T21:10:02.000Z",
      value: 9.876,
    });
    const nextWindow = advanceLiveHistoryWindow(window, [incoming]);

    expect(nextWindow.to.toISOString()).toBe("2026-08-03T21:10:02.000Z");
    expect(nextWindow.to.getTime() - nextWindow.from.getTime()).toBe(
      window.to.getTime() - window.from.getTime(),
    );
    const merged = mergeLiveHistoryTail(
      [sample({ event_id: "old-tail", captured_at: "2026-08-03T21:10:00.000Z", value: 2.8 })],
      [incoming],
      new Set([liveChannelKey(incoming)]),
      nextWindow,
    );
    expect(merged.at(-1)?.event_id).toBe("new-tail");
    expect(merged.at(-1)?.value).toBe(9.876);
  });

  it("does not move the live window backwards for delayed replay", () => {
    const delayed = sample({ event_id: "delayed", captured_at: "2026-08-03T21:09:00.000Z" });
    expect(advanceLiveHistoryWindow(window, [delayed])).toBe(window);
  });
});
