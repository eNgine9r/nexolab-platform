import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import {
  isOperatorEmbracoTemperature,
  savedDashboardChannelLabel,
  savedDashboardDisplaySample,
  savedDashboardSeriesLabel,
  savedDashboardSeriesUnit,
} from "./embraco-series";
import type { LiveDashboardItem } from "./types";

const cabinet: LiveDashboardItem = {
  id: "cabinet",
  position: 1,
  channel_ref_id: null,
  node_id: "edge-01",
  equipment_id: "EMBRACO-2",
  channel_id: "2-cabinet-temperature",
  metric: "temperature.cabinet",
  native_unit: "degC",
  visualization: "line",
  color: "#00C6E0",
  display_unit: "degC",
};

const sample: TelemetrySample = {
  event_id: "sample-1",
  node_id: "edge-01",
  equipment_id: "EMBRACO-2",
  channel_id: "2-cabinet-temperature",
  metric: "temperature.cabinet",
  captured_at: "2026-11-19T19:12:20Z",
  value: null,
  raw_value: 65507,
  unit: "degC",
  quality: "unknown",
  source: "embraco-sync",
  alarm: null,
  raw_status: null,
};

describe("operator Embraco saved dashboard display", () => {
  it("shows explicitly operator-derived signed16 Celsius only for exact installed probe", () => {
    expect(savedDashboardSeriesLabel(cabinet)).toBe("Температура в об’ємі");
    expect(savedDashboardChannelLabel(cabinet)).toBe("Температура в об’ємі");
    expect(savedDashboardChannelLabel({ ...cabinet, node_id: "edge-02" })).toBe("2-cabinet-temperature");
    expect(
      savedDashboardChannelLabel({ ...cabinet, channel_id: "106-03", metric: "temperature.probe" }),
    ).toBe("106-03");
    expect(savedDashboardSeriesUnit(cabinet)).toBe("°C");
    expect(isOperatorEmbracoTemperature(cabinet)).toBe(true);
    expect(savedDashboardDisplaySample(cabinet, sample)).toEqual({
      value: -0.29,
      unit: "°C",
      operatorDerived: true,
    });
    expect(sample.value).toBeNull();
    expect(sample.quality).toBe("unknown");
    expect(sample.raw_value).toBe(65507);
  });

  it("shows exact defrost and RPM channels using their independent units", () => {
    const defrost = {
      ...cabinet,
      channel_id: "2-evaporator-temperature",
      metric: "temperature.evaporator",
    };
    const rpm = {
      ...cabinet,
      channel_id: "2-compressor-speed",
      metric: "compressor.speed",
      native_unit: "rpm",
    };
    expect(savedDashboardSeriesLabel(defrost)).toBe("Датчик відтайки");
    expect(
      savedDashboardDisplaySample(defrost, {
        ...sample,
        channel_id: defrost.channel_id,
        metric: defrost.metric,
        raw_value: 65468,
      })?.value,
    ).toBe(-0.68);
    expect(isOperatorEmbracoTemperature(rpm)).toBe(false);
    expect(savedDashboardSeriesLabel(rpm)).toBe("Обороти компресора");
    expect(
      savedDashboardDisplaySample(rpm, {
        ...sample,
        channel_id: rpm.channel_id,
        metric: rpm.metric,
        raw_value: 2198,
        value: 2198,
        unit: "rpm",
        quality: "valid",
      }),
    ).toEqual({ value: 2198, unit: "rpm", operatorDerived: false });
  });

  it("rejects forged scope, noncommissioned channels, missing raw and communication errors", () => {
    expect(savedDashboardSeriesLabel({ ...cabinet, channel_id: "2-evaporator-2-temperature" })).toContain(
      "2-evaporator-2-temperature",
    );
    for (const candidate of [
      { ...cabinet, node_id: "other-node" },
      { ...cabinet, equipment_id: "EMBRACO-3" },
      { ...cabinet, channel_ref_id: "some-registry-row" },
      { ...cabinet, channel_id: "2-evaporator-2-temperature" },
      { ...cabinet, metric: "temperature.ambient" },
    ]) {
      expect(isOperatorEmbracoTemperature(candidate)).toBe(false);
      expect(savedDashboardDisplaySample(candidate, sample)).toBeNull();
    }
    expect(savedDashboardDisplaySample(cabinet, { ...sample, raw_value: null })).toBeNull();
    expect(savedDashboardDisplaySample(cabinet, { ...sample, quality: "communication_error" })).toBeNull();
    expect(savedDashboardDisplaySample(cabinet, { ...sample, raw_value: 65536 })).toBeNull();
    expect(savedDashboardDisplaySample(cabinet, { ...sample, source: "different" })).toBeNull();
  });
});
