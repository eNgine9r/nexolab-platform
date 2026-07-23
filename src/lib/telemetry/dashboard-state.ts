import type { TelemetryAlarm, TelemetryConnectionState, TelemetryQuality, TelemetrySample } from "./types";

export type DashboardTelemetryStatus =
  | "demo"
  | "connecting"
  | "live"
  | "reconnecting"
  | "stale"
  | "offline"
  | "error";

export interface DashboardTelemetryStore {
  samples: Record<string, TelemetrySample>;
  seenEventIds: string[];
  rejectedFutureSamples: number;
}

export interface DashboardTelemetryView {
  status: DashboardTelemetryStatus;
  samples: TelemetrySample[];
  freshSamples: TelemetrySample[];
  lastCapturedAt: string | null;
  ageMs: number | null;
  rejectedFutureSamples: number;
}

export interface MergeTelemetryOptions {
  now?: Date | number;
  maxFutureSkewMs?: number;
  maxSeenEventIds?: number;
}

export interface DeriveTelemetryOptions {
  now?: Date | number;
  staleAfterMs?: number;
  hasLoadedSnapshot: boolean;
  connectionState: TelemetryConnectionState;
  error: Error | null;
}

export interface DashboardKpiValue {
  label: string;
  value: string;
  detail: string;
  trend: string;
  tone: "blue" | "cyan" | "green" | "red" | "amber";
  icon: "network" | "signal" | "session" | "alarm" | "energy" | "temperature";
  badge: string;
  badgeTone: "demo" | "live" | "stale" | "offline" | "error";
}

type UsableTelemetrySample = TelemetrySample & {
  quality: "valid";
  value: number;
};

const DEFAULT_MAX_FUTURE_SKEW_MS = 30_000;
const DEFAULT_MAX_SEEN_EVENT_IDS = 10_000;
const DEFAULT_STALE_AFTER_MS = 30_000;
const EXPECTED_RECORDS_PER_CYCLE = 34;
const PRODUCTION_TEMPERATURE_CHANNELS = new Set(["106-03", "106-04"]);
const PRODUCTION_ENERGY_UNITS = new Set(["200", "201", "202", "203"]);

export function createDashboardTelemetryStore(): DashboardTelemetryStore {
  return {
    samples: {},
    seenEventIds: [],
    rejectedFutureSamples: 0,
  };
}

export function telemetrySeriesKey(sample: TelemetrySample): string {
  return [sample.node_id, sample.equipment_id, sample.channel_id, sample.metric].join(":");
}

function milliseconds(value: Date | number | undefined): number {
  if (value instanceof Date) {
    return value.getTime();
  }
  return value ?? Date.now();
}

function capturedAtMs(sample: TelemetrySample): number {
  return Date.parse(sample.captured_at);
}

export function mergeDashboardTelemetry(
  current: DashboardTelemetryStore,
  incoming: readonly TelemetrySample[],
  options: MergeTelemetryOptions = {},
): DashboardTelemetryStore {
  const nowMs = milliseconds(options.now);
  const maxFutureSkewMs = options.maxFutureSkewMs ?? DEFAULT_MAX_FUTURE_SKEW_MS;
  const maxSeenEventIds = options.maxSeenEventIds ?? DEFAULT_MAX_SEEN_EVENT_IDS;
  const seen = new Set(current.seenEventIds);
  const seenOrder = [...current.seenEventIds];
  const samples = { ...current.samples };
  let rejectedFutureSamples = current.rejectedFutureSamples;
  let changed = false;

  for (const sample of incoming) {
    if (seen.has(sample.event_id)) {
      continue;
    }

    const sampleTime = capturedAtMs(sample);
    if (!Number.isFinite(sampleTime) || sampleTime > nowMs + maxFutureSkewMs) {
      rejectedFutureSamples += 1;
      changed = true;
      continue;
    }

    seen.add(sample.event_id);
    seenOrder.push(sample.event_id);
    changed = true;

    const key = telemetrySeriesKey(sample);
    const previous = samples[key];
    if (!previous || capturedAtMs(previous) <= sampleTime) {
      samples[key] = sample;
    }
  }

  while (seenOrder.length > maxSeenEventIds) {
    seenOrder.shift();
  }

  if (!changed) {
    return current;
  }

  return {
    samples,
    seenEventIds: seenOrder,
    rejectedFutureSamples,
  };
}

export function deriveDashboardTelemetry(
  store: DashboardTelemetryStore,
  options: DeriveTelemetryOptions,
): DashboardTelemetryView {
  const nowMs = milliseconds(options.now);
  const staleAfterMs = options.staleAfterMs ?? DEFAULT_STALE_AFTER_MS;
  const samples = Object.values(store.samples).sort(
    (left, right) => capturedAtMs(right) - capturedAtMs(left),
  );
  const latestTimestamp = samples[0]?.captured_at ?? null;
  const ageMs = latestTimestamp === null ? null : Math.max(0, nowMs - Date.parse(latestTimestamp));
  const freshSamples = samples.filter((sample) => nowMs - capturedAtMs(sample) <= staleAfterMs);

  let status: DashboardTelemetryStatus;
  if (options.error && samples.length === 0) {
    status = "error";
  } else if (!options.hasLoadedSnapshot && samples.length === 0) {
    status = "connecting";
  } else if (options.connectionState === "reconnecting") {
    status = freshSamples.length > 0 ? "reconnecting" : "stale";
  } else if (options.connectionState === "disconnected") {
    status = freshSamples.length > 0 ? "reconnecting" : "offline";
  } else if (freshSamples.length === 0) {
    status = samples.length > 0 ? "stale" : "offline";
  } else {
    status = "live";
  }

  return {
    status,
    samples,
    freshSamples,
    lastCapturedAt: latestTimestamp,
    ageMs,
    rejectedFutureSamples: store.rejectedFutureSamples,
  };
}

function isUsable(sample: TelemetrySample): sample is UsableTelemetrySample {
  return sample.quality === "valid" && sample.value !== null;
}

function normalizedMetric(metric: string): string {
  return metric
    .trim()
    .toLowerCase()
    .replaceAll(/[.\s-]+/g, "_");
}

function isTemperatureMetric(metric: string): boolean {
  const normalized = normalizedMetric(metric);
  return normalized === "temperature" || normalized.startsWith("temperature_");
}

function belongsToEnergyUnit(sample: TelemetrySample): boolean {
  return [...PRODUCTION_ENERGY_UNITS].some(
    (unit) => sample.equipment_id.includes(unit) || sample.channel_id.includes(unit),
  );
}

function isActivePowerMetric(metric: string): boolean {
  const normalized = normalizedMetric(metric);
  return normalized === "active_power" || normalized === "electrical_power_active";
}

function powerInKw(sample: TelemetrySample): number | null {
  if (!isUsable(sample) || !isActivePowerMetric(sample.metric)) {
    return null;
  }

  const unit = sample.unit.trim().toLowerCase();
  if (unit === "kw") {
    return sample.value;
  }
  if (unit === "w") {
    return sample.value / 1_000;
  }
  return null;
}

function formatNumber(value: number, digits: number): string {
  return new Intl.NumberFormat("uk-UA", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

function qualityLabel(quality: TelemetryQuality): string {
  switch (quality) {
    case "valid":
      return "valid";
    case "sensor_error":
      return "помилка датчика";
    case "communication_error":
      return "помилка зв’язку";
    default:
      return "невідома якість";
  }
}

function alarmLabel(alarm: TelemetryAlarm | null): string {
  if (alarm === "high") {
    return "верхня межа";
  }
  if (alarm === "low") {
    return "нижня межа";
  }
  return "без тривоги";
}

function badgeForStatus(status: DashboardTelemetryStatus): {
  badge: string;
  badgeTone: DashboardKpiValue["badgeTone"];
} {
  switch (status) {
    case "live":
      return { badge: "live", badgeTone: "live" };
    case "reconnecting":
      return { badge: "reconnect", badgeTone: "stale" };
    case "stale":
      return { badge: "stale", badgeTone: "stale" };
    case "error":
      return { badge: "error", badgeTone: "error" };
    default:
      return { badge: "offline", badgeTone: "offline" };
  }
}

export function buildLiveDashboardKpis(view: DashboardTelemetryView): DashboardKpiValue[] {
  const badge = badgeForStatus(view.status);
  const fresh = view.freshSamples;
  const good = fresh.filter(isUsable);
  const nodeCount = new Set(fresh.map((sample) => sample.node_id)).size;
  const activeRecords = good.length;
  const alarmSamples = fresh.filter((sample) => sample.alarm !== null || sample.quality !== "valid");
  const temperatures = good.filter(
    (sample) => isTemperatureMetric(sample.metric) && PRODUCTION_TEMPERATURE_CHANNELS.has(sample.channel_id),
  );
  const averageTemperature =
    temperatures.length === 0
      ? null
      : temperatures.reduce((sum, sample) => sum + sample.value, 0) / temperatures.length;
  const powerSamples = good.filter(belongsToEnergyUnit);
  const totalPower = powerSamples.reduce((sum, sample) => sum + (powerInKw(sample) ?? 0), 0);
  const hasPower = powerSamples.some((sample) => powerInKw(sample) !== null);

  return [
    {
      label: "Вузлів онлайн",
      value: `${nodeCount} / 1`,
      detail: nodeCount === 1 ? "edge-01 передає дані" : "edge-01 недоступний",
      trend: "production scope M3",
      tone: nodeCount === 1 ? "blue" : "red",
      icon: "network",
      ...badge,
    },
    {
      label: "Свіжих записів",
      value: `${activeRecords} / ${EXPECTED_RECORDS_PER_CYCLE}`,
      detail: `${fresh.length} latest records`,
      trend: "34 записи на повний цикл",
      tone: activeRecords > 0 ? "green" : "red",
      icon: "signal",
      ...badge,
    },
    {
      label: "Активних сесій",
      value: "—",
      detail: "Session API ще не підключено",
      trend: "дані не симулюються",
      tone: "cyan",
      icon: "session",
      ...badge,
    },
    {
      label: "Активних тривог",
      value: String(alarmSamples.length),
      detail:
        alarmSamples.length === 0
          ? "Без telemetry alarms"
          : `${alarmSamples.filter((sample) => sample.alarm !== null).length} threshold alarms`,
      trend:
        alarmSamples[0] === undefined
          ? "quality valid"
          : `${qualityLabel(alarmSamples[0].quality)} · ${alarmLabel(alarmSamples[0].alarm)}`,
      tone: alarmSamples.length === 0 ? "green" : "red",
      icon: "alarm",
      ...badge,
    },
    {
      label: "Поточне споживання",
      value: hasPower ? `${formatNumber(totalPower, 2)} kW` : "—",
      detail: hasPower ? "LE-01MP 200–203" : "Немає свіжих active_power",
      trend: "сума валідних лічильників",
      tone: hasPower ? "amber" : "red",
      icon: "energy",
      ...badge,
    },
    {
      label: "Середня температура",
      value: averageTemperature === null ? "—" : `${formatNumber(averageTemperature, 1)} °C`,
      detail:
        temperatures.length === 0 ? "106-03 / 106-04 недоступні" : `${temperatures.length}/2 каналів valid`,
      trend: "XJP60D production channels",
      tone: averageTemperature === null ? "red" : "blue",
      icon: "temperature",
      ...badge,
    },
  ];
}

export function selectProductionTemperatures(view: DashboardTelemetryView): TelemetrySample[] {
  return view.samples.filter(
    (sample) => isTemperatureMetric(sample.metric) && PRODUCTION_TEMPERATURE_CHANNELS.has(sample.channel_id),
  );
}
