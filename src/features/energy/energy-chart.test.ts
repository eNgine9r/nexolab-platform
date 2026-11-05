import { describe, expect, it } from "vitest";

import { chartSeriesKey } from "@/features/charts/domain";
import { buildChartYAxisModel, partitionChartSeriesByAxisBudget } from "@/features/charts/units";
import { ENERGY_METRICS } from "./energy-telemetry";
import { energyMeterIdentity, type CommissionedEnergyMeter } from "./energy-commissioned-meters";
import { normalizeEnergySeriesSelection } from "./energy-series-selection";
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
  it("selects two commissioned meters with the same Unit independently of legacy history", () => {
    const meters: CommissionedEnergyMeter[] = ["0123456789abcdef", "fedcba9876543210"].map((id) => ({
      nodeId: "edge-01",
      busId: `commissioning-${id}`,
      unitId: 1,
      equipmentId: `SDM120M:commissioning-${id}:1`,
      label: id,
      modelLabel: "SDM",
      family: "sdm120",
    }));
    const samples = [...meters.map((meter) => meter.equipmentId), "SDM120M-1"].map((id, index) =>
      sample(id, "2026-08-19T00:05:00Z", {
        equipment_id: id,
        channel_id: "1-active-power",
        value: index + 1,
      }),
    );
    const keys = meters.map((meter) => energyMeterIdentity(meter.nodeId, meter.equipmentId));
    expect(
      normalizeEnergySeriesSelection(
        [
          { unitId: 1, meterKey: keys[0], metric: "electrical.power.active" },
          { unitId: 99, meterKey: keys[1], metric: "electrical.power.active" },
          { unitId: 1, metric: "electrical.power.active" },
        ],
        meters,
      ),
    ).toEqual([
      { unitId: 1, metric: "electrical.power.active" },
      { unitId: 1, meterKey: keys[0], metric: "electrical.power.active" },
    ]);
    const scene = buildEnergyChartScene({
      samples,
      meters,
      selectedMeterKeys: keys,
      selectedUnitIds: [1],
      selectedMetric: "electrical.power.active",
      status: "live",
      historyWindow: null,
    });
    expect(scene.series).toHaveLength(3);
    expect(new Set(scene.series.map((item) => chartSeriesKey(item.identity))).size).toBe(3);
    expect(new Set(scene.series.map((item) => item.colorToken)).size).toBe(3);
    const selected = buildEnergyChartScene({
      samples,
      meters,
      selectedMeterKeys: keys,
      selectedUnitIds: [1],
      selectedPairs: [{ unitId: 1, meterKey: keys[0], metric: "electrical.power.active" }],
      selectedMetric: "electrical.power.active",
      status: "live",
      historyWindow: null,
    });
    expect(selected.series.map((item) => item.identity.equipmentId)).toEqual([meters[0].equipmentId]);
    expect(
      buildEnergyChartScene({
        samples,
        meters,
        selectedUnitIds: [1],
        selectedMetric: "electrical.power.active",
        status: "live",
        historyWindow: null,
      }).series.map((item) => item.identity.equipmentId),
    ).toEqual(["SDM120M-1"]);
  });
  it("keeps P/U/I on independent axes with distinct stable colors and exact pair selection", () => {
    const samples = ["electrical.power.active", "electrical.voltage", "electrical.current"].map((id) => {
      const metric = ENERGY_METRICS.find((item) => item.id === id)!;
      return sample(id, "2026-08-19T00:05:00Z", {
        metric: id,
        unit: metric.expectedUnit,
        channel_id: `200-${id}`,
      });
    });
    const options = {
      samples,
      selectedMetrics: ["electrical.power.active", "electrical.voltage", "electrical.current"] as const,
      selectedUnitIds: [200],
      status: "live" as const,
      historyWindow: null,
    };
    const scene = buildEnergyChartScene(options);
    expect(scene.series).toHaveLength(3);
    expect(new Set(scene.series.map((item) => item.colorToken)).size).toBe(3);
    expect(
      buildChartYAxisModel(scene.series)
        .visibleAxes.map((axis) => axis.nativeUnit)
        .sort(),
    ).toEqual(["A", "V", "W"]);
    const subset = buildEnergyChartScene({
      ...options,
      selectedPairs: [{ unitId: 200, metric: "electrical.current" }],
    });
    expect(subset.series).toHaveLength(1);
    expect(subset.series[0].colorToken).toBe(
      scene.series.find((item) => item.identity.metric === "electrical.current")!.colorToken,
    );
  });

  it("partitions nine native quantities without mixing node or counter identity", () => {
    const samples = ENERGY_METRICS.map((metric) =>
      sample(metric.id, "2026-08-19T00:05:00Z", {
        metric: metric.id,
        unit: metric.expectedUnit,
        channel_id: `200-${metric.id}`,
      }),
    );
    samples.push({ ...samples[0], node_id: "edge-other", event_id: "other-node" });
    const scene = buildEnergyChartScene({
      samples,
      selectedMetrics: ENERGY_METRICS.map((metric) => metric.id),
      selectedUnitIds: [200],
      status: "live",
      historyWindow: null,
    });
    expect(scene.series).toHaveLength(10);
    const panels = partitionChartSeriesByAxisBudget(scene.series);
    expect(panels).toHaveLength(2);
    expect(panels.every((series) => buildChartYAxisModel(series).visibleAxes.length <= 5)).toBe(true);
    expect(new Set(scene.series.map((item) => chartSeriesKey(item.identity))).size).toBe(10);
    expect(
      scene.series.find((item) => item.identity.metric === "electrical.energy.active")?.semanticMode,
    ).toBe("cumulative_counter");
  });

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
