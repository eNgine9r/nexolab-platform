import {
  ENERGY_METERS,
  ENERGY_METRICS,
  energyMeterSupportsMetric,
  type EnergyMetricId,
} from "./energy-telemetry";

export interface EnergySeriesSelection {
  unitId: number;
  metric: EnergyMetricId;
}

export function energySeriesSelectionKey(series: EnergySeriesSelection): string {
  return `${series.unitId}:${series.metric}`;
}

export function normalizeEnergySeriesSelection(
  selected: readonly EnergySeriesSelection[],
): EnergySeriesSelection[] {
  const keys = new Set(selected.map(energySeriesSelectionKey));
  return ENERGY_METERS.flatMap((meter) =>
    ENERGY_METRICS.filter(
      (metric) =>
        energyMeterSupportsMetric(meter, metric.id) &&
        keys.has(energySeriesSelectionKey({ unitId: meter.unitId, metric: metric.id })),
    ).map((metric) => ({ unitId: meter.unitId, metric: metric.id })),
  );
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
