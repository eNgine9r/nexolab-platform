import { chartSeriesKey, type ChartSeriesIdentity } from "./domain";

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
