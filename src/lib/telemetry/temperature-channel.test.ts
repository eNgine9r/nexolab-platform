import { describe, expect, it } from "vitest";

import { isTemperatureProbeSample } from "./temperature-channel";
import type { TelemetrySample } from "./types";

function sample(overrides: Partial<TelemetrySample> = {}): TelemetrySample {
  return {
    event_id: "event-1",
    node_id: "edge-01",
    captured_at: "2026-07-31T08:00:00Z",
    metric: "temperature.probe",
    value: 4.5,
    unit: "degC",
    quality: "valid",
    source: "dashboard-acceptance",
    equipment_id: "K126",
    channel_id: "126-04",
    alarm: null,
    raw_value: 45,
    raw_status: 0x1100,
    ...overrides,
  };
}

describe("temperature channel classification", () => {
  it("accepts canonical controller inputs regardless of transport source", () => {
    expect(isTemperatureProbeSample(sample())).toBe(true);
    expect(isTemperatureProbeSample(sample({ source: "dixell-xjp60d", channel_id: "110-06" }))).toBe(true);
  });

  it("rejects non-temperature and non-controller channels", () => {
    expect(isTemperatureProbeSample(sample({ metric: "electrical.power.active" }))).toBe(false);
    expect(isTemperatureProbeSample(sample({ channel_id: "200-active-power" }))).toBe(false);
  });
});
