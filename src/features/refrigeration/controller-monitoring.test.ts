import { describe, expect, it, vi } from "vitest";

import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";
import type { RefrigerationControllerBinding } from "./controller-binding-repository";

import {
  EMBRACO_HISTORY_METRICS,
  EMBRACO_METRICS,
  buildEmbracoSnapshot,
  loadEmbracoHistory,
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

describe("Embraco history binding time boundary", () => {
  const binding: RefrigerationControllerBinding = {
    id: "moved",
    equipmentId: "KK1",
    nodeId: "edge-01",
    controllerFamily: "embraco",
    controllerEquipmentId: "EMBRACO-2",
    unitId: 2,
    profileVersion: "embraco-sync-fc03-v1.00.04",
    boundAt: "2026-11-19T13:28:25.010Z",
    verifiedFromTelemetry: true,
  };
  const requested = {
    from: new Date("2026-11-19T12:00:00.000Z"),
    to: new Date("2026-11-19T14:00:00.000Z"),
  };

  it("loads both temperature probes only from KK1's new binding time, not KK2 history", async () => {
    const history = vi.fn(async () => ({
      items: [],
      count: 0,
      limit: 1000,
      offset: 0,
      next_offset: null,
      snapshot_at: "2026-11-19T14:00:00.000Z",
    }));
    const result = await loadEmbracoHistory({ history } as unknown as TelemetryAdapter, binding, requested);
    expect(history).toHaveBeenCalled();
    expect([...history.mock.calls].length).toBe(EMBRACO_HISTORY_METRICS.length);
    expect(result.has(EMBRACO_METRICS.cabinet)).toBe(true);
    expect(result.has(EMBRACO_METRICS.evaporator)).toBe(true);
    for (const [query] of history.mock.calls as unknown as [Record<string, unknown>][]) {
      expect((query.from as Date).toISOString()).toBe(binding.boundAt);
      expect((query.to as Date).toISOString()).toBe(requested.to.toISOString());
    }
  });

  it("does not fetch history when the entire requested interval predates KK1 association", async () => {
    const history = vi.fn();
    const result = await loadEmbracoHistory({ history } as unknown as TelemetryAdapter, binding, {
      from: new Date("2026-11-18T00:00:00.000Z"),
      to: new Date("2026-11-18T01:00:00.000Z"),
    });
    expect(history).not.toHaveBeenCalled();
    expect(result.get(EMBRACO_METRICS.cabinet)).toEqual([]);
  });
});
