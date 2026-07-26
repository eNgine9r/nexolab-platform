import type { TelemetrySample } from "./types";

export const PRODUCTION_HISTORY_CHANNELS = ["106-03", "106-04"] as const;

export type TemperatureHistoryPoint = {
  eventId: string;
  capturedAt: string;
  value: number;
  x: number;
  y: number;
};

export type TemperatureHistorySeries = {
  channelId: string;
  points: TemperatureHistoryPoint[];
  path: string;
};

export type TemperatureHistoryChart = {
  series: TemperatureHistorySeries[];
  minimum: number | null;
  maximum: number | null;
  from: string;
  to: string;
};

function isTemperature(sample: TelemetrySample): boolean {
  const metric = sample.metric.trim().toLowerCase().replaceAll("-", "_").replaceAll(".", "_");
  return metric === "temperature" || metric.startsWith("temperature_");
}

function usable(sample: TelemetrySample): sample is TelemetrySample & { value: number } {
  return (
    sample.quality === "valid" &&
    sample.value !== null &&
    Number.isFinite(sample.value) &&
    isTemperature(sample) &&
    PRODUCTION_HISTORY_CHANNELS.includes(sample.channel_id as (typeof PRODUCTION_HISTORY_CHANNELS)[number])
  );
}

export function mergeTelemetryHistory(
  history: readonly TelemetrySample[],
  latest: readonly TelemetrySample[],
): TelemetrySample[] {
  const byEventId = new Map<string, TelemetrySample>();
  for (const sample of [...history, ...latest]) {
    byEventId.set(sample.event_id, sample);
  }
  return [...byEventId.values()].sort(
    (left, right) => Date.parse(left.captured_at) - Date.parse(right.captured_at),
  );
}

export function buildTemperatureHistoryChart(
  samples: readonly TelemetrySample[],
  window: { from: string; to: string },
): TemperatureHistoryChart {
  const fromMs = Date.parse(window.from);
  const toMs = Date.parse(window.to);
  const safeFrom = Number.isFinite(fromMs) ? fromMs : Date.now() - 60 * 60 * 1000;
  const safeTo = Number.isFinite(toMs) && toMs > safeFrom ? toMs : safeFrom + 60 * 60 * 1000;
  const accepted = samples.filter(usable).filter((sample) => {
    const captured = Date.parse(sample.captured_at);
    return Number.isFinite(captured) && captured >= safeFrom && captured <= safeTo;
  });
  const values = accepted.map((sample) => sample.value);
  const minimum = values.length > 0 ? Math.min(...values) : null;
  const maximum = values.length > 0 ? Math.max(...values) : null;
  const spread = minimum === null || maximum === null ? 1 : Math.max(1, maximum - minimum);
  const lower = minimum === null ? 0 : minimum - spread * 0.12;
  const upper = maximum === null ? 1 : maximum + spread * 0.12;
  const valueSpan = Math.max(1, upper - lower);
  const timeSpan = Math.max(1, safeTo - safeFrom);

  const series = PRODUCTION_HISTORY_CHANNELS.map((channelId) => {
    const channelSamples = accepted.filter((sample) => sample.channel_id === channelId);
    const points = channelSamples.map((sample) => {
      const captured = Date.parse(sample.captured_at);
      return {
        eventId: sample.event_id,
        capturedAt: sample.captured_at,
        value: sample.value,
        x: 32 + ((captured - safeFrom) / timeSpan) * 568,
        y: 20 + (1 - (sample.value - lower) / valueSpan) * 135,
      };
    });
    return {
      channelId,
      points,
      path: points
        .map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
        .join(" "),
    };
  }).filter((item) => item.points.length > 0);

  return {
    series,
    minimum,
    maximum,
    from: new Date(safeFrom).toISOString(),
    to: new Date(safeTo).toISOString(),
  };
}
