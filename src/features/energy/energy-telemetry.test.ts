import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";
import type { CommissionedEnergyMeter } from "./energy-commissioned-meters";

import {
  ENERGY_METRICS,
  energyMeterSupportsMetric,
  energySampleState,
  findEnergySample,
  findEnergySampleForMeter,
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

function cumulativeEnergySample(overrides: Partial<TelemetrySample> = {}): TelemetrySample {
  return sample({
    metric: "electrical.energy.active",
    value: 13_745.11,
    unit: "kWh",
    raw_value: 1_374_511,
    channel_id: "200-active-energy",
    ...overrides,
  });
}

describe("energy telemetry", () => {
  it("resolves only authorized node and equipment identities for scoped meters", () => {
    const first: CommissionedEnergyMeter = {
      nodeId: "edge-01",
      busId: "commissioning-0123456789abcdef",
      unitId: 1,
      equipmentId: "SDM120M:commissioning-0123456789abcdef:1",
      label: "First",
      modelLabel: "SDM",
      family: "sdm120",
    };
    const second: CommissionedEnergyMeter = {
      ...first,
      busId: "commissioning-fedcba9876543210",
      equipmentId: "SDM120M:commissioning-fedcba9876543210:1",
      label: "Second",
    };
    const inventory = [first, second];
    const a = sample({ equipment_id: first.equipmentId, channel_id: "1-active-power", value: 100 });
    const b = sample({
      event_id: "b",
      equipment_id: second.equipmentId,
      channel_id: "1-active-power",
      value: 200,
    });
    const legacy = sample({
      event_id: "legacy",
      equipment_id: "SDM120M-1",
      channel_id: "1-active-power",
      value: 300,
    });
    const foreign = sample({ event_id: "foreign", node_id: "edge-02", equipment_id: first.equipmentId });
    expect(resolveEnergyMeter(a)).toBeNull();
    expect(resolveEnergyMeter(a, inventory)).toEqual(first);
    expect(resolveEnergyMeter(foreign, inventory)).toBeNull();
    expect(resolveEnergyMeter({ ...foreign, channel_id: "200-active-power" }, inventory)).toBeNull();
    const all = [a, b, legacy, foreign];
    expect(selectLatestEnergySamples(all, inventory)).toHaveLength(3);
    expect(findEnergySampleForMeter(all, "edge-01", first, "electrical.power.active", inventory)?.value).toBe(
      100,
    );
    expect(
      findEnergySampleForMeter(all, "edge-01", second, "electrical.power.active", inventory)?.value,
    ).toBe(200);
    expect(findEnergySampleForMeter(all, "edge-02", first, "electrical.power.active", inventory)).toBeNull();
  });
  it("keeps latest samples from identical meter IDs on different nodes separate", () => {
    const a = sample({ event_id: "a", node_id: "node-a", value: 10 });
    const b = sample({ event_id: "b", node_id: "node-b", value: 20 });
    expect(
      selectLatestEnergySamples([a, b])
        .map((item) => item.node_id)
        .sort(),
    ).toEqual(["node-a", "node-b"]);
  });
  it("maps heterogeneous production energy meters deterministically", () => {
    expect(resolveEnergyMeter(sample())?.label).toBe("W1");
    expect(
      resolveEnergyMeter(
        sample({
          equipment_id: "unknown",
          channel_id: "203-power-factor",
        }),
      )?.label,
    ).toBe("W4");
    expect(
      resolveEnergyMeter(
        sample({
          equipment_id: "SDM120M-1",
          channel_id: "1-voltage",
          source: "eastron-sdm120m",
          metric: "electrical.voltage",
          value: 227.8,
          unit: "V",
        }),
      )?.label,
    ).toBe("SDM120M");
    expect(
      resolveEnergyMeter(
        sample({
          equipment_id: "LE01MP-204",
          channel_id: "204-active-power",
        }),
      ),
    ).toBeNull();
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
    expect(isEnergySample(cumulativeEnergySample())).toBe(true);
    expect(
      isEnergySample(
        cumulativeEnergySample({
          unit: "Wh",
        }),
      ),
    ).toBe(false);
    expect(
      isEnergySample(
        cumulativeEnergySample({
          equipment_id: "LE01MP-204",
          channel_id: "204-active-energy",
        }),
      ),
    ).toBe(false);
    expect(
      isEnergySample(
        sample({
          metric: "electrical.voltage",
          unit: "W",
          channel_id: "200-voltage",
        }),
      ),
    ).toBe(false);
    expect(
      isEnergySample(
        sample({
          metric: "temperature.internal",
          unit: "°C",
          channel_id: "200-temperature",
        }),
      ),
    ).toBe(true);
    expect(
      isEnergySample(
        sample({
          equipment_id: "SDM120M-1",
          source: "eastron-sdm120m",
          metric: "temperature.internal",
          unit: "degC",
          channel_id: "1-temperature",
        }),
      ),
    ).toBe(false);
    const sdm120 = resolveEnergyMeter(sample({ equipment_id: "SDM120M-1", channel_id: "1-voltage" }));
    expect(sdm120).not.toBeNull();
    expect(energyMeterSupportsMetric(sdm120!, "temperature.internal")).toBe(false);
    expect(energyMeterSupportsMetric(sdm120!, "electrical.voltage")).toBe(true);
  });

  it("keeps the newest sample for every meter and metric", () => {
    const latest = selectLatestEnergySamples([
      sample({ event_id: "old", value: 100 }),
      sample({
        event_id: "new",
        captured_at: "2026-08-03T14:00:05Z",
        value: 200,
      }),
      cumulativeEnergySample({
        event_id: "energy",
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
    expect(
      energySampleState(
        sample({
          quality: "communication_error",
          value: null,
        }),
        now,
      ),
    ).toBe("communication_error");
    expect(energySampleState(null, now)).toBe("empty");
  });

  it("formats confirmed units without inventing unavailable values", () => {
    expect(formatEnergyValue(sample())).toBe("615 W");
    expect(formatEnergyValue(cumulativeEnergySample())).toBe("13 745,11 kWh");
    expect(
      formatEnergyValue(
        sample({
          metric: "electrical.power_factor",
          value: 0.955,
          unit: "ratio",
        }),
      ),
    ).toBe("0,955");
    expect(
      formatEnergyValue(
        sample({
          metric: "electrical.voltage",
          value: 615,
          unit: "W",
        }),
      ),
    ).toBe("—");
    expect(
      formatEnergyValue(
        cumulativeEnergySample({
          unit: "Wh",
        }),
      ),
    ).toBe("—");
    expect(
      formatEnergyValue(
        sample({
          quality: "unknown",
          value: 615,
        }),
      ),
    ).toBe("—");
  });
});
