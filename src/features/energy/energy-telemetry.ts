import type { TelemetrySample } from "@/lib/telemetry/types";

export const ENERGY_METERS = [
  { label: "W1", unitId: 200, equipmentId: "LE01MP-200" },
  { label: "W2", unitId: 201, equipmentId: "LE01MP-201" },
  { label: "W3", unitId: 202, equipmentId: "LE01MP-202" },
  { label: "W4", unitId: 203, equipmentId: "LE01MP-203" },
] as const;

export const ENERGY_METRICS = [
  {
    id: "electrical.power.active",
    label: "Активна потужність",
    shortLabel: "P",
    expectedUnit: "W",
    digits: 0,
  },
  {
    id: "electrical.energy.active",
    label: "Накопичена активна енергія",
    shortLabel: "EΣ",
    expectedUnit: "kWh",
    digits: 2,
  },
  {
    id: "electrical.voltage",
    label: "Напруга",
    shortLabel: "U",
    expectedUnit: "V",
    digits: 1,
  },
  {
    id: "electrical.current",
    label: "Струм",
    shortLabel: "I",
    expectedUnit: "A",
    digits: 1,
  },
  {
    id: "electrical.frequency",
    label: "Частота",
    shortLabel: "f",
    expectedUnit: "Hz",
    digits: 1,
  },
  {
    id: "electrical.power.reactive",
    label: "Реактивна потужність",
    shortLabel: "Q",
    expectedUnit: "var",
    digits: 0,
  },
  {
    id: "electrical.power.apparent",
    label: "Повна потужність",
    shortLabel: "S",
    expectedUnit: "VA",
    digits: 0,
  },
  {
    id: "electrical.power_factor",
    label: "Коефіцієнт потужності",
    shortLabel: "PF",
    expectedUnit: "ratio",
    digits: 3,
  },
  {
    id: "temperature.internal",
    label: "Температура лічильника",
    shortLabel: "T",
    expectedUnit: "degC",
    digits: 0,
  },
] as const;

export type EnergyMetricId = (typeof ENERGY_METRICS)[number]["id"];
export type EnergyMeter = (typeof ENERGY_METERS)[number];
export type EnergySampleState =
  "live" | "stale" | "sensor_error" | "communication_error" | "unknown" | "empty";

const METRIC_ORDER = new Map<string, number>(ENERGY_METRICS.map((metric, index) => [metric.id, index]));

function canonicalUnit(unit: string): string {
  const normalized = unit.trim().toLowerCase();
  if (normalized === "°c" || normalized === "degc") return "degc";
  return normalized;
}

function energyMetricDefinition(metric: string) {
  return ENERGY_METRICS.find((definition) => definition.id === metric) ?? null;
}

function hasExpectedEnergyUnit(sample: TelemetrySample): boolean {
  const definition = energyMetricDefinition(sample.metric);
  return definition !== null && canonicalUnit(sample.unit) === canonicalUnit(definition.expectedUnit);
}

function meterByUnitId(unitId: number): EnergyMeter | null {
  return ENERGY_METERS.find((meter) => meter.unitId === unitId) ?? null;
}

export function resolveEnergyMeter(sample: TelemetrySample): EnergyMeter | null {
  const equipmentMatch = sample.equipment_id.match(/^LE01MP-(\d+)$/i);
  if (equipmentMatch) return meterByUnitId(Number(equipmentMatch[1]));

  const channelMatch = sample.channel_id.match(/^(20[0-3])(?:-|$)/);
  if (!channelMatch) return null;
  return meterByUnitId(Number(channelMatch[1]));
}

export function isEnergySample(sample: TelemetrySample): boolean {
  return hasExpectedEnergyUnit(sample) && resolveEnergyMeter(sample) !== null;
}

export function selectLatestEnergySamples(samples: readonly TelemetrySample[]): TelemetrySample[] {
  const latest = new Map<string, TelemetrySample>();

  for (const sample of samples) {
    const meter = resolveEnergyMeter(sample);
    if (!meter || !hasExpectedEnergyUnit(sample)) continue;
    const key = `${meter.unitId}:${sample.metric}`;
    const current = latest.get(key);
    if (!current || Date.parse(current.captured_at) <= Date.parse(sample.captured_at)) {
      latest.set(key, sample);
    }
  }

  return [...latest.values()].sort((left, right) => {
    const leftMeter = resolveEnergyMeter(left)?.unitId ?? Number.MAX_SAFE_INTEGER;
    const rightMeter = resolveEnergyMeter(right)?.unitId ?? Number.MAX_SAFE_INTEGER;
    return (
      leftMeter - rightMeter ||
      (METRIC_ORDER.get(left.metric) ?? Number.MAX_SAFE_INTEGER) -
        (METRIC_ORDER.get(right.metric) ?? Number.MAX_SAFE_INTEGER)
    );
  });
}

export function findEnergySample(
  samples: readonly TelemetrySample[],
  unitId: number,
  metric: EnergyMetricId,
): TelemetrySample | null {
  return (
    selectLatestEnergySamples(samples).find(
      (sample) => resolveEnergyMeter(sample)?.unitId === unitId && sample.metric === metric,
    ) ?? null
  );
}

export function energySampleState(
  sample: TelemetrySample | null,
  now: number = Date.now(),
  staleAfterMs = 30_000,
): EnergySampleState {
  if (!sample) return "empty";
  if (sample.quality === "sensor_error") return "sensor_error";
  if (sample.quality === "communication_error") return "communication_error";
  if (sample.quality === "unknown") return "unknown";
  const capturedAt = Date.parse(sample.captured_at);
  if (!Number.isFinite(capturedAt) || now - capturedAt > staleAfterMs) return "stale";
  return "live";
}

export function formatEnergyValue(sample: TelemetrySample | null): string {
  if (!sample || sample.quality !== "valid" || sample.value === null || !hasExpectedEnergyUnit(sample)) {
    return "—";
  }
  const definition = energyMetricDefinition(sample.metric);
  const digits = definition?.digits ?? 2;
  const value = new Intl.NumberFormat("uk-UA", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(sample.value);
  const unit = canonicalUnit(sample.unit) === "degc" ? "°C" : sample.unit;
  return canonicalUnit(unit) === "ratio" ? value : `${value} ${unit}`;
}

export function formatCapturedAt(sample: TelemetrySample | null): string {
  if (!sample) return "Даних ще немає";
  const capturedAt = Date.parse(sample.captured_at);
  if (!Number.isFinite(capturedAt)) return "Некоректний час";
  return new Intl.DateTimeFormat("uk-UA", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(capturedAt);
}
