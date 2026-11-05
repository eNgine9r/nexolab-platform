import type { TelemetrySample } from "./types";

const CONTROLLER_CHANNEL_PATTERN = /^\d{2,3}-(?:0?[1-6])$/;

export function normalizeTelemetryMetric(value: string): string {
  return value.trim().toLowerCase().replaceAll("-", "_").replaceAll(".", "_").replaceAll(" ", "_");
}

export function isTemperatureProbeSample(sample: TelemetrySample): boolean {
  const metric = normalizeTelemetryMetric(sample.metric);
  const section = /^([A-Za-z0-9][A-Za-z0-9_-]{0,63}):(\d{1,3})-S0[1-6]$/.exec(sample.channel_id);
  const sectionInput =
    sample.source === "dixell-xjp60d-sections" &&
    section !== null &&
    Number(section[2]) >= 1 &&
    Number(section[2]) <= 242 &&
    sample.equipment_id === `XJP60D-S:${section[1]}:${section[2]}`;
  return (
    (CONTROLLER_CHANNEL_PATTERN.test(sample.channel_id) || sectionInput) &&
    (metric === "temperature" || metric.startsWith("temperature_"))
  );
}
