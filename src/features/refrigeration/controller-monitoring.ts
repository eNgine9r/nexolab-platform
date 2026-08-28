import { loadCompleteTelemetryHistory } from "@/lib/telemetry/history";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

import type { RefrigerationControllerBinding } from "./controller-binding-repository";

export type RefrigerationHistoryPreset = "1h" | "12h" | "24h" | "custom";
export type RefrigerationHistoryRange = { from: Date; to: Date };

export const EMBRACO_METRICS = {
  hysteresis: "refrigeration.hysteresis",
  setpoint: "refrigeration.setpoint",
  cabinet: "temperature.cabinet",
  evaporator: "temperature.evaporator",
  condenser: "temperature.condenser",
  ambient: "temperature.ambient",
  door: "temperature.door",
  auxiliary: "temperature.auxiliary",
  evaporator2: "temperature.evaporator_2",
  controlState: "refrigeration.control_state",
  relays: "controller.relay_state_bits",
  compressorSpeed: "compressor.speed",
  alarms: "controller.alarm_state_bits",
} as const;

export const EMBRACO_HISTORY_METRICS = [
  EMBRACO_METRICS.cabinet,
  EMBRACO_METRICS.evaporator,
  EMBRACO_METRICS.condenser,
  EMBRACO_METRICS.setpoint,
  EMBRACO_METRICS.compressorSpeed,
  EMBRACO_METRICS.controlState,
  EMBRACO_METRICS.relays,
  EMBRACO_METRICS.alarms,
] as const;

export type EmbracoControllerSnapshot = {
  latestByMetric: ReadonlyMap<string, TelemetrySample>;
  compressorSpeedRpm: number | null;
  controlState: string | null;
  relayStates: readonly boolean[] | null;
  activeAlarms: readonly string[] | null;
  lastSeenAt: string | null;
  online: boolean;
};

const CONTROL_STATES: Record<number, string> = {
  0: "Idle",
  1: "Cooling",
  2: "Prepare defrost",
  3: "Defrost",
  4: "Post-defrost",
  5: "Pulldown",
};

const ALARMS: Record<number, string> = {
  1: "Висока температура вітрини",
  2: "Низька температура вітрини",
  3: "Висока температура конденсатора",
  4: "Низька холодопродуктивність",
  5: "Зовнішня тривога",
  6: "Відкриті двері",
  7: "Несправність температурного датчика",
  8: "Помилка зв’язку з інвертором",
  9: "Відтайка не завершена",
  10: "RTC не налаштований",
  11: "Висока допоміжна температура",
  12: "Низька допоміжна температура",
};

export function resolveRefrigerationHistoryRange(
  preset: RefrigerationHistoryPreset,
  now: Date,
  custom?: RefrigerationHistoryRange | null,
): RefrigerationHistoryRange {
  const to = new Date(now);
  if (!Number.isFinite(to.getTime())) throw new Error("invalid current time");
  if (preset === "custom") {
    if (!custom) throw new Error("custom history range is required");
    const from = new Date(custom.from);
    const customTo = new Date(custom.to);
    if (!Number.isFinite(from.getTime()) || !Number.isFinite(customTo.getTime()) || from >= customTo) {
      throw new Error("custom history range must have valid from/to values");
    }
    return { from, to: customTo };
  }
  const hours = preset === "1h" ? 1 : preset === "12h" ? 12 : 24;
  return { from: new Date(to.getTime() - hours * 60 * 60 * 1000), to };
}

export function buildEmbracoSnapshot(samples: readonly TelemetrySample[]): EmbracoControllerSnapshot {
  const latestByMetric = new Map<string, TelemetrySample>();
  for (const sample of samples) {
    const current = latestByMetric.get(sample.metric);
    if (!current || Date.parse(sample.captured_at) > Date.parse(current.captured_at)) {
      latestByMetric.set(sample.metric, sample);
    }
  }
  const speed = latestByMetric.get(EMBRACO_METRICS.compressorSpeed);
  const state = latestByMetric.get(EMBRACO_METRICS.controlState);
  const relays = latestByMetric.get(EMBRACO_METRICS.relays);
  const alarms = latestByMetric.get(EMBRACO_METRICS.alarms);
  const validSamples = [...latestByMetric.values()].filter((item) => item.quality === "valid");
  const lastSeenAt = validSamples.reduce<string | null>(
    (latest, item) =>
      !latest || Date.parse(item.captured_at) > Date.parse(latest) ? item.captured_at : latest,
    null,
  );
  return {
    latestByMetric,
    compressorSpeedRpm: validNumber(speed),
    controlState:
      state?.quality === "valid" && state.value !== null
        ? (CONTROL_STATES[Math.trunc(state.value)] ?? null)
        : null,
    relayStates:
      relays?.quality === "valid" && relays.value !== null ? decodeRelayBits(Math.trunc(relays.value)) : null,
    activeAlarms:
      alarms?.quality === "valid" && alarms.value !== null ? decodeAlarmBits(Math.trunc(alarms.value)) : null,
    lastSeenAt,
    online: lastSeenAt !== null && Date.now() - Date.parse(lastSeenAt) <= 120_000,
  };
}

export async function loadEmbracoLatest(
  adapter: TelemetryAdapter,
  binding: RefrigerationControllerBinding,
  signal?: AbortSignal,
): Promise<EmbracoControllerSnapshot> {
  const response = await adapter.latest(
    { node_id: binding.nodeId, equipment_id: binding.controllerEquipmentId, limit: 100 },
    signal,
  );
  return buildEmbracoSnapshot(response.items);
}

export async function loadEmbracoHistory(
  adapter: TelemetryAdapter,
  binding: RefrigerationControllerBinding,
  range: RefrigerationHistoryRange,
  signal?: AbortSignal,
): Promise<Map<string, TelemetrySample[]>> {
  const entries = await Promise.all(
    EMBRACO_HISTORY_METRICS.map(async (metric) => {
      const result = await loadCompleteTelemetryHistory(
        adapter,
        { node_id: binding.nodeId, equipment_id: binding.controllerEquipmentId, metric },
        range,
        { signal },
      );
      return [metric, result.samples] as const;
    }),
  );
  return new Map(entries);
}

export function decodeRelayBits(value: number): readonly boolean[] {
  return [0, 1, 2, 3].map((bit) => Boolean(value & (1 << bit)));
}

export function decodeAlarmBits(value: number): readonly string[] {
  return Object.entries(ALARMS)
    .filter(([bit]) => Boolean(value & (1 << Number(bit))))
    .map(([, label]) => label);
}

function validNumber(sample: TelemetrySample | undefined): number | null {
  return sample?.quality === "valid" && sample.value !== null && Number.isFinite(sample.value)
    ? sample.value
    : null;
}
