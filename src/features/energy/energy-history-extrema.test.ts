import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import { downsampleEnergyHistory } from "./energy-history";

function power(index: number, value: number, unit = 200): TelemetrySample {
  return {
    event_id: `energy-edge-01-${unit}-${index}`,
    node_id: "edge-01",
    captured_at: new Date(Date.UTC(2026, 7, 3, 10, 0, index * 10)).toISOString(),
    metric: "electrical.power.active",
    value,
    unit: "W",
    quality: "valid",
    source: "f-and-f-le-01mp",
    equipment_id: `LE01MP-${unit}`,
    channel_id: `${unit}-active-power`,
    alarm: null,
    raw_value: value,
    raw_status: null,
  };
}

describe("Energy history reduction keeps extrema (#1649)", () => {
  it("retains a one-sample power spike and dip that bucket-last sampling used to drop", () => {
    const source = Array.from({ length: 2_000 }, (_, index) => power(index, 500));
    source[777] = power(777, 4_800); // short spike
    source[1_234] = power(1_234, 3); // short dip
    const reduced = downsampleEnergyHistory(source, 240);
    const values = reduced.map((entry) => entry.value);
    expect(reduced.length).toBeLessThanOrEqual(240);
    expect(values).toContain(4_800);
    expect(values).toContain(3);
    expect(reduced[0].event_id).toBe(source[0].event_id);
    expect(reduced.at(-1)!.event_id).toBe(source.at(-1)!.event_id);
    const times = reduced.map((entry) => Date.parse(entry.captured_at));
    expect([...times].sort((a, b) => a - b)).toEqual(times);
  });

  it("returns every sample unchanged when under the budget", () => {
    const source = Array.from({ length: 50 }, (_, index) => power(index, index));
    expect(downsampleEnergyHistory(source, 240)).toHaveLength(50);
  });

  it("keeps full bucket resolution for monotonic cumulative energy counters", () => {
    const counter = Array.from({ length: 2_000 }, (_, index) => ({
      ...power(index, 100 + index / 10),
      metric: "electrical.energy.active",
      unit: "kWh",
      channel_id: "200-active-energy",
    }));
    const reduced = downsampleEnergyHistory(counter, 240);
    expect(reduced.length).toBeGreaterThan(200);
    expect(reduced.length).toBeLessThanOrEqual(240);
  });
});
