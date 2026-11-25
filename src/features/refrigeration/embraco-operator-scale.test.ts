import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";
import { EMBRACO_METRICS } from "./controller-monitoring";
import {
  EMBRACO_KK1_OPERATOR_SCALE,
  EMBRACO_KK1_OPERATOR_SCALE_BASIS,
  operatorEmbracoCelsius,
} from "./embraco-operator-scale";

const base: TelemetrySample = {
  event_id: "raw-probe",
  node_id: "edge-01",
  captured_at: "2026-11-19T15:38:20Z",
  metric: EMBRACO_METRICS.cabinet,
  value: null,
  unit: "degC",
  quality: "unknown",
  source: "embraco-sync",
  equipment_id: "EMBRACO-2",
  channel_id: "2-cabinet-temperature",
  alarm: null,
  raw_value: 42,
  raw_status: null,
};

describe("provisional 0.01 °C/count Embraco HMI-mismatch candidate", () => {
  it("uses HMI-informed factor with explicit not-calibrated provenance", () => {
    expect(EMBRACO_KK1_OPERATOR_SCALE).toBe(0.01);
    expect(EMBRACO_KK1_OPERATOR_SCALE_BASIS).toBe("candidate_0p01_hmi_not_calibrated");
    expect(operatorEmbracoCelsius(base)).toBe(0.42);
    expect(
      operatorEmbracoCelsius({
        ...base,
        metric: EMBRACO_METRICS.evaporator,
        channel_id: "2-evaporator-temperature",
        raw_value: 65510,
      }),
    ).toBe(-0.26);
    expect(operatorEmbracoCelsius({ ...base, raw_value: 0x8000 })).toBe(-327.68);
    expect(operatorEmbracoCelsius({ ...base, raw_value: 0xffff })).toBe(-0.01);
    expect(operatorEmbracoCelsius({ ...base, raw_value: 0 })).toBe(0);
    expect(operatorEmbracoCelsius({ ...base, raw_value: 32767 })).toBe(327.67);
    // Live Modbus FC03 observed 2026-11-20, controller display +0.1 °C.
    expect(operatorEmbracoCelsius({ ...base, raw_value: 65514 })).toBe(-0.22);
    expect(
      operatorEmbracoCelsius({
        ...base,
        metric: EMBRACO_METRICS.evaporator,
        channel_id: "2-evaporator-temperature",
        raw_value: 24,
      }),
    ).toBe(0.24);
  });

  it("does not invent readings for other controllers, channels or missing/error raw", () => {
    for (const changed of [
      { equipment_id: "EMBRACO-96" },
      { node_id: "edge-other" },
      { channel_id: "2-evaporator-temperature" },
      { source: "other" },
      { metric: EMBRACO_METRICS.condenser },
      { quality: "communication_error" as const },
      { quality: "valid" as const, value: 4.2 },
      { value: 0 },
      { raw_value: null },
      { raw_value: -1 },
      { raw_value: 65536 },
      { raw_value: 1.5 },
      { raw_value: Number.NaN },
      { metric: EMBRACO_METRICS.evaporator, channel_id: "2-cabinet-temperature" },
      { metric: EMBRACO_METRICS.cabinet, channel_id: "2-evaporator-temperature" },
    ]) {
      expect(operatorEmbracoCelsius({ ...base, ...changed })).toBeNull();
    }
  });

  it("never changes source sample value/quality/raw evidence", () => {
    const sample = { ...base, raw_value: 65485 };
    expect(operatorEmbracoCelsius(sample)).toBe(-0.51);
    expect(sample.value).toBeNull();
    expect(sample.quality).toBe("unknown");
    expect(sample.raw_value).toBe(65485);
  });
});
