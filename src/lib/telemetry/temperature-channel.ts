import type { TelemetrySample } from "./types";

const CONTROLLER_CHANNEL_PATTERN = /^([1-9]\d{0,2})-(?:0?[1-6])$/;
const SECTION_CHANNEL_PATTERN = /^([a-zA-Z0-9_-]+):([1-9]\d{0,2})-S0[1-6]$/;

export function normalizeTelemetryMetric(value: string): string {
  return value.trim().toLowerCase().replaceAll("-", "_").replaceAll(".", "_").replaceAll(" ", "_");
}

export function isTemperatureProbeSample(sample: TelemetrySample): boolean {
  const metric = normalizeTelemetryMetric(sample.metric);
  const channel = CONTROLLER_CHANNEL_PATTERN.exec(sample.channel_id);
  const section = SECTION_CHANNEL_PATTERN.exec(sample.channel_id);
  const controllerInput = channel !== null && Number(channel[1]) <= 247;
  const commissionedSection =
    section !== null &&
    Number(section[2]) <= 247 &&
    sample.equipment_id === `XJP60D-S:${section[1]}:${section[2]}`;
  return (
    (controllerInput || commissionedSection) &&
    (metric === "temperature" || metric.startsWith("temperature_"))
  );
}
