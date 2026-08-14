import { chartSeriesKey, type ChartSeries, type ChartSeriesIdentity } from "./domain";

export type ChartPhysicalQuantity =
  | "temperature"
  | "humidity"
  | "pressure"
  | "voltage"
  | "current"
  | "active_power"
  | "frequency"
  | "power_factor"
  | "cumulative_energy"
  | "unknown";

export interface ChartUnitGroup {
  id: string;
  nativeUnit: string;
  physicalQuantity: ChartPhysicalQuantity;
  series: readonly ChartSeriesIdentity[];
}

export interface ApprovedChartUnitConversionContract {
  id: string;
  fromNativeUnit: string;
  toNativeUnit: string;
  factor: number;
  offset: number;
  approved: true;
}

export const MAX_CHART_Y_AXES = 5;
export const CHART_Y_AXIS_OFFSET_PX = 56;

export interface ChartYAxis {
  id: string;
  nativeUnit: string;
  physicalQuantity: ChartPhysicalQuantity;
  order: number;
  position: "left" | "right";
  offset: number;
  seriesKeys: readonly string[];
}

export interface ChartYAxisModel {
  allAxes: readonly ChartYAxis[];
  visibleAxes: readonly ChartYAxis[];
  axisIdBySeriesKey: ReadonlyMap<string, string>;
}

const UNIT_QUANTITIES: Readonly<Record<string, ChartPhysicalQuantity>> = {
  "°C": "temperature",
  "°F": "temperature",
  "%RH": "humidity",
  Pa: "pressure",
  kPa: "pressure",
  bar: "pressure",
  V: "voltage",
  A: "current",
  W: "active_power",
  kW: "active_power",
  Hz: "frequency",
  PF: "power_factor",
  kWh: "cumulative_energy",
  Wh: "cumulative_energy",
};

function quantity(identity: ChartSeriesIdentity): ChartPhysicalQuantity {
  const unitQuantity = UNIT_QUANTITIES[identity.nativeUnit];
  if (unitQuantity) return unitQuantity;
  const metric = identity.metric.toLowerCase();
  if (metric.includes("temperature")) return "temperature";
  if (metric.includes("humidity")) return "humidity";
  if (metric.includes("pressure")) return "pressure";
  if (metric.includes("voltage")) return "voltage";
  if (metric.includes("current")) return "current";
  if (metric.includes("frequency")) return "frequency";
  if (metric.includes("power_factor")) return "power_factor";
  if (metric.includes("energy")) return "cumulative_energy";
  if (metric.includes("power")) return "active_power";
  return "unknown";
}

function groupKey(identity: ChartSeriesIdentity): string {
  const physicalQuantity = quantity(identity);
  const conservativeMetric = physicalQuantity === "unknown" ? `:${identity.metric}` : "";
  return `${physicalQuantity}:${identity.nativeUnit}${conservativeMetric}`;
}

export function chartYAxisId(identity: ChartSeriesIdentity): string {
  return groupKey(identity);
}

export function groupCompatibleChartUnits(identities: readonly ChartSeriesIdentity[]): ChartUnitGroup[] {
  const groups = new Map<string, ChartSeriesIdentity[]>();
  for (const identity of identities) {
    const key = groupKey(identity);
    groups.set(key, [...(groups.get(key) ?? []), identity]);
  }
  return [...groups.entries()]
    .sort(([left], [right]) => left.localeCompare(right, "en"))
    .map(([id, series]) => ({
      id,
      nativeUnit: series[0].nativeUnit,
      physicalQuantity: quantity(series[0]),
      series: [...series].sort((left, right) => chartSeriesKey(left).localeCompare(chartSeriesKey(right))),
    }));
}

export function buildChartYAxisModel(series: readonly ChartSeries[]): ChartYAxisModel {
  const groups = groupCompatibleChartUnits(series.map((item) => item.identity));
  const visibleSeriesKeys = new Set(
    series.filter((item) => item.visible).map((item) => chartSeriesKey(item.identity)),
  );
  const axisIdBySeriesKey = new Map<string, string>();
  const allAxes = groups.map((group, order): ChartYAxis => {
    const seriesKeys = group.series.map(chartSeriesKey);
    for (const seriesKey of seriesKeys) axisIdBySeriesKey.set(seriesKey, group.id);
    return {
      id: group.id,
      nativeUnit: group.nativeUnit,
      physicalQuantity: group.physicalQuantity,
      order,
      position: order % 2 === 0 ? "left" : "right",
      offset: Math.floor(order / 2) * CHART_Y_AXIS_OFFSET_PX,
      seriesKeys,
    };
  });
  const visibleAxes = allAxes.filter((axis) => axis.seriesKeys.some((key) => visibleSeriesKeys.has(key)));
  if (visibleAxes.length > MAX_CHART_Y_AXES) {
    throw new Error(`Chart scene exceeds the ${MAX_CHART_Y_AXES}-axis readability limit`);
  }
  return { allAxes, visibleAxes, axisIdBySeriesKey };
}

export function partitionChartSeriesByAxisBudget(
  series: readonly ChartSeries[],
  maximumAxes = MAX_CHART_Y_AXES,
): ChartSeries[][] {
  if (!Number.isInteger(maximumAxes) || maximumAxes < 1) {
    throw new Error("Chart axis budget must be a positive integer");
  }
  const groups = groupCompatibleChartUnits(series.map((item) => item.identity));
  if (groups.length <= maximumAxes) return [[...series]];

  const partitions: ChartSeries[][] = [];
  for (let start = 0; start < groups.length; start += maximumAxes) {
    const axisIds = new Set(groups.slice(start, start + maximumAxes).map((group) => group.id));
    partitions.push(series.filter((item) => axisIds.has(chartYAxisId(item.identity))));
  }
  return partitions.filter((partition) => partition.length > 0);
}
