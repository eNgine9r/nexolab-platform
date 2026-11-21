import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import {
  EMBRACO_PROVISIONAL_UNIT,
  buildEmbracoOperatorCelsiusScene,
  buildEmbracoProbeRawScene,
  buildEmbracoTemperatureScene,
} from "./controller-chart";
import { EMBRACO_METRICS } from "./controller-monitoring";

function sample(quality: TelemetrySample["quality"], value: number | null): TelemetrySample {
  return {
    event_id: `cabinet-${quality}-${String(value)}`,
    node_id: "edge-01",
    captured_at: "2026-08-28T18:00:00.000Z",
    metric: EMBRACO_METRICS.cabinet,
    value,
    unit: "degC",
    quality,
    source: "embraco-sync",
    equipment_id: "EMBRACO-2",
    channel_id: "2-cabinet-temperature",
    alarm: null,
    raw_value: value,
    raw_status: null,
  };
}

describe("buildEmbracoTemperatureScene", () => {
  const range = {
    from: new Date("2026-08-28T17:00:00.000Z"),
    to: new Date("2026-08-28T18:00:00.000Z"),
  };

  it("does not create a chart series from unverified raw temperature samples", () => {
    const history = new Map([[EMBRACO_METRICS.cabinet, [sample("unknown", null)]]]);

    expect(buildEmbracoTemperatureScene(history, range, true).series).toEqual([]);
  });

  it("keeps the series when at least one verified engineering value exists", () => {
    const history = new Map([[EMBRACO_METRICS.cabinet, [sample("unknown", null), sample("valid", 4.2)]]]);

    expect(buildEmbracoTemperatureScene(history, range, true).series).toHaveLength(1);
  });

  it("uses the canonical 240-point policy while preserving extrema", () => {
    const start = range.from.getTime();
    const samples = Array.from({ length: 300 }, (_, index): TelemetrySample => ({
      ...sample("valid", index === 140 ? -50 : index === 160 ? 100 : 4 + (index % 5) / 10),
      event_id: `cabinet-${index}`,
      captured_at: new Date(start + index * 5_000).toISOString(),
    }));
    const history = new Map([[EMBRACO_METRICS.cabinet, samples]]);
    const points = buildEmbracoTemperatureScene(history, range, true).series[0]?.segments.flatMap(
      (segment) => segment.points,
    );

    expect(points).toHaveLength(240);
    expect(points?.some((point) => point.value === -50)).toBe(true);
    expect(points?.some((point) => point.value === 100)).toBe(true);
  });
});

describe("buildEmbracoProbeRawScene", () => {
  const range = {
    from: new Date("2026-11-19T13:00:00.000Z"),
    to: new Date("2026-11-19T13:05:00.000Z"),
  };
  const at = (
    metric: string,
    raw_value: number | null,
    quality: TelemetrySample["quality"] = "unknown",
  ): TelemetrySample => ({
    ...sample(quality, null),
    metric,
    raw_value,
    event_id: `${metric}-${raw_value}`,
  });

  it("shows both read-only raw probe traces as signed register values without claiming Celsius", () => {
    const scene = buildEmbracoProbeRawScene(
      new Map([
        [EMBRACO_METRICS.cabinet, [at(EMBRACO_METRICS.cabinet, 65485)]],
        [EMBRACO_METRICS.evaporator, [at(EMBRACO_METRICS.evaporator, 65418)]],
      ]),
      range,
      true,
    );

    expect(scene.series.map((item) => item.name)).toEqual([
      "Температура в об’ємі · raw",
      "Датчик відтайки · raw",
    ]);
    expect(scene.series.map((item) => item.identity.nativeUnit)).toEqual(["raw", "raw"]);
    expect(scene.series.map((item) => item.segments[0]?.points[0]?.value)).toEqual([-51, -118]);
    expect(scene.series.map((item) => item.displayPrecision)).toEqual([0, 0]);
    expect(scene.series.map((item) => item.identity.channelId.endsWith(":raw"))).toEqual([true, true]);
  });

  it("fails closed for missing register samples, errors, and out-of-range register values", () => {
    const scene = buildEmbracoProbeRawScene(
      new Map([
        [
          EMBRACO_METRICS.cabinet,
          [
            at(EMBRACO_METRICS.cabinet, null),
            at(EMBRACO_METRICS.cabinet, 12, "communication_error"),
            at(EMBRACO_METRICS.cabinet, -2),
            at(EMBRACO_METRICS.cabinet, 65536),
          ],
        ],
        [EMBRACO_METRICS.evaporator, [at(EMBRACO_METRICS.evaporator, null)]],
      ]),
      range,
      true,
    );
    expect(scene.series).toEqual([]);
  });

  it("preserves the unverified Celsius state in the original samples", () => {
    const unverified = at(EMBRACO_METRICS.cabinet, 65485);
    const input = new Map([[EMBRACO_METRICS.cabinet, [unverified]]]);
    buildEmbracoProbeRawScene(input, range, true);
    expect(unverified.value).toBeNull();
    expect(unverified.quality).toBe("unknown");
    expect(buildEmbracoTemperatureScene(input, range, true).series).toEqual([]);
  });
});

describe("buildEmbracoOperatorCelsiusScene", () => {
  const range = { from: new Date("2026-11-19T15:00:00Z"), to: new Date("2026-11-19T15:05:00Z") };
  const input = (
    metric: string,
    raw_value: number | null,
    quality: TelemetrySample["quality"] = "unknown",
  ): TelemetrySample => ({
    ...sample(quality, null),
    event_id: `operator-${metric}-${raw_value}`,
    equipment_id: "EMBRACO-2",
    source: "embraco-sync",
    metric,
    raw_value,
    channel_id: metric === EMBRACO_METRICS.evaporator ? "2-evaporator-temperature" : "2-cabinet-temperature",
  });

  it("draws operator-interpreted cabinet and defrost temperatures in degC without changing source", () => {
    const cabinet = input(EMBRACO_METRICS.cabinet, 42);
    const defrost = input(EMBRACO_METRICS.evaporator, 65510);
    const scene = buildEmbracoOperatorCelsiusScene(
      new Map([
        [EMBRACO_METRICS.cabinet, [cabinet]],
        [EMBRACO_METRICS.evaporator, [defrost]],
      ]),
      range,
      true,
      "EMBRACO-2",
    );
    expect(scene.series.map((series) => series.name)).toEqual([
      "Температура в об’ємі · попередня шкала",
      "Датчик відтайки · попередня шкала",
    ]);
    // Provisional estimates never share the calibrated °C axis.
    expect(scene.series.map((series) => series.identity.nativeUnit)).toEqual([
      EMBRACO_PROVISIONAL_UNIT,
      EMBRACO_PROVISIONAL_UNIT,
    ]);
    expect(scene.series.map((series) => series.displayPrecision)).toEqual([2, 2]);
    expect(scene.series.map((series) => series.segments[0]?.points[0]?.value)).toEqual([0.42, -0.26]);
    expect(cabinet.quality).toBe("unknown");
    expect(cabinet.value).toBeNull();
    expect(defrost.value).toBeNull();
  });

  it("fails closed on other binding identities and bad-quality data", () => {
    const wrong = input(EMBRACO_METRICS.cabinet, 42);
    const error = input(EMBRACO_METRICS.evaporator, 65510, "communication_error");
    const history = new Map([
      [EMBRACO_METRICS.cabinet, [wrong]],
      [EMBRACO_METRICS.evaporator, [error]],
    ]);
    expect(buildEmbracoOperatorCelsiusScene(history, range, true, "EMBRACO-96").series).toEqual([]);
    expect(buildEmbracoOperatorCelsiusScene(history, range, true, "EMBRACO-2").series).toHaveLength(1);
    expect(
      buildEmbracoOperatorCelsiusScene(
        new Map([[EMBRACO_METRICS.cabinet, [{ ...wrong, equipment_id: "EMBRACO-96" }]]]),
        range,
        true,
        "EMBRACO-2",
      ).series,
    ).toEqual([]);
  });

  it("retains valid source engineering value rather than overriding it with operator estimate", () => {
    const valid = { ...input(EMBRACO_METRICS.cabinet, 42, "valid"), value: 3.7 };
    const scene = buildEmbracoOperatorCelsiusScene(
      new Map([[EMBRACO_METRICS.cabinet, [valid]]]),
      range,
      true,
      "EMBRACO-2",
    );
    expect(scene.series[0]?.segments[0]?.points[0]?.value).toBe(3.7);
    expect(scene.series[0]?.identity.nativeUnit).toBe("°C");
    expect(scene.series[0]?.name).toBe("Температура в об’ємі");
  });

  it("breaks the operator line across a communication error instead of joining it", () => {
    const at = (iso: string, raw: number | null, quality: TelemetrySample["quality"] = "unknown") => ({
      ...input(EMBRACO_METRICS.cabinet, raw, quality),
      event_id: `cab-${iso}`,
      captured_at: iso,
    });
    const scene = buildEmbracoOperatorCelsiusScene(
      new Map([
        [
          EMBRACO_METRICS.cabinet,
          [
            at("2026-11-19T15:00:00Z", 40),
            at("2026-11-19T15:00:05Z", 41),
            at("2026-11-19T15:00:10Z", null, "communication_error"),
            at("2026-11-19T15:00:15Z", 42),
            at("2026-11-19T15:00:20Z", 43),
          ],
        ],
      ]),
      range,
      true,
      "EMBRACO-2",
    );
    expect(scene.series).toHaveLength(1);
    expect(scene.series[0]?.segments).toHaveLength(2);
    expect(scene.series[0]?.segments[1]?.precedingBreak?.reason).toBe("invalid_quality");
  });
});

describe("buildEmbracoProbeRawScene continuity", () => {
  it("breaks the raw line across a communication error", () => {
    const range = { from: new Date("2026-11-19T15:00:00Z"), to: new Date("2026-11-19T15:05:00Z") };
    const at = (iso: string, raw: number | null, quality: TelemetrySample["quality"] = "unknown") => ({
      ...sample(quality, null),
      raw_value: raw,
      event_id: `raw-${iso}`,
      captured_at: iso,
    });
    const scene = buildEmbracoProbeRawScene(
      new Map([
        [
          EMBRACO_METRICS.cabinet,
          [
            at("2026-11-19T15:00:00Z", 40),
            at("2026-11-19T15:00:05Z", 41),
            at("2026-11-19T15:00:10Z", null, "communication_error"),
            at("2026-11-19T15:00:15Z", 42),
          ],
        ],
      ]),
      range,
      true,
    );
    expect(scene.series[0]?.segments).toHaveLength(2);
  });
});

describe("Embraco setpoint styling", () => {
  it("draws the setpoint dashed", () => {
    const range = { from: new Date("2026-08-28T17:00:00.000Z"), to: new Date("2026-08-28T18:00:00.000Z") };
    const setpoint = { ...sample("valid", 4), metric: EMBRACO_METRICS.setpoint, channel_id: "2-setpoint" };
    const scene = buildEmbracoTemperatureScene(
      new Map([[EMBRACO_METRICS.setpoint, [setpoint]]]),
      range,
      true,
    );
    expect(scene.series[0]?.name).toBe("Уставка");
    expect(scene.series[0]?.dashStyle).toBe("dashed");
  });
});
