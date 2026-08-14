import { describe, expect, it } from "vitest";

import { chartSeriesKey, type ChartSeriesIdentity } from "./domain";
import { createBenchmarkScene } from "./fixtures";
import {
  buildChartYAxisModel,
  chartYAxisId,
  groupCompatibleChartUnits,
  partitionChartSeriesByAxisBudget,
} from "./units";

function identity(channelId: string, metric: string, nativeUnit: string): ChartSeriesIdentity {
  return { nodeId: "edge", equipmentId: "equipment", channelId, metric, nativeUnit };
}

function mixedSeries(definitions: Array<{ channelId: string; metric: string; unit: string }>) {
  const scene = createBenchmarkScene(definitions.length);
  return scene.series.map((series, index) => ({
    ...series,
    identity: {
      ...series.identity,
      equipmentId: "meter-01",
      channelId: definitions[index].channelId,
      metric: definitions[index].metric,
      nativeUnit: definitions[index].unit,
    },
  }));
}

describe("compatible chart unit grouping", () => {
  it("groups identical temperature units deterministically", () => {
    const groups = groupCompatibleChartUnits([
      identity("b", "temperature.probe", "°C"),
      identity("a", "temperature.probe", "°C"),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0].series.map((item) => item.channelId)).toEqual(["a", "b"]);
  });

  it("separates incompatible physical quantities", () => {
    const groups = groupCompatibleChartUnits([
      identity("temperature", "temperature.probe", "°C"),
      identity("pressure", "pressure", "kPa"),
      identity("voltage", "voltage", "V"),
      identity("current", "current", "A"),
    ]);
    expect(groups.map((group) => group.physicalQuantity).sort()).toEqual([
      "current",
      "pressure",
      "temperature",
      "voltage",
    ]);
  });

  it("does not mix cumulative energy with instantaneous active power", () => {
    const groups = groupCompatibleChartUnits([
      identity("power", "active_power", "kW"),
      identity("energy", "active_energy", "kWh"),
    ]);
    expect(groups).toHaveLength(2);
    expect(groups.map((group) => group.physicalQuantity)).toContain("active_power");
    expect(groups.map((group) => group.physicalQuantity)).toContain("cumulative_energy");
  });

  it("does not perform implicit conversion between compatible quantities", () => {
    const groups = groupCompatibleChartUnits([
      identity("celsius", "temperature.probe", "°C"),
      identity("fahrenheit", "temperature.probe", "°F"),
    ]);
    expect(groups).toHaveLength(2);
  });

  it("keeps deterministic V/A/W axis identities across hide, show and solo", () => {
    const series = mixedSeries([
      { channelId: "voltage", metric: "electrical.voltage", unit: "V" },
      { channelId: "current", metric: "electrical.current", unit: "A" },
      { channelId: "power", metric: "electrical.active_power", unit: "W" },
    ]);
    const initial = buildChartYAxisModel(series);
    const initialAxisIds = initial.allAxes.map((axis) => axis.id);

    for (const item of series) {
      expect(initial.axisIdBySeriesKey.get(chartSeriesKey(item.identity))).toBe(chartYAxisId(item.identity));
    }

    const hidden = buildChartYAxisModel(series.map((item, index) => ({ ...item, visible: index !== 1 })));
    expect(hidden.allAxes.map((axis) => axis.id)).toEqual(initialAxisIds);
    expect(hidden.visibleAxes.map((axis) => axis.id)).not.toContain(chartYAxisId(series[1].identity));

    const restored = buildChartYAxisModel(series.map((item) => ({ ...item, visible: true })));
    expect(restored.visibleAxes.map((axis) => axis.id)).toEqual(initial.visibleAxes.map((axis) => axis.id));

    const solo = buildChartYAxisModel(series.map((item, index) => ({ ...item, visible: index === 2 })));
    expect(solo.visibleAxes.map((axis) => axis.id)).toEqual([chartYAxisId(series[2].identity)]);
  });

  it("partitions more than five axes without mixing equipment-scene axis budgets", () => {
    const series = mixedSeries([
      { channelId: "voltage", metric: "electrical.voltage", unit: "V" },
      { channelId: "current", metric: "electrical.current", unit: "A" },
      { channelId: "power", metric: "electrical.active_power", unit: "W" },
      { channelId: "frequency", metric: "electrical.frequency", unit: "Hz" },
      { channelId: "energy", metric: "electrical.energy", unit: "kWh" },
      { channelId: "factor", metric: "electrical.power_factor", unit: "PF" },
    ]);

    const partitions = partitionChartSeriesByAxisBudget(series);
    expect(partitions).toHaveLength(2);
    expect(partitions.map((partition) => buildChartYAxisModel(partition).allAxes.length)).toEqual([5, 1]);
    expect(partitions.flatMap((partition) => partition)).toHaveLength(series.length);
  });
});
