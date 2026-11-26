import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import {
  buildOverviewChartBase,
  buildOverviewChartGroups,
  overviewChartGroupsForDomain,
} from "./overview-chart";
import { appendHistoryTail, orderedHistoryWindow, trimHistoryWindow } from "./overview-history-window";

const T0 = Date.parse("2026-11-25T00:00:00Z");
const STEP = 10_000;

function probe(index: number, channel = "106-01", overrides: Partial<TelemetrySample> = {}): TelemetrySample {
  return {
    event_id: `${channel}-${index}`,
    node_id: "edge-01",
    captured_at: new Date(T0 + index * STEP).toISOString(),
    metric: "temperature",
    value: 4 + Math.sin(index / 40),
    unit: "degC",
    quality: "valid",
    source: "xjp60d",
    equipment_id: "XJP60D-1",
    channel_id: channel,
    alarm: null,
    raw_value: 40,
    raw_status: null,
    ...overrides,
  };
}

function window(fromIndex: number, toIndex: number) {
  return { from: new Date(T0 + fromIndex * STEP), to: new Date(T0 + toIndex * STEP) };
}

function ids(samples: readonly TelemetrySample[]): string[] {
  return samples.map((sample) => sample.event_id);
}

describe("Overview history window (#1827)", () => {
  const held = orderedHistoryWindow(
    Array.from({ length: 200 }, (_, index) => [probe(index), probe(index, "106-02")]).flat(),
    window(0, 199),
  );

  it("appends an in-order live tail exactly like the full rebuild", () => {
    const incoming = [probe(200, "106-02"), probe(200), probe(201)];
    const next = window(2, 201);
    const fast = appendHistoryTail(held, incoming, next);
    expect(ids(fast)).toEqual(ids(orderedHistoryWindow([...held, ...incoming], next)));
    expect(fast[0].captured_at).toBe(new Date(T0 + 2 * STEP).toISOString());
  });

  it("falls back to the full rebuild for late, repeated or same-instant events", () => {
    const cases: TelemetrySample[][] = [
      [probe(150, "106-03")], // late
      [probe(199)], // repeated event id
      [probe(205, "106-01", { event_id: "106-01-10" })], // repeated id with a newer time
      [probe(203), probe(203, "106-01", { event_id: "106-01-203" })], // duplicate within incoming
    ];
    for (const incoming of cases) {
      const next = window(0, 210);
      expect(ids(appendHistoryTail(held, incoming, next))).toEqual(
        ids(orderedHistoryWindow([...held, ...incoming], next)),
      );
    }
  });

  it("trims a moved window by binary search and keeps the same array when unchanged", () => {
    expect(trimHistoryWindow(held, window(0, 199))).toBe(held);
    const trimmed = trimHistoryWindow(held, window(50, 120));
    expect(ids(trimmed)).toEqual(ids(orderedHistoryWindow(held, window(50, 120))));
  });
});

describe("Overview chart domain (#1827)", () => {
  // One probe, 24 h at 10 s, a single sharp peak and a communication error.
  const samples = Array.from({ length: 8_640 }, (_, index) =>
    index === 5_000
      ? probe(index, "106-01", { value: 30 })
      : index === 6_000
        ? probe(index, "106-01", { value: null, quality: "communication_error" })
        : probe(index),
  );
  const fullDomain = { fromMs: T0, toMs: T0 + 8_639 * STEP };
  const base = buildOverviewChartBase({ samples, status: "live", historical: false, now: T0 + 8_640 * STEP });

  it("matches the previous single-call builder for the full range", () => {
    const viaDomain = overviewChartGroupsForDomain(base, fullDomain);
    const direct = buildOverviewChartGroups({
      samples,
      status: "live",
      xDomain: fullDomain,
      historical: false,
      now: T0 + 8_640 * STEP,
    });
    expect(viaDomain).toEqual(direct);
    expect("rawSegments" in viaDomain[0].scene.series[0]).toBe(false);
  });

  it("shows the original measurements of a zoomed window and keeps the peak and the break", () => {
    const zoom = { fromMs: T0 + 4_990 * STEP, toMs: T0 + 5_010 * STEP };
    const [group] = overviewChartGroupsForDomain(base, zoom, zoom);
    const points = group.scene.series[0].segments.flatMap((segment) => segment.points);
    const inside = points.filter(
      (point) => point.timestampMs >= T0 + 4_980 * STEP && point.timestampMs <= T0 + 5_020 * STEP,
    );
    // ±50 % margin: every raw sample from index 4 980 to 5 020.
    expect(inside).toHaveLength(41);
    expect(inside.map((point) => point.value)).toContain(30);
    // Outside the detail range the full-range points remain, so panning never shows blank space.
    expect(points.some((point) => point.timestampMs < T0 + 4_000 * STEP)).toBe(true);
    // The communication error still splits the series.
    const coarseSegments = overviewChartGroupsForDomain(base, fullDomain)[0].scene.series[0].segments.length;
    expect(group.scene.series[0].segments).toHaveLength(coarseSegments);
    expect(coarseSegments).toBeGreaterThan(1);
  });

  it("keeps the extreme of a wide zoom within the point budget", () => {
    const zoom = { fromMs: T0 + 3_000 * STEP, toMs: T0 + 7_000 * STEP };
    const [group] = overviewChartGroupsForDomain(base, zoom, zoom);
    const points = group.scene.series[0].segments.flatMap((segment) => segment.points);
    expect(points.map((point) => point.value)).toContain(30);
    expect(points.length).toBeLessThan(600);
  });
});
