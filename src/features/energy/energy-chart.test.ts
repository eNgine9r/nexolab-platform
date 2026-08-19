import { describe, expect, it } from "vitest";

import { chartSeriesKey } from "@/features/charts/domain";
import { markEnergyHistorySegmentStart } from "@/features/energy/energy-history-segment";
import type { TelemetrySample } from "@/lib/telemetry/types";

import { buildEnergyChartScene } from "./energy-chart";

function sample(
  eventId: string,
  capturedAt: string,
  overrides: Partial<TelemetrySample> = {},
): TelemetrySample {
  return {
    event_id: eventId,
    node_id: "edge-01",
    captured_at: capturedAt,
    metric: "electrical.power.active",
    value: 420,
    unit: "W",
    quality: "valid",
    source: "modbus",
    equipment_id: "LE01MP-200",
    channel_id: "200-active-power",
    alarm: null,
    raw_value: 420,
    raw_status: 0,
    received_at: capturedAt,
    ...overrides,
  };
}

describe("Energy canonical chart scene", () => {
  it("preserves explicit history gaps as independent canonical segments", () => {
    const first = sample("first", "2026-08-18T23:55:00.000Z");
    const second = markEnergyHistorySegmentStart(
      sample("second", "2026-08-19T00:05:00.000Z", { value: 510 }),
    );
    const scene = buildEnergyChartScene({
      samples: [first, second],
      selectedMetric: "electrical.power.active",
      selectedUnitIds: [200],
      status: "live",
      historyWindow: { from: "2026-08-18T23:00:00.000Z", to: "2026-08-19T01:00:00.000Z" },
    });
    expect(scene.xDomain).toEqual({
      fromMs: Date.parse("2026-08-18T23:00:00.000Z"),
      toMs: Date.parse("2026-08-19T01:00:00.000Z"),
    });
    expect(scene.series).toHaveLength(1);
    expect(scene.series[0].segments).toHaveLength(2);
    expect(scene.series[0].segments[1].precedingBreak?.reason).toBe("explicit_gap");
    expect(scene.series[0].segments[1].points[0].value).toBe(510);
    expect(scene.series[0].segments[1].points[0].pinReasons).toContain("segment_boundary");
    expect(scene.series[0].freshness).toBe("live");
    expect(chartSeriesKey(scene.series[0].identity)).toContain("LE01MP-200");
  });

  it("uses canonical energy unit compatibility instead of raw unit spelling", () => {
    const temperature = sample("temp", "2026-08-19T00:05:00.000Z", {
      metric: "temperature.internal",
      value: 31,
      unit: "°C",
      channel_id: "200-internal-temperature",
    });
    const scene = buildEnergyChartScene({
      samples: [temperature],
      selectedMetric: "temperature.internal",
      selectedUnitIds: [200],
      status: "stale",
      historyWindow: null,
    });
    expect(scene.series).toHaveLength(1);
    expect(scene.series[0].identity.nativeUnit).toBe("degC");
    expect(scene.series[0].segments[0].points[0].value).toBe(31);
    expect(scene.series[0].freshness).toBe("stale");
  });

  it("keeps meter/channel identity deterministic and excludes unselected meters", () => {
    const w1 = sample("w1", "2026-08-19T00:05:00.000Z");
    const w2 = sample("w2", "2026-08-19T00:05:01.000Z", {
      equipment_id: "LE01MP-201",
      channel_id: "201-active-power",
    });
    const scene = buildEnergyChartScene({
      samples: [w2, w1],
      selectedMetric: "electrical.power.active",
      selectedUnitIds: [200],
      status: "reconnecting",
      historyWindow: null,
    });
    expect(scene.series.map((series) => series.identity.equipmentId)).toEqual(["LE01MP-200"]);
    expect(scene.series[0].name).toContain("W1");
    expect(scene.series[0].name).toContain("200-active-power");
    expect(scene.series[0].freshness).toBe("reconnecting");
  });
});
