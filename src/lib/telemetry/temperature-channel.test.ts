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
    expect(isTemperatureProbeSample(sample({ channel_id: "96-01" }))).toBe(true);
    expect(isTemperatureProbeSample(sample({ source: "dixell-xjp60d", channel_id: "110-06" }))).toBe(true);
  });

  it.each(["1-01", "7-02", "9-06", "10-01", "247-06"])("accepts commissioned input %s", (channel_id) => {
    expect(isTemperatureProbeSample(sample({ channel_id }))).toBe(true);
  });

  it.each(["0-01", "248-01", "999-01", "1-00", "1-07", "1-001", "01-01"])(
    "rejects invalid identity %s",
    (channel_id) => {
      expect(isTemperatureProbeSample(sample({ channel_id }))).toBe(false);
    },
  );

  it("recognizes commissioned sections with their exact bus and module identity", () => {
    for (const unit of [1, 7, 49]) {
      for (let section = 1; section <= 6; section += 1) {
        expect(
          isTemperatureProbeSample(
            sample({
              equipment_id: `XJP60D-S:rs485-sdm120:${unit}`,
              channel_id: `rs485-sdm120:${unit}-S0${section}`,
            }),
          ),
        ).toBe(true);
      }
    }
    expect(
      isTemperatureProbeSample(
        sample({
          equipment_id: "XJP60D-S:other:1",
          channel_id: "rs485-sdm120:1-S01",
        }),
      ),
    ).toBe(false);
    expect(
      isTemperatureProbeSample(
        sample({
          equipment_id: "XJP60D-S:rs485-sdm120:248",
          channel_id: "rs485-sdm120:248-S01",
        }),
      ),
    ).toBe(false);
  });

  it("rejects non-temperature and non-controller channels", () => {
    expect(isTemperatureProbeSample(sample({ metric: "electrical.power.active" }))).toBe(false);

    expect(isTemperatureProbeSample(sample({ channel_id: "1096-01" }))).toBe(false);
    expect(isTemperatureProbeSample(sample({ channel_id: "200-active-power" }))).toBe(false);
  });
});
