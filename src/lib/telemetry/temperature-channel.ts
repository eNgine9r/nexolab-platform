import type { TelemetrySample } from "./types";

const CONTROLLER_CHANNEL_PATTERN = /^\d{3}-(?:0?[1-6])$/;

export function normalizeTelemetryMetric(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replaceAll("-", "_")
    .replaceAll(".", "_")
    .replaceAll(" ", "_");
}

export function isTemperatureProbeSample(sample: TelemetrySample): boolean {
  const metric = normalizeTelemetryMetric(sample.metric);
  return (
    CONTROLLER_CHANNEL_PATTERN.test(sample.channel_id) &&
    (metric === "temperature" || metric.startsWith("temperature_"))
  );
}
