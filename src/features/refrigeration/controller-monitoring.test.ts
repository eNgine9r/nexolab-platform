import { describe, expect, it, vi } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import {
  EMBRACO_METRICS,
  buildEmbracoSnapshot,
  resolveRefrigerationHistoryRange,
} from "./controller-monitoring";

function sample(
  metric: string,
  value: number | null,
  capturedAt: string,
  quality: TelemetrySample["quality"] = "valid",
): TelemetrySample {
  return {
    event_id: `${metric}-${capturedAt}`,
    node_id: "edge-01",
    captured_at: capturedAt,
    metric,
    value,
    unit: metric === EMBRACO_METRICS.compressorSpeed ? "rpm" : "state",
    quality,
    source: "embraco-sync",
    equipment_id: "EMBRACO-2",
    channel_id: `2-${metric}`,
    alarm: null,
    raw_value: value,
    raw_status: null,
  };
}

describe("resolveRefrigerationHistoryRange", () => {
  const now = new Date("2026-08-28T18:00:00.000Z");

  it.each([
    ["1h", 1],
    ["12h", 12],
    ["24h", 24],
  ] as const)("resolves %s to the exact requested duration", (preset, hours) => {
    const range = resolveRefrigerationHistoryRange(preset, now);
    expect(range.to.toISOString()).toBe(now.toISOString());
    expect(range.to.getTime() - range.from.getTime()).toBe(hours * 60 * 60 * 1000);
  });

  it("uses exact custom from/to boundaries", () => {
    const custom = {
      from: new Date("2026-08-27T05:17:00.000Z"),
      to: new Date("2026-08-28T10:43:00.000Z"),
    };
    expect(resolveRefrigerationHistoryRange("custom", now, custom)).toEqual(custom);
  });

  it("rejects malformed custom ranges", () => {
    expect(() => resolveRefrigerationHistoryRange("custom", now, null)).toThrow();
    expect(() => resolveRefrigerationHistoryRange("custom", now, { from: now, to: now })).toThrow();
  });
});

describe("buildEmbracoSnapshot", () => {
  it("decodes verified state, relays, alarms and RPM without inventing unknown temperatures", () => {
    vi.setSystemTime(new Date("2026-08-28T18:00:30.000Z"));
    const snapshot = buildEmbracoSnapshot([
      sample(EMBRACO_METRICS.compressorSpeed, 4500, "2026-08-28T18:00:00.000Z"),
      sample(EMBRACO_METRICS.controlState, 5, "2026-08-28T18:00:00.000Z"),
      sample(EMBRACO_METRICS.relays, 11, "2026-08-28T18:00:00.000Z"),
      sample(EMBRACO_METRICS.alarms, 0, "2026-08-28T18:00:00.000Z"),
      sample(EMBRACO_METRICS.cabinet, null, "2026-08-28T18:00:00.000Z", "unknown"),
    ]);

    expect(snapshot.compressorSpeedRpm).toBe(4500);
    expect(snapshot.controlState).toBe("Pulldown");
    expect(snapshot.relayStates).toEqual([true, true, false, true]);
    expect(snapshot.activeAlarms).toEqual([]);
    expect(snapshot.latestByMetric.get(EMBRACO_METRICS.cabinet)?.quality).toBe("unknown");
    expect(snapshot.online).toBe(true);
    vi.useRealTimers();
  });
});
