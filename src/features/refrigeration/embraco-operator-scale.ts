import type { TelemetrySample } from "@/lib/telemetry/types";

import { EMBRACO_METRICS } from "./controller-monitoring";

/**
 * 2026-11-20 candidate after physical HMI +0.1 °C contradicted earlier ×0.1.
 * Raw cabinet -22, evaporator +24 and condenser +3202 counts suggest ×0.01,
 * but HMI probe selection and actual calibration remain UNVERIFIED.
 * This is display-only interpretation; NEVER mark source quality as valid.
 */
export const EMBRACO_KK1_OPERATOR_SCALE = 0.01;
export const EMBRACO_KK1_OPERATOR_SCALE_BASIS = "candidate_0p01_hmi_not_calibrated";
export const EMBRACO_KK1_CONTROLLER_ID = "EMBRACO-2";

const EMBRACO_PROBE_CHANNELS: Record<string, string> = {
  [EMBRACO_METRICS.cabinet]: "2-cabinet-temperature",
  [EMBRACO_METRICS.evaporator]: "2-evaporator-temperature",
};

export function isEmbracoProbeMetric(metric: string): boolean {
  return Object.hasOwn(EMBRACO_PROBE_CHANNELS, metric);
}

/**
 * Presentation-only PROVISIONAL Celsius estimate from an unsigned FC03 word.
 * The display at the controller may use a different configured probe.
 * Reject other controllers, non-probes, missing readings and communication errors.
 * Never update persisted value/quality or infer hardware calibration.
 */
export function operatorEmbracoCelsius(sample: TelemetrySample): number | null {
  if (
    sample.node_id !== "edge-01" ||
    sample.equipment_id !== EMBRACO_KK1_CONTROLLER_ID ||
    sample.source !== "embraco-sync" ||
    !isEmbracoProbeMetric(sample.metric) ||
    sample.channel_id !== EMBRACO_PROBE_CHANNELS[sample.metric] ||
    sample.quality !== "unknown" ||
    sample.value !== null ||
    sample.raw_value === null ||
    !Number.isInteger(sample.raw_value) ||
    sample.raw_value < 0 ||
    sample.raw_value > 0xffff
  ) {
    return null;
  }

  const signed = sample.raw_value >= 0x8000 ? sample.raw_value - 0x10000 : sample.raw_value;
  return signed * EMBRACO_KK1_OPERATOR_SCALE;
}
