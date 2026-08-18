import { describe, expect, it, vi } from "vitest";

import type {
  TelemetryAdapter,
  TelemetryCollectionResponse,
  TelemetryHistoryQuery,
  TelemetrySample,
} from "./types";
import {
  loadCompleteTelemetryHistory,
  reconcileTelemetryHistoryEvents,
  seedTelemetryHistoryOrderingState,
} from "./history";

function sample(overrides: Partial<TelemetrySample> = {}): TelemetrySample {
  return {
    event_id: "event-1",
    node_id: "edge-01",
    captured_at: "2026-08-18T19:00:00.000Z",
    metric: "temperature.probe",
    value: 4.2,
    unit: "degC",
    quality: "valid",
    source: "xjp60d",
    equipment_id: "K108",
    channel_id: "108-01",
    alarm: null,
    raw_value: 42,
    raw_status: null,
    ...overrides,
  };
}

function response(
  items: TelemetrySample[],
  nextOffset: number | null,
  snapshotAt = "2026-08-18T19:10:00.000Z",
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
  return { readiness: vi.fn(), latest: vi.fn(), history, subscribe: vi.fn() };
}

const window = {
  from: new Date("2026-08-18T18:00:00.000Z"),
  to: new Date("2026-08-18T19:10:00.000Z"),
};

describe("complete telemetry history loading", () => {
  it("paginates against one stable ingestion snapshot without using offset", async () => {
    const newer = sample({ event_id: "newer", captured_at: "2026-08-18T19:00:00.000Z" });
    const older = sample({ event_id: "older", captured_at: "2026-08-18T18:30:00.000Z" });
    const queries: TelemetryHistoryQuery[] = [];
    const history = vi.fn(async (query: TelemetryHistoryQuery) => {
      queries.push(query);
      return queries.length === 1 ? response([newer], 1) : response([older], null);
    });

    const result = await loadCompleteTelemetryHistory(
      adapter(history),
      { metric: "temperature.probe" },
      window,
    );

    expect(result.samples.map((item) => item.event_id)).toEqual(["older", "newer"]);
    expect(result.snapshotAt).toBe("2026-08-18T19:10:00.000Z");
    expect(queries).toHaveLength(2);
    expect(queries[0].snapshot_at).toBeUndefined();
    expect(queries[0].offset).toBe(0);
    expect(queries[1].snapshot_at).toBe(result.snapshotAt);
    expect(queries[1].offset).toBe(0);
    expect(new Date(queries[1].to).getTime()).toBeLessThan(new Date(queries[0].to).getTime());
  });

  it("deduplicates overlap between captured-time cursor pages", async () => {
    const boundary = sample({ event_id: "boundary", captured_at: "2026-08-18T18:30:00.000Z" });
    const older = sample({ event_id: "older", captured_at: "2026-08-18T18:00:01.000Z" });
    const history = vi
      .fn<TelemetryAdapter["history"]>()
      .mockResolvedValueOnce(response([boundary], 1))
      .mockResolvedValueOnce(response([boundary, older], null));

    const result = await loadCompleteTelemetryHistory(adapter(history), {}, window);

    expect(result.samples.map((item) => item.event_id)).toEqual(["older", "boundary"]);
  });

  it("fails closed when the ingestion snapshot changes between pages", async () => {
    const history = vi
      .fn<TelemetryAdapter["history"]>()
      .mockResolvedValueOnce(response([sample()], 1))
      .mockResolvedValueOnce(
        response(
          [sample({ event_id: "older", captured_at: "2026-08-18T18:30:00.000Z" })],
          null,
          "2026-08-18T19:11:00.000Z",
        ),
      );

    await expect(loadCompleteTelemetryHistory(adapter(history), {}, window)).rejects.toThrow(
      "snapshot changed",
    );
  });
});

describe("telemetry history live reconciliation", () => {
  it("rejects duplicate and out-of-order events while accepting a newer tail", () => {
    const persisted = sample({ event_id: "persisted", captured_at: "2026-08-18T19:00:00.000Z" });
    const duplicate = { ...persisted };
    const delayed = sample({ event_id: "delayed", captured_at: "2026-08-18T18:59:00.000Z" });
    const newer = sample({ event_id: "newer", captured_at: "2026-08-18T19:00:10.000Z" });

    const reconciled = reconcileTelemetryHistoryEvents(
      [newer, delayed, duplicate],
      seedTelemetryHistoryOrderingState([persisted]),
      { now: Date.parse("2026-08-18T19:00:20.000Z") },
    );

    expect(reconciled.samples).toEqual([newer]);
    const replay = reconcileTelemetryHistoryEvents([newer], reconciled.state, {
      now: Date.parse("2026-08-18T19:00:20.000Z"),
    });
    expect(replay.samples).toEqual([]);
  });

  it("preserves non-valid newer samples so chart continuity can show real gaps", () => {
    const persisted = sample({ event_id: "persisted" });
    const failure = sample({
      event_id: "failure",
      captured_at: "2026-08-18T19:00:10.000Z",
      quality: "communication_error",
      value: null,
    });

    const reconciled = reconcileTelemetryHistoryEvents(
      [failure],
      seedTelemetryHistoryOrderingState([persisted]),
      { now: Date.parse("2026-08-18T19:00:20.000Z") },
    );

    expect(reconciled.samples).toEqual([failure]);
  });
});
