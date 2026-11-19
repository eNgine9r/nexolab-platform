import { describe, expect, it } from "vitest";
import { monitoredTemperatureChannels } from "./temperature-monitoring";

export function registryFixture() {
  const bus = "rs485-sdm120";
  return {
    schema_version: 2,
    revision: 46,
    buses: [{ bus_id: bus, protocol: "modbus_rtu", read_only: true }],
    devices: [1, 7].map((unit) => ({
      device_id: `xjp60d-sections:${bus}:${unit}`,
      bus_id: bus,
      unit_id: unit,
      device_family: "xjp60d",
      lifecycle: "active",
    })),
    targets: [1, 7].flatMap((unit) =>
      Array.from({ length: 6 }, (_, index) => {
        const active = unit === 1 || index < 2;
        const channel = `${bus}:${unit}-S0${index + 1}`;
        return {
          device_id: `xjp60d-sections:${bus}:${unit}`,
          target_id: `xjp60d-sections:${channel}`,
          telemetry_channel_id: channel,
          metric: "temperature.probe",
          unit: "degC",
          function: 3,
          lifecycle: active ? "active" : "reserve",
          poll_eligible: active,
        };
      }),
    ),
  };
}

describe("canonical temperature monitoring", () => {
  it("selects the eight enabled section inputs and leaves four reserve inputs out", () => {
    expect(monitoredTemperatureChannels(registryFixture())).toEqual([
      ...Array.from({ length: 6 }, (_, i) => `rs485-sdm120:1-S0${i + 1}`),
      "rs485-sdm120:7-S01",
      "rs485-sdm120:7-S02",
    ]);
  });
  it("requires active parents even if a target claims eligibility", () => {
    const fixture = registryFixture();
    fixture.devices[0].lifecycle = "discovery_only";
    expect(monitoredTemperatureChannels(fixture)).toEqual(["rs485-sdm120:7-S01", "rs485-sdm120:7-S02"]);
  });
  it.each(["disabled", "reserve", "retired"])("excludes %s targets", (lifecycle) => {
    const fixture = registryFixture();
    fixture.targets[0].lifecycle = lifecycle;
    expect(monitoredTemperatureChannels(fixture)).not.toContain("rs485-sdm120:1-S01");
  });
  it("rejects cross-bus identities, ineligible inputs and non-read operations", () => {
    const fixture = registryFixture();
    fixture.targets[0].telemetry_channel_id = "another-bus:1-S01";
    fixture.targets[1].function = 6;
    fixture.targets[2].poll_eligible = false;
    expect(monitoredTemperatureChannels(fixture)).toHaveLength(5);
    fixture.buses[0].read_only = false;
    expect(monitoredTemperatureChannels(fixture)).toEqual([]);
  });
  it("continues to select canonical legacy channels", () => {
    const fixture = registryFixture();
    fixture.devices = [
      {
        device_id: "xjp60d-106",
        bus_id: "rs485-sdm120",
        unit_id: 106,
        device_family: "xjp60d",
        lifecycle: "active",
      },
    ];
    fixture.targets = [
      {
        ...fixture.targets[0],
        device_id: "xjp60d-106",
        target_id: "xjp60d:106-03",
        telemetry_channel_id: "106-03",
      },
    ];
    expect(monitoredTemperatureChannels(fixture)).toEqual(["106-03"]);
  });
  it("fails closed for missing, orphaned or duplicated registry identities", () => {
    expect(() => monitoredTemperatureChannels({ active_points: ["106-03"] })).toThrow();
    const fixture = registryFixture();
    fixture.devices = [];
    expect(() => monitoredTemperatureChannels(fixture)).toThrow();
    const duplicate = registryFixture();
    duplicate.targets.push(duplicate.targets[0]);
    expect(() => monitoredTemperatureChannels(duplicate)).toThrow();
  });
});
