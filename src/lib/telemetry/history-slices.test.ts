import { describe, expect, it, vi } from "vitest";

import { TelemetryClientError } from "./errors";
import {
  TelemetryHistoryVolumeError,
  loadCompleteTelemetryHistoryForSeries,
  loadTelemetryHistorySlices,
  telemetryHistorySlices,
} from "./history";
import type {
  TelemetryAdapter,
  TelemetryCollectionResponse,
  TelemetryHistoryQuery,
  TelemetrySample,
} from "./types";

const SNAPSHOT = "2026-11-26T12:00:00.000Z";
const HOUR = 3_600_000;
const T0 = Date.parse("2026-11-20T00:00:00Z");

function sample(timestampMs: number): TelemetrySample {
  return {
    event_id: `e-${timestampMs}`,
    node_id: "edge-01",
    captured_at: new Date(timestampMs).toISOString(),
    metric: "temperature.probe",
    value: 4,
    unit: "degC",
    quality: "valid",
    source: "test",
    equipment_id: "K106",
    channel_id: "106-01",
    alarm: null,
    raw_value: 40,
    raw_status: null,
  };
}

/** A fake history API over a 10 min cadence: from inclusive, to exclusive, newest first, paged. */
function api(stepMs = 600_000) {
  const queries: TelemetryHistoryQuery[] = [];
  const history = vi.fn(async (query: TelemetryHistoryQuery): Promise<TelemetryCollectionResponse> => {
    queries.push(query);
    const from = new Date(query.from!).getTime();
    const to = new Date(query.to!).getTime();
    const items: TelemetrySample[] = [];
    for (let t = Math.ceil(from / stepMs) * stepMs; t < to; t += stepMs) items.push(sample(t));
    items.reverse();
    const page = items.slice(0, query.limit);
    return {
      items: page,
      count: page.length,
      limit: query.limit ?? 1_000,
      offset: 0,
      next_offset: items.length > page.length ? page.length : null,
      snapshot_at: SNAPSHOT,
    };
  });
  const adapter = {
    history,
    latest: vi.fn(),
    readiness: vi.fn(),
    subscribe: vi.fn(),
  } as unknown as TelemetryAdapter;
  return { adapter, queries };
}

const week = { from: new Date(T0), to: new Date(T0 + 7 * 24 * HOUR) };

describe("time-sliced history (P0 charts)", () => {
  it("splits [from, to) into non-overlapping slices, newest first", () => {
    const slices = telemetryHistorySlices({ from: new Date(T0), to: new Date(T0 + 13 * HOUR) }, 6 * HOUR);
    expect(
      slices.map((slice) => [slice.from.getTime() - T0, slice.to.getTime() - T0].map((v) => v / HOUR)),
    ).toEqual([
      [7, 13],
      [1, 7],
      [0, 1],
    ]);
  });

  it("loads every row exactly once under one snapshot, beyond the single-stream page limit", async () => {
    const { adapter, queries } = api();
    const seen = new Set<string>();
    let duplicates = 0;
    const result = await loadTelemetryHistorySlices(
      adapter,
      { channel_id: "106-01" },
      week,
      // 10 rows per page and at most 5 pages per slice: one 7-day stream (1 008 rows) would need 101.
      { pageSize: 10, maxPagesPerSlice: 5, sliceMs: 6 * HOUR, retryDelaysMs: [] },
      (samples) => {
        for (const item of samples) {
          if (seen.has(item.event_id)) duplicates += 1;
          seen.add(item.event_id);
        }
      },
    );
    expect(duplicates).toBe(0);
    expect(seen.size).toBe(7 * 24 * 6);
    expect(result).toMatchObject({ rows: 7 * 24 * 6, slices: 28, snapshotAt: SNAPSHOT });
    // The first request fixes the snapshot; every later one reuses it.
    expect(queries[0].snapshot_at).toBeUndefined();
    expect(queries.slice(1).every((query) => query.snapshot_at === SNAPSHOT)).toBe(true);
  });

  it("stops early with a volume error when the measured density exceeds the row budget", async () => {
    const { adapter, queries } = api(10_000);
    const error = await loadTelemetryHistorySlices(
      adapter,
      { channel_id: "106-01" },
      week,
      { sliceMs: 6 * HOUR, maxRows: 20_000, retryDelaysMs: [] },
      () => undefined,
    ).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(TelemetryHistoryVolumeError);
    expect((error as TelemetryHistoryVolumeError).estimatedRows).toBeGreaterThan(60_000);
    // Far fewer requests than the 7-day window would need (61 pages).
    expect(queries.length).toBeLessThan(20);
  });

  it("propagates cancellation without loading the remaining slices", async () => {
    const { adapter, queries } = api();
    const controller = new AbortController();
    const loading = loadTelemetryHistorySlices(
      adapter,
      { channel_id: "106-01" },
      week,
      { sliceMs: 6 * HOUR, retryDelaysMs: [], signal: controller.signal },
      () => controller.abort(),
    );
    await expect(loading).rejects.toBeInstanceOf(TelemetryClientError);
    expect(queries.length).toBeLessThan(28);
  });

  it("stops a multi-series load as soon as the projected rows exceed the budget", async () => {
    const { adapter, queries } = api(60_000);
    const filters = Array.from({ length: 24 }, (_, index) => ({ channel_id: `ch-${index}` }));
    const error = await loadCompleteTelemetryHistoryForSeries(adapter, filters, week, {
      retryDelaysMs: [],
      maxRows: 50_000,
      seriesConcurrency: 1,
    }).catch((caught: unknown) => caught);
    // 24 series × 10 080 rows ≈ 242 000 projected after the first series.
    expect(error).toBeInstanceOf(TelemetryHistoryVolumeError);
    expect(queries.length).toBeLessThan(30);
  });
});
