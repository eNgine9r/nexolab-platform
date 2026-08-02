import { isTemperatureProbeSample, normalizeTelemetryMetric } from "./temperature-channel";
import type { TelemetryConnectionState, TelemetrySample } from "./types";

export type DashboardTelemetryStatus =
  | "demo"
  | "connecting"
  | "live"
  | "reconnecting"
  | "stale"
  | "offline"
  | "unauthorized"
  | "forbidden"
  | "configuration_error"
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

type ValidSample = TelemetrySample & { quality: "valid"; value: number };
const ENERGY_UNITS = ["200", "201", "202", "203"];

export function createDashboardTelemetryStore(): DashboardTelemetryStore {
  return { samples: {}, seenEventIds: [], rejectedFutureSamples: 0 };
}

export function telemetrySeriesKey(sample: TelemetrySample): string {
  return [sample.node_id, sample.equipment_id, sample.channel_id, sample.metric].join(":");
}

const time = (value?: Date | number) => (value instanceof Date ? value.getTime() : (value ?? Date.now()));
const captured = (sample: TelemetrySample) => Date.parse(sample.captured_at);

export function mergeDashboardTelemetry(
  current: DashboardTelemetryStore,
  incoming: readonly TelemetrySample[],
  options: MergeTelemetryOptions = {},
): DashboardTelemetryStore {
  const now = time(options.now);
  const seen = new Set(current.seenEventIds);
  const order = [...current.seenEventIds];
  const samples = { ...current.samples };
  let rejected = current.rejectedFutureSamples;
  let changed = false;
  for (const sample of incoming) {
    if (seen.has(sample.event_id)) continue;
    const stamp = captured(sample);
    if (!Number.isFinite(stamp) || stamp > now + (options.maxFutureSkewMs ?? 30_000)) {
      rejected += 1;
      changed = true;
      continue;
    }
    seen.add(sample.event_id);
    order.push(sample.event_id);
    changed = true;
    const key = telemetrySeriesKey(sample);
    if (!samples[key] || captured(samples[key]) <= stamp) samples[key] = sample;
  }
  while (order.length > (options.maxSeenEventIds ?? 10_000)) order.shift();
  return changed ? { samples, seenEventIds: order, rejectedFutureSamples: rejected } : current;
}

export function deriveDashboardTelemetry(
  store: DashboardTelemetryStore,
  options: DeriveTelemetryOptions,
): DashboardTelemetryView {
  const now = time(options.now);
  const samples = Object.values(store.samples).sort((a, b) => captured(b) - captured(a));
  const lastCapturedAt = samples[0]?.captured_at ?? null;
  const ageMs = lastCapturedAt ? Math.max(0, now - Date.parse(lastCapturedAt)) : null;
  const freshSamples = samples.filter((sample) => now - captured(sample) <= (options.staleAfterMs ?? 30_000));
  let status: DashboardTelemetryStatus;
  if (["unauthorized", "forbidden", "configuration_error"].includes(options.connectionState)) {
    status = options.connectionState as DashboardTelemetryStatus;
  } else if (options.error && samples.length === 0) status = "error";
  else if (!options.hasLoadedSnapshot && samples.length === 0) status = "connecting";
  else if (options.connectionState === "reconnecting") {
    status = freshSamples.length ? "reconnecting" : "stale";
  } else if (["offline", "idle"].includes(options.connectionState)) status = "offline";
  else if (!freshSamples.length) status = samples.length ? "stale" : "offline";
  else status = "live";
  return {
    status,
    samples,
    freshSamples,
    lastCapturedAt,
    ageMs,
    rejectedFutureSamples: store.rejectedFutureSamples,
  };
}

const valid = (sample: TelemetrySample): sample is ValidSample =>
  sample.quality === "valid" && sample.value !== null;
const energy = (sample: TelemetrySample) =>
  ENERGY_UNITS.some((unit) => sample.equipment_id.includes(unit) || sample.channel_id.includes(unit));
const power = (sample: TelemetrySample) => {
  if (
    !valid(sample) ||
    !["active_power", "electrical_power_active"].includes(normalizeTelemetryMetric(sample.metric))
  ) {
    return null;
  }
  const unit = sample.unit.toLowerCase();
  return unit === "kw" ? sample.value : unit === "w" ? sample.value / 1_000 : null;
};
const number = (value: number, digits: number) =>
  new Intl.NumberFormat("uk-UA", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);

function badge(status: DashboardTelemetryStatus) {
  if (status === "live") return { badge: "live", badgeTone: "live" as const };
  if (["reconnecting", "stale"].includes(status)) {
    return {
      badge: status === "stale" ? "stale" : "reconnect",
      badgeTone: "stale" as const,
    };
  }
  if (["unauthorized", "forbidden", "configuration_error", "error"].includes(status)) {
    return { badge: "error", badgeTone: "error" as const };
  }
  return { badge: "offline", badgeTone: "offline" as const };
}

export function buildLiveDashboardKpis(view: DashboardTelemetryView): DashboardKpiValue[] {
  const mark = badge(view.status);
  const fresh = view.freshSamples;
  const good = fresh.filter(valid);
  const nodes = new Set(fresh.map((sample) => sample.node_id)).size;
  const alarms = fresh.filter((sample) => sample.alarm !== null || sample.quality === "communication_error");
  const temperatures = good.filter(isTemperatureProbeSample);
  const average = temperatures.length
    ? temperatures.reduce((sum, sample) => sum + sample.value, 0) / temperatures.length
    : null;
  const powers = good
    .filter(energy)
    .map(power)
    .filter((value): value is number => value !== null);
  const totalPower = powers.reduce((sum, value) => sum + value, 0);
  return [
    {
      label: "Вузлів онлайн",
      value: `${nodes} / 1`,
      detail: nodes ? "edge-01 передає дані" : "edge-01 недоступний",
      trend: "production scope M3",
      tone: nodes ? "blue" : "red",
      icon: "network",
      ...mark,
    },
    {
      label: "Валідних вимірювань",
      value: String(good.length),
      detail: `${fresh.length} свіжих записів у поточному циклі`,
      trend: "усі налаштовані канали",
      tone: good.length ? "green" : "red",
      icon: "signal",
      ...mark,
    },
    {
      label: "Активних сесій",
      value: "—",
      detail: "Session API ще не підключено",
      trend: "дані не симулюються",
      tone: "cyan",
      icon: "session",
      ...mark,
    },
    {
      label: "Активних тривог",
      value: String(alarms.length),
      detail: alarms.length ? "Порогові або комунікаційні помилки" : "Без telemetry alarms",
      trend: "відсутній probe не створює тривогу",
      tone: alarms.length ? "red" : "green",
      icon: "alarm",
      ...mark,
    },
    {
      label: "Поточне споживання",
      value: powers.length ? `${number(totalPower, 2)} kW` : "—",
      detail: powers.length ? "LE-01MP 200–203" : "Немає свіжої active power",
      trend: "сума валідних лічильників",
      tone: powers.length ? "amber" : "red",
      icon: "energy",
      ...mark,
    },
    {
      label: "Середня температура",
      value: average === null ? "—" : `${number(average, 1)} °C`,
      detail: temperatures.length
        ? `${temperatures.length} валідних каналів XJP60D`
        : "Немає валідних каналів XJP60D",
      trend: "усі виявлені входи КК1 і КК2",
      tone: average === null ? "red" : "blue",
      icon: "temperature",
      ...mark,
    },
  ];
}

export function selectProductionTemperatures(view: DashboardTelemetryView): TelemetrySample[] {
  return view.samples.filter(isTemperatureProbeSample);
}
