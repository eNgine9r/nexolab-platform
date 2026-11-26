import { describe, expect, it } from "vitest";

import { buildChartSegments } from "@/features/charts/continuity";
import type { TelemetrySample } from "@/lib/telemetry/types";

import {
  appendLiveHistoryTail,
  deriveLiveSourceGapMsByChannel,
  downsampleLiveHistory,
  isLiveHistorySegmentStart,
  liveHistorySegments,
  mergeLiveHistoryTail,
} from "./live-history";
import { liveChannelKey } from "./live-telemetry";

const HOUR = 3_600_000;
const T0 = Date.parse("2026-11-25T12:00:00Z");
const CADENCE = 10_000;

function sample(
  index: number,
  timestampMs: number,
  overrides: Partial<TelemetrySample> = {},
): TelemetrySample {
  return {
    event_id: `e-${index}`,
    schema_version: 1,
    node_id: "edge-01",
    equipment_id: "XJP60D-1",
    channel_id: "temperature-1",
    metric: "temperature",
    unit: "degC",
    // Smooth daily drift, a short 8 °C excursion every ~4 h and deterministic sensor noise.
    value:
      4 +
      2 * Math.sin(timestampMs / (2 * HOUR)) +
      (index % 1_500 === 700 ? 8 : 0) +
      ((index * 7_919) % 10) / 100,
    quality: "valid",
    alarm: null,
    captured_at: new Date(timestampMs).toISOString(),
    received_at: new Date(timestampMs + 150).toISOString(),
    ...overrides,
  } as TelemetrySample;
}

function continuousDay(): TelemetrySample[] {
  const raw: TelemetrySample[] = [];
  let index = 0;
  for (let timestampMs = T0 - 24 * HOUR; timestampMs <= T0; timestampMs += CADENCE) {
    raw.push(sample(index, timestampMs));
    index += 1;
  }
  return raw;
}

function dayWindow(toMs: number) {
  return { from: new Date(toMs - 24 * HOUR), to: new Date(toMs) };
}

function maximum(samples: readonly TelemetrySample[]): number {
  return samples.reduce((max, entry) => Math.max(max, entry.value ?? Number.NEGATIVE_INFINITY), -Infinity);
}

describe("Live history continuity on 24 h windows (#1805)", () => {
  it("keeps a continuous 24 h series in one segment through 60 minutes of live tail and clock ticks", () => {
    const raw = continuousDay();
    const gaps = deriveLiveSourceGapMsByChannel(raw);
    const key = liveChannelKey(raw[0]);
    const lookup = (channelKey: string) => gaps.get(channelKey);
    let current = downsampleLiveHistory(raw, dayWindow(T0), 240);
    expect(liveHistorySegments(current)).toHaveLength(1);

    let index = raw.length;
    let now = T0;
    for (let step = 0; step < 360; step += 1) {
      now += CADENCE;
      current = mergeLiveHistoryTail(
        current,
        [sample(index, now)],
        new Set([key]),
        dayWindow(now),
        240,
        lookup,
      );
      index += 1;
      // The 5 s clock tick slides the window without new samples.
      current = mergeLiveHistoryTail(current, [], new Set([key]), dayWindow(now + 5_000), 240, lookup);
    }

    const segments = liveHistorySegments(current);
    expect(segments).toHaveLength(1);
    expect(current.length).toBeLessThanOrEqual(240 + 60);
    // The short excursions inside the window stay visible after repeated tail merges.
    expect(maximum(current)).toBeCloseTo(
      maximum(raw.filter((entry) => Date.parse(entry.captured_at) >= now - 24 * HOUR)),
      6,
    );
  });

  it("still breaks the line once for a real silent gap in the live tail", () => {
    const raw = continuousDay();
    const gaps = deriveLiveSourceGapMsByChannel(raw);
    const lookup = (channelKey: string) => gaps.get(channelKey);
    let current = downsampleLiveHistory(raw, dayWindow(T0), 240);
    const resumedAt = T0 + 10 * 60_000; // 10 minutes without any sample
    current = appendLiveHistoryTail(current, [sample(90_001, resumedAt)], dayWindow(resumedAt), 240, {
      sourceGapMsFor: lookup,
    });
    current = appendLiveHistoryTail(
      current,
      [sample(90_002, resumedAt + CADENCE)],
      dayWindow(resumedAt + CADENCE),
      240,
      { sourceGapMsFor: lookup },
    );

    expect(liveHistorySegments(current)).toHaveLength(2);
    expect(isLiveHistorySegmentStart(current.find((entry) => entry.event_id.endsWith("e-90001"))!)).toBe(
      true,
    );
  });

  it("breaks after an invalid live sample even when it arrives in a separate call", () => {
    const raw = continuousDay();
    const gaps = deriveLiveSourceGapMsByChannel(raw);
    const pending = new Set<string>();
    const options = { sourceGapMsFor: (key: string) => gaps.get(key), pendingBreakChannels: pending };
    let current = downsampleLiveHistory(raw, dayWindow(T0), 240);
    current = appendLiveHistoryTail(
      current,
      [sample(90_001, T0 + CADENCE, { quality: "communication_error", value: null })],
      dayWindow(T0 + CADENCE),
      240,
      options,
    );
    current = appendLiveHistoryTail(
      current,
      [sample(90_002, T0 + 2 * CADENCE)],
      dayWindow(T0 + 2 * CADENCE),
      240,
      options,
    );

    expect(liveHistorySegments(current)).toHaveLength(2);
    expect(current.some((entry) => entry.event_id.endsWith("e-90001"))).toBe(false);
    expect(pending.size).toBe(0);
  });

  it("derives the tolerance from raw cadence, not from reduced spacing", () => {
    const raw = continuousDay();
    const gap = deriveLiveSourceGapMsByChannel(raw).get(liveChannelKey(raw[0]));
    expect(gap).toBe(30_000);
  });

  it("does not re-segment reduced continuous history when building chart segments", () => {
    for (const cadenceMs of [10_000, 30_000, 60_000]) {
      for (const hours of [6, 24, 168]) {
        const raw: TelemetrySample[] = [];
        let index = 0;
        for (let timestampMs = T0 - hours * HOUR; timestampMs <= T0; timestampMs += cadenceMs) {
          raw.push(sample(index, timestampMs));
          index += 1;
        }
        const reduced = downsampleLiveHistory(
          raw,
          { from: new Date(T0 - hours * HOUR), to: new Date(T0) },
          240,
        );
        const segments = liveHistorySegments(reduced).flatMap((segment) =>
          buildChartSegments(
            {
              nodeId: "edge-01",
              equipmentId: "XJP60D-1",
              channelId: "temperature-1",
              metric: "temperature",
              nativeUnit: "degC",
            },
            segment.map((entry) => ({
              id: entry.event_id,
              timestampMs: Date.parse(entry.captured_at),
              value: entry.value,
              quality: entry.quality,
            })),
            { maximumSourceGapMs: Number.MAX_SAFE_INTEGER },
          ),
        );
        expect(segments, `${cadenceMs / 1_000} s cadence, ${hours} h`).toHaveLength(1);
      }
    }
  });
});
