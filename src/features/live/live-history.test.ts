import { describe, expect, it, vi } from "vitest";

import type {
  TelemetryAdapter,
  TelemetryCollectionResponse,
  TelemetryHistoryQuery,
  TelemetrySample,
} from "@/lib/telemetry/types";

import {
  downsampleLiveHistory,
  isLiveHistorySegmentStart,
  liveHistorySegments,
  loadCompleteLiveHistory,
} from "./live-history";

function sample(overrides: Partial<TelemetrySample> = {}): TelemetrySample {
  return {
    event_id: "event-1",
    node_id: "edge-01",
    captured_at: "2026-08-04T00:00:00.000Z",
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
  snapshotAt = "2026-08-04T00:10:00.000Z",
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
  from: new Date("2026-08-03T23:00:00.000Z"),
  to: new Date("2026-08-04T00:10:00.000Z"),
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

    expect(result.snapshotAt).toBe("2026-08-04T00:10:00.000Z");
    expect(queries).toHaveLength(2);
    expect(queries[0].snapshot_at).toBeUndefined();
    expect(queries[1].snapshot_at).toBe(result.snapshotAt);
    expect(result.samples).toHaveLength(2);
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
      .mockResolvedValueOnce(response([power], "2026-08-04T00:11:00.000Z"));

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
        captured_at: new Date(window.from.getTime() + index * 60_000).toISOString(),
        value: index,
      }),
    );

    const result = downsampleLiveHistory(samples, window, 5);

    expect(result).toHaveLength(5);
    expect(result[0].event_id).toBe("event-0");
    expect(result.at(-1)?.event_id).toBe("event-19");
  });

  it("preserves a communication failure as a separate recovery segment", () => {
    const samples = [
      sample({ event_id: "before", captured_at: "2026-08-04T00:00:00.000Z", value: 4.1 }),
      sample({
        event_id: "failure",
        captured_at: "2026-08-04T00:00:05.000Z",
        quality: "communication_error",
        value: null,
      }),
      sample({ event_id: "recovery", captured_at: "2026-08-04T00:00:10.000Z", value: 4.3 }),
    ];

    const result = downsampleLiveHistory(samples, window, 10);

    expect(result).toHaveLength(2);
    expect(isLiveHistorySegmentStart(result[1])).toBe(true);
    expect(liveHistorySegments(result)).toHaveLength(2);
  });
});
