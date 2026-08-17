import { describe, expect, it, vi } from "vitest";

import {
  createEnergyBoundaryHistoryCache,
  selectEnergyBoundarySample,
} from "@/features/energy/energy-consumption-cache";
import { ENERGY_METERS } from "@/features/energy/energy-telemetry";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

function sample(unitId: number, eventId: string, capturedAt: string, value: number): TelemetrySample {
  return {
    event_id: eventId,
    node_id: "edge-01",
    captured_at: capturedAt,
    metric: "electrical.energy.active",
    value,
    unit: "kWh",
    quality: "valid",
    source: "modbus",
    equipment_id: `LE01MP-${unitId}`,
    channel_id: `${unitId}-energy-active`,
    alarm: null,
    raw_value: Math.round(value * 100),
    raw_status: null,
  };
}

describe("energy boundary history cache", () => {
  it("coalesces equivalent meter-card boundary reads into one REST history request", async () => {
    const items = ENERGY_METERS.map((meter, index) =>
      sample(meter.unitId, `energy-${meter.unitId}`, "2026-08-16T20:15:30.000Z", 100 + index),
    );
    const history = vi.fn().mockResolvedValue({
      items,
      count: items.length,
      limit: 1000,
      offset: 0,
      next_offset: null,
      snapshot_at: "2026-08-17T20:16:00.000Z",
    });
    const adapter = { history } as unknown as TelemetryAdapter;
    const cache = createEnergyBoundaryHistoryCache();
    const boundaries = [
      new Date("2026-08-16T20:16:01.000Z"),
      new Date("2026-08-16T20:16:02.000Z"),
      new Date("2026-08-16T20:16:03.000Z"),
      new Date("2026-08-16T20:16:04.000Z"),
    ];

    const results = await Promise.all(
      boundaries.map((boundary) =>
        cache.load({
          adapter,
          scopeKey: "viewer:organization",
          nodeId: "edge-01",
          boundary,
        }),
      ),
    );

    expect(history).toHaveBeenCalledTimes(1);
    expect(results.every((result) => result === results[0])).toBe(true);
  });

  it("selects the latest valid sample at or before each requested boundary", () => {
    const meter = ENERGY_METERS[0];
    const samples = [
      sample(200, "older", "2026-08-17T07:58:30.000Z", 10),
      sample(200, "nearest", "2026-08-17T07:59:45.000Z", 11),
      sample(200, "future", "2026-08-17T08:00:05.000Z", 12),
      sample(201, "other-meter", "2026-08-17T07:59:55.000Z", 20),
    ];

    expect(selectEnergyBoundarySample(samples, meter, new Date("2026-08-17T08:00:00.000Z"))?.event_id).toBe(
      "nearest",
    );
  });

  it("isolates cached history by authenticated scope", async () => {
    const history = vi.fn().mockResolvedValue({
      items: [],
      count: 0,
      limit: 1000,
      offset: 0,
      next_offset: null,
      snapshot_at: "2026-08-17T20:16:00.000Z",
    });
    const adapter = { history } as unknown as TelemetryAdapter;
    const cache = createEnergyBoundaryHistoryCache();
    const boundary = new Date("2026-08-16T20:16:00.000Z");

    await cache.load({ adapter, scopeKey: "viewer-a:org", nodeId: "edge-01", boundary });
    await cache.load({ adapter, scopeKey: "viewer-b:org", nodeId: "edge-01", boundary });

    expect(history).toHaveBeenCalledTimes(2);
  });
});
