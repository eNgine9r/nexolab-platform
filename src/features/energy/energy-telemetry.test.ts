import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import {
  ENERGY_METRICS,
  energySampleState,
  findEnergySample,
  formatEnergyValue,
  isEnergySample,
  resolveEnergyMeter,
  selectLatestEnergySamples,
} from "./energy-telemetry";

function sample(overrides: Partial<TelemetrySample> = {}): TelemetrySample {
  return {
    event_id: "energy-1",
    node_id: "edge-01",
    captured_at: "2026-08-03T14:00:00Z",
    metric: "electrical.power.active",
    value: 615,
    unit: "W",
    quality: "valid",
    source: "f-and-f-le-01mp",
    equipment_id: "LE01MP-200",
    channel_id: "200-active-power",
    alarm: null,
    raw_value: 615,
    raw_status: null,
    ...overrides,
  };
}

describe("energy telemetry", () => {
  it("maps the four production meters deterministically", () => {
    expect(resolveEnergyMeter(sample())?.label).toBe("W1");
    expect(
      resolveEnergyMeter(sample({ equipment_id: "unknown", channel_id: "203-power-factor" }))?.label,
    ).toBe("W4");
    expect(resolveEnergyMeter(sample({ equipment_id: "LE01MP-204" }))).toBeNull();
  });

  it("includes cumulative active energy in deterministic metric order", () => {
    expect(ENERGY_METRICS[0].id).toBe("electrical.power.active");
    expect(ENERGY_METRICS[1]).toMatchObject({
      id: "electrical.energy.active",
      expectedUnit: "kWh",
      digits: 2,
    });
  });

  it("accepts confirmed metrics with compatible units only", () => {
    expect(isEnergySample(sample())).toBe(true);
    expect(
      isEnergySample(
        sample({
          metric: "electrical.energy.active",
          unit: "kWh",
          value: 13_745.11,
          raw_value: 1_374_511,
          channel_id: "200-active-energy",
        }),
      ),
    ).toBe(true);
    expect(
      isEnergySample(
        sample({
          metric: "electrical.energy.active",
          unit: "Wh",
          channel_id: "200-active-energy",
        }),
      ),
    ).toBe(false);
    expect(
      isEnergySample(
        sample({
          equipment_id: "LE01MP-204",
          channel_id: "204-active-energy",
          metric: "electrical.energy.active",
          unit: "kWh",
        }),
      ),
    ).toBe(false);
    expect(
      isEnergySample(sample({ metric: "electrical.voltage", unit: "W", channel_id: "200-voltage" })),
    ).toBe(false);
    expect(
      isEnergySample(sample({ metric: "temperature.internal", unit: "°C", channel_id: "200-temperature" })),
    ).toBe(true);
  });

  it("keeps the newest sample for every meter and metric", () => {
    const latest = selectLatestEnergySamples([
      sample({ event_id: "old", value: 100 }),
      sample({ event_id: "new", captured_at: "2026-08-03T14:00:05Z", value: 200 }),
      sample({
        event_id: "energy",
        metric: "electrical.energy.active",
        channel_id: "200-active-energy",
        value: 13_745.11,
        unit: "kWh",
        raw_value: 1_374_511,
      }),
      sample({
        event_id: "voltage",
        metric: "electrical.voltage",
        channel_id: "200-voltage",
        value: 230.1,
        unit: "V",
      }),
      sample({
        event_id: "invalid-voltage-unit",
        metric: "electrical.voltage",
        channel_id: "200-voltage",
        value: 900,
        unit: "W",
      }),
    ]);

    expect(latest).toHaveLength(3);
    expect(findEnergySample(latest, 200, "electrical.power.active")?.value).toBe(200);
    expect(findEnergySample(latest, 200, "electrical.energy.active")?.value).toBe(13_745.11);
    expect(findEnergySample(latest, 200, "electrical.voltage")?.value).toBe(230.1);
    expect(latest.map((item) => item.metric)).toEqual([
      "electrical.power.active",
      "electrical.energy.active",
      "electrical.voltage",
    ]);
  });

  it("distinguishes live, stale and communication failures", () => {
    const now = Date.parse("2026-08-03T14:00:20Z");
    expect(energySampleState(sample(), now)).toBe("live");
    expect(energySampleState(sample(), now + 60_000)).toBe("stale");
    expect(energySampleState(sample({ quality: "communication_error", value: null }), now)).toBe(
      "communication_error",
    );
    expect(energySampleState(null, now)).toBe("empty");
  });

  it("formats confirmed units without inventing unavailable values", () => {
    expect(formatEnergyValue(sample())).toBe("615 W");
    expect(
      formatEnergyValue(
        sample({
          metric: "electrical.energy.active",
          value: 13_745.11,
          unit: "kWh",
          raw_value: 1_374_511,
          channel_id: "200-active-energy",
        }),
      ),
    ).toBe("13 745,11 kWh");
    expect(
      formatEnergyValue(sample({ metric: "electrical.power_factor", value: 0.955, unit: "ratio" })),
    ).toBe("0,955");
    expect(formatEnergyValue(sample({ metric: "electrical.voltage", value: 615, unit: "W" }))).toBe("—");
    expect(
      formatEnergyValue(
        sample({ metric: "electrical.energy.active", value: 13_745.11, unit: "Wh" }),
      ),
    ).toBe("—");
    expect(formatEnergyValue(sample({ quality: "unknown", value: 615 }))).toBe("—");
  });
});
