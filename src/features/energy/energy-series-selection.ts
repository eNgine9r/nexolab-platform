import {
  ENERGY_METERS,
  ENERGY_METRICS,
  energyMeterSupportsMetric,
  type EnergyMetricId,
} from "./energy-telemetry";
import { energyMeterIdentity, type CommissionedEnergyMeter } from "./energy-commissioned-meters";

export interface EnergySeriesSelection {
  unitId: number;
  metric: EnergyMetricId;
  /** Full node/equipment identity for commissioned meters; legacy pairs omit it. */
  meterKey?: string;
}

export function energySeriesSelectionKey(series: EnergySeriesSelection): string {
  return `${series.meterKey ?? series.unitId}:${series.metric}`;
}

export function normalizeEnergySeriesSelection(
  selected: readonly EnergySeriesSelection[],
  meters: readonly CommissionedEnergyMeter[] = [],
): EnergySeriesSelection[] {
  const keys = new Set(selected.map(energySeriesSelectionKey));
  const legacy = ENERGY_METERS.flatMap((meter) =>
    ENERGY_METRICS.filter(
      (metric) =>
        energyMeterSupportsMetric(meter, metric.id) &&
        keys.has(energySeriesSelectionKey({ unitId: meter.unitId, metric: metric.id })),
    ).map((metric) => ({ unitId: meter.unitId, metric: metric.id })),
  );
  const scoped = meters.flatMap((meter) => {
    const meterKey = energyMeterIdentity(meter.nodeId, meter.equipmentId);
    return ENERGY_METRICS.filter((metric) => {
      const candidate = { unitId: meter.unitId, metric: metric.id, meterKey };
      return (
        energyMeterSupportsMetric(meter, metric.id) &&
        keys.has(energySeriesSelectionKey(candidate)) &&
        selected.some(
          (item) =>
            item.unitId === meter.unitId &&
            energySeriesSelectionKey(item) === energySeriesSelectionKey(candidate),
        )
      );
    }).map((metric) => ({ unitId: meter.unitId, metric: metric.id, meterKey }));
  });
  return [...legacy, ...scoped];
}

export function energySeriesForMeters(
  unitIds: readonly number[],
  metrics: readonly EnergyMetricId[],
): EnergySeriesSelection[] {
  return normalizeEnergySeriesSelection(
    unitIds.flatMap((unitId) => metrics.map((metric) => ({ unitId, metric }))),
  );
}

export function energySeriesDisplayUnit(metric: EnergyMetricId): string {
  const unit = ENERGY_METRICS.find((item) => item.id === metric)?.expectedUnit ?? "";
  return unit === "degC" ? "°C" : unit === "ratio" ? "PF" : unit;
}
