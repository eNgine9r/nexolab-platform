import { describe, expect, it, vi } from "vitest";

import {
  deriveEnergyConsumption,
  loadEnergyConsumption,
  resolveEnergyConsumptionWindow,
} from "@/features/energy/energy-consumption";
import { ENERGY_METERS } from "@/features/energy/energy-telemetry";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

const meter = ENERGY_METERS[0];

function sample(eventId: string, capturedAt: string, value: number): TelemetrySample {
  return {
    event_id: eventId,
    node_id: "edge-01",
    captured_at: capturedAt,
    metric: "electrical.energy.active",
    value,
    unit: "kWh",
    quality: "valid",
    source: "modbus",
    equipment_id: meter.equipmentId,
    channel_id: "200-energy-active",
    alarm: null,
    raw_value: Math.round(value * 100),
    raw_status: null,
  };
}

describe("energy consumption windows", () => {
  it("resolves local calendar and rolling presets", () => {
    const now = new Date(2026, 7, 17, 20, 16, 0);
    const today = resolveEnergyConsumptionWindow("today", now)!;
    expect([today.from.getFullYear(), today.from.getMonth(), today.from.getDate()]).toEqual([2026, 7, 17]);
    expect([today.from.getHours(), today.from.getMinutes()]).toEqual([0, 0]);
    expect(today.to.getTime()).toBe(now.getTime());

    const yesterday = resolveEnergyConsumptionWindow("yesterday", now)!;
    expect(yesterday.from.getDate()).toBe(16);
    expect(yesterday.to.getDate()).toBe(17);
    expect(yesterday.to.getHours()).toBe(0);

    const last24h = resolveEnergyConsumptionWindow("last24h", now)!;
    expect(last24h.to.getTime() - last24h.from.getTime()).toBe(24 * 60 * 60 * 1000);
  });

  it("validates custom local ranges", () => {
    const now = new Date(2026, 7, 17, 20, 16, 0);
    const custom = resolveEnergyConsumptionWindow("custom", now, {
      fromLocal: "2026-08-17T08:00",
      toLocal: "2026-08-17T20:00",
    });
    expect(custom?.from.getHours()).toBe(8);
    expect(custom?.to.getHours()).toBe(20);
    expect(
      resolveEnergyConsumptionWindow("custom", now, {
        fromLocal: "2026-08-17T20:00",
        toLocal: "2026-08-17T08:00",
      }),
    ).toBeNull();
  });
});

describe("deriveEnergyConsumption", () => {
  it("derives kWh only from cumulative boundary readings", () => {
    const result = deriveEnergyConsumption(
      sample("start", "2026-08-17T08:00:00.000Z", 25_390.73),
      sample("end", "2026-08-17T20:00:00.000Z", 25_409.45),
      meter,
    );
    expect(result.status).toBe("ready");
    expect(result.valueKwh).toBeCloseTo(18.72, 6);
  });

  it("refuses negative reset/rollover-like deltas", () => {
    expect(
      deriveEnergyConsumption(
        sample("start", "2026-08-17T08:00:00.000Z", 100),
        sample("end", "2026-08-17T20:00:00.000Z", 5),
        meter,
      ),
    ).toMatchObject({ status: "discontinuity", valueKwh: null });
  });

  it("returns unavailable without both boundaries", () => {
    expect(deriveEnergyConsumption(null, null, meter)).toMatchObject({
      status: "unavailable",
      valueKwh: null,
    });
  });
});

describe("loadEnergyConsumption", () => {
  it("uses current live cumulative as the end boundary and queries only the start anchor", async () => {
    const history = vi.fn().mockResolvedValue({
      items: [sample("start", "2026-08-17T07:59:30.000Z", 10)],
      count: 1,
      limit: 1,
      offset: 0,
      next_offset: null,
      snapshot_at: "2026-08-17T20:00:00.000Z",
    });
    const adapter = { history } as unknown as TelemetryAdapter;
    const result = await loadEnergyConsumption(adapter, {
      nodeId: "edge-01",
      meter,
      window: {
        from: new Date("2026-08-17T08:00:00.000Z"),
        to: new Date("2026-08-17T20:00:00.000Z"),
      },
      currentCumulative: sample("end", "2026-08-17T19:59:45.000Z", 12.5),
    });

    expect(result).toMatchObject({ status: "ready", valueKwh: 2.5 });
    expect(history).toHaveBeenCalledTimes(1);
    expect(history).toHaveBeenCalledWith(
      expect.objectContaining({
        node_id: "edge-01",
        equipment_id: meter.equipmentId,
        metric: "electrical.energy.active",
        quality: "valid",
        limit: 1,
      }),
      undefined,
    );
  });

  it("returns unavailable when persisted boundary evidence is missing", async () => {
    const history = vi.fn().mockResolvedValue({
      items: [],
      count: 0,
      limit: 1,
      offset: 0,
      next_offset: null,
      snapshot_at: "2026-08-17T20:00:00.000Z",
    });
    const adapter = { history } as unknown as TelemetryAdapter;
    const result = await loadEnergyConsumption(adapter, {
      nodeId: "edge-01",
      meter,
      window: {
        from: new Date("2026-08-17T08:00:00.000Z"),
        to: new Date("2026-08-17T20:00:00.000Z"),
      },
      currentCumulative: sample("end", "2026-08-17T19:59:45.000Z", 12.5),
    });
    expect(result).toMatchObject({ status: "unavailable", valueKwh: null });
  });
});
