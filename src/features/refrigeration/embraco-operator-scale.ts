import type { TelemetrySample } from "@/lib/telemetry/types";

import { EMBRACO_METRICS } from "./controller-monitoring";

/** Product Owner's 2026-11-19 interpretation; NOT hardware-verified calibration. */
export const EMBRACO_KK1_OPERATOR_SCALE = 0.1;
export const EMBRACO_KK1_OPERATOR_SCALE_BASIS = "operator_confirmed_hardware_unverified";
export const EMBRACO_KK1_CONTROLLER_ID = "EMBRACO-2";

export function isEmbracoProbeMetric(metric: string): boolean {
  return metric === EMBRACO_METRICS.cabinet || metric === EMBRACO_METRICS.evaporator;
}

/**
 * Presentation-only Celsius estimate from an unsigned FC03 word.
 * Reject other controllers, non-probes, missing readings and communication errors.
 * Never update persisted value/quality or infer hardware calibration.
 */
export function operatorEmbracoCelsius(sample: TelemetrySample): number | null {
  if (
    sample.equipment_id !== EMBRACO_KK1_CONTROLLER_ID ||
    sample.source !== "embraco-sync" ||
    !isEmbracoProbeMetric(sample.metric) ||
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
  return signed / 10;
}
