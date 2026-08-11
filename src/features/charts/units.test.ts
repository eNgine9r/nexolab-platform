import { describe, expect, it } from "vitest";

import type { ChartSeriesIdentity } from "./domain";
import { groupCompatibleChartUnits } from "./units";

function identity(channelId: string, metric: string, nativeUnit: string): ChartSeriesIdentity {
  return { nodeId: "edge", equipmentId: "equipment", channelId, metric, nativeUnit };
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
});
