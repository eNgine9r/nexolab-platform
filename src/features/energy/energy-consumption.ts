import { isEnergySample, resolveEnergyMeter, type EnergyMeter } from "@/features/energy/energy-telemetry";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

export const ENERGY_CONSUMPTION_METRIC = "electrical.energy.active" as const;
export const ENERGY_CONSUMPTION_ANCHOR_TOLERANCE_MS = 5 * 60 * 1000;

export type EnergyConsumptionPreset =
  | "today"
  | "yesterday"
  | "last24h"
  | "last7d"
  | "last30d"
  | "month"
  | "custom";

export interface EnergyConsumptionWindow {
  from: Date;
  to: Date;
}

export interface EnergyConsumptionCustomRange {
  fromLocal: string;
  toLocal: string;
}

export type EnergyConsumptionStatus = "ready" | "unavailable" | "discontinuity" | "error";

export interface EnergyConsumptionResult {
  status: EnergyConsumptionStatus;
  valueKwh: number | null;
  startSample: TelemetrySample | null;
  endSample: TelemetrySample | null;
  message: string | null;
}

export interface EnergyConsumptionLoadOptions {
  nodeId: string;
  meter: EnergyMeter;
  window: EnergyConsumptionWindow;
  currentCumulative?: TelemetrySample | null;
  anchorToleranceMs?: number;
}

const PRESET_LABELS: Record<Exclude<EnergyConsumptionPreset, "custom">, string> = {
  today: "Сьогодні",
  yesterday: "Вчора",
  last24h: "24 год",
  last7d: "7 днів",
  last30d: "30 днів",
  month: "Цей місяць",
};

function startOfLocalDay(value: Date): Date {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate());
}

function parseLocalDateTime(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (!match) return null;
  const [, year, month, day, hour, minute] = match;
  const parsed = new Date(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour),
    Number(minute),
  );
  if (
    parsed.getFullYear() !== Number(year) ||
    parsed.getMonth() !== Number(month) - 1 ||
    parsed.getDate() !== Number(day) ||
    parsed.getHours() !== Number(hour) ||
    parsed.getMinutes() !== Number(minute)
  ) {
    return null;
  }
  return parsed;
}

export function resolveEnergyConsumptionWindow(
  preset: EnergyConsumptionPreset,
  now: Date,
  custom?: EnergyConsumptionCustomRange,
): EnergyConsumptionWindow | null {
  const to = new Date(now);
  if (!Number.isFinite(to.getTime())) return null;

  switch (preset) {
    case "today":
      return { from: startOfLocalDay(to), to };
    case "yesterday": {
      const end = startOfLocalDay(to);
      const start = new Date(end);
      start.setDate(start.getDate() - 1);
      return { from: start, to: end };
    }
    case "last24h":
      return { from: new Date(to.getTime() - 24 * 60 * 60 * 1000), to };
    case "last7d":
      return { from: new Date(to.getTime() - 7 * 24 * 60 * 60 * 1000), to };
    case "last30d":
      return { from: new Date(to.getTime() - 30 * 24 * 60 * 60 * 1000), to };
    case "month":
      return { from: new Date(to.getFullYear(), to.getMonth(), 1), to };
    case "custom": {
      if (!custom) return null;
      const from = parseLocalDateTime(custom.fromLocal);
      const customTo = parseLocalDateTime(custom.toLocal);
      if (!from || !customTo || from >= customTo) return null;
      return { from, to: customTo };
    }
  }
}

export function energyConsumptionPresetLabel(preset: EnergyConsumptionPreset): string {
  if (preset === "custom") return "Власний період";
  return PRESET_LABELS[preset];
}

export function formatEnergyConsumptionWindow(
  preset: EnergyConsumptionPreset,
  window: EnergyConsumptionWindow,
): string {
  switch (preset) {
    case "today":
      return "з 00:00 до зараз";
    case "yesterday":
      return "попередня календарна доба";
    case "last24h":
      return "останні 24 години";
    case "last7d":
      return "останні 7 днів";
    case "last30d":
      return "останні 30 днів";
    case "month":
      return "з початку місяця до зараз";
    case "custom": {
      const formatter = new Intl.DateTimeFormat("uk-UA", {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
      return `${formatter.format(window.from)} → ${formatter.format(window.to)}`;
    }
  }
}

export function formatEnergyConsumptionSelector(
  preset: EnergyConsumptionPreset,
  window: EnergyConsumptionWindow,
): string {
  if (preset !== "custom") return energyConsumptionPresetLabel(preset);
  const formatter = new Intl.DateTimeFormat("uk-UA", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${formatter.format(window.from)} → ${formatter.format(window.to)}`;
}

function sampleMatchesMeter(sample: TelemetrySample, meter: EnergyMeter): boolean {
  return (
    sample.metric === ENERGY_CONSUMPTION_METRIC &&
    sample.quality === "valid" &&
    sample.value !== null &&
    Number.isFinite(sample.value) &&
    isEnergySample(sample) &&
    resolveEnergyMeter(sample)?.unitId === meter.unitId
  );
}

function boundarySample(
  sample: TelemetrySample | null | undefined,
  meter: EnergyMeter,
  boundary: Date,
  toleranceMs: number,
): TelemetrySample | null {
  if (!sample || !sampleMatchesMeter(sample, meter)) return null;
  const capturedAt = Date.parse(sample.captured_at);
  const boundaryAt = boundary.getTime();
  if (!Number.isFinite(capturedAt) || capturedAt > boundaryAt) return null;
  if (boundaryAt - capturedAt > toleranceMs) return null;
  return sample;
}

async function loadBoundarySample(
  adapter: TelemetryAdapter,
  nodeId: string,
  meter: EnergyMeter,
  boundary: Date,
  toleranceMs: number,
  signal?: AbortSignal,
): Promise<TelemetrySample | null> {
  const response = await adapter.history(
    {
      node_id: nodeId,
      equipment_id: meter.equipmentId,
      metric: ENERGY_CONSUMPTION_METRIC,
      quality: "valid",
      from: new Date(boundary.getTime() - toleranceMs),
      to: new Date(boundary.getTime() + 1),
      limit: 1,
      offset: 0,
    },
    signal,
  );
  return boundarySample(response.items[0] ?? null, meter, boundary, toleranceMs);
}

export function deriveEnergyConsumption(
  startSample: TelemetrySample | null,
  endSample: TelemetrySample | null,
  meter: EnergyMeter,
): EnergyConsumptionResult {
  if (!startSample || !endSample) {
    return {
      status: "unavailable",
      valueKwh: null,
      startSample,
      endSample,
      message: "Недостатньо підтверджених даних біля меж вибраного періоду.",
    };
  }
  if (!sampleMatchesMeter(startSample, meter) || !sampleMatchesMeter(endSample, meter)) {
    return {
      status: "unavailable",
      valueKwh: null,
      startSample,
      endSample,
      message: "Граничні покази не відповідають підтвердженому лічильнику енергії.",
    };
  }

  const start = startSample.value!;
  const end = endSample.value!;
  const delta = end - start;
  if (delta < -0.000_001) {
    return {
      status: "discontinuity",
      valueKwh: null,
      startSample,
      endSample,
      message: "Виявлено зменшення накопичувального лічильника. Споживання не обчислюється до класифікації reset/rollover.",
    };
  }

  return {
    status: "ready",
    valueKwh: Math.max(0, delta),
    startSample,
    endSample,
    message: null,
  };
}

export async function loadEnergyConsumption(
  adapter: TelemetryAdapter,
  options: EnergyConsumptionLoadOptions,
  signal?: AbortSignal,
): Promise<EnergyConsumptionResult> {
  const toleranceMs = options.anchorToleranceMs ?? ENERGY_CONSUMPTION_ANCHOR_TOLERANCE_MS;
  if (
    !Number.isFinite(options.window.from.getTime()) ||
    !Number.isFinite(options.window.to.getTime()) ||
    options.window.from >= options.window.to
  ) {
    return {
      status: "error",
      valueKwh: null,
      startSample: null,
      endSample: null,
      message: "Некоректний часовий інтервал.",
    };
  }

  try {
    const [startSample, persistedEndSample] = await Promise.all([
      loadBoundarySample(
        adapter,
        options.nodeId,
        options.meter,
        options.window.from,
        toleranceMs,
        signal,
      ),
      boundarySample(
        options.currentCumulative,
        options.meter,
        options.window.to,
        toleranceMs,
      )
        ? Promise.resolve(null)
        : loadBoundarySample(
            adapter,
            options.nodeId,
            options.meter,
            options.window.to,
            toleranceMs,
            signal,
          ),
    ]);
    const liveEndSample = boundarySample(
      options.currentCumulative,
      options.meter,
      options.window.to,
      toleranceMs,
    );
    return deriveEnergyConsumption(startSample, liveEndSample ?? persistedEndSample, options.meter);
  } catch (error) {
    if (signal?.aborted) throw error;
    return {
      status: "error",
      valueKwh: null,
      startSample: null,
      endSample: null,
      message: error instanceof Error ? error.message : "Не вдалося завантажити дані споживання.",
    };
  }
}
