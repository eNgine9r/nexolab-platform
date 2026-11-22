import { describe, expect, it, vi } from "vitest";

import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

import { downsampleLiveHistory, loadCompleteLiveHistory, mergeLiveHistoryTail } from "./live-history";
import { liveChannelKey } from "./live-telemetry";

// Well in the past: samples dated after "now" are rejected as future skew.
const T0 = Date.parse("2026-11-10T00:00:00Z");
const COUNT = 6_000;

function sample(index: number, value: number): TelemetrySample {
  return {
    event_id: `e-${index}`,
    node_id: "edge-1",
    captured_at: new Date(T0 + index * 10_000).toISOString(),
    metric: "temperature",
    value,
    unit: "degC",
    quality: "valid",
    source: "test",
    equipment_id: "K106",
    channel_id: "106-01",
    alarm: null,
    raw_value: value,
    raw_status: null,
  };
}

const window = { from: new Date(T0 - 1), to: new Date(T0 + COUNT * 10_000) };
const raw = Array.from({ length: COUNT }, (_, index) => sample(index, index === 3_333 ? 40 : 4));

describe("Live history density budget (#1620)", () => {
  it("keeps more points for a higher budget and never loses the extreme excursion", () => {
    const auto = downsampleLiveHistory(raw, window);
    const high = downsampleLiveHistory(raw, window, 2_500);
    expect(auto.length).toBeLessThan(high.length);
    expect(high.length).toBeLessThanOrEqual(2_500 + 10);
    for (const result of [auto, high]) {
      expect(Math.max(...result.map((entry) => entry.value ?? 0))).toBe(40);
    }
  });

  it("applies the same budget when merging a live tail", () => {
    const key = liveChannelKey(raw[0]);
    const merged = mergeLiveHistoryTail(raw, [sample(COUNT - 1, 4)], new Set([key]), window, 500);
    expect(merged.length).toBeLessThanOrEqual(500 + 10);
    expect(Math.max(...merged.map((entry) => entry.value ?? 0))).toBe(40);
  });

  it("passes the budget through the complete-history loader", async () => {
    const adapter = {
      readiness: vi.fn(),
      latest: vi.fn(),
      subscribe: vi.fn(),
      history: vi.fn(async () => ({
        items: raw.slice(-1_000),
        count: 1_000,
        limit: 1_000,
        offset: 0,
        next_offset: null,
        snapshot_at: new Date(T0 + COUNT * 10_000).toISOString(),
      })),
    } as unknown as TelemetryAdapter;
    const small = await loadCompleteLiveHistory(adapter, [raw[0]], window, undefined, 120);
    const large = await loadCompleteLiveHistory(adapter, [raw[0]], window, undefined, 900);
    expect(small.samples.length).toBeLessThan(large.samples.length);
    expect(large.intervalColumns[liveChannelKey(raw[0])]).toBeDefined();
  });
});
