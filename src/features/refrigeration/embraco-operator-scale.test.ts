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
  channel_id: "cabinet",
  alarm: null,
  raw_value: 42,
  raw_status: null,
};

describe("operator 0.1 °C/count Embraco KK1 reading", () => {
  it("uses exactly owner-provided multiplier with explicit hardware-unverified basis", () => {
    expect(EMBRACO_KK1_OPERATOR_SCALE).toBe(0.1);
    expect(EMBRACO_KK1_OPERATOR_SCALE_BASIS).toBe("operator_confirmed_hardware_unverified");
    expect(operatorEmbracoCelsius(base)).toBe(4.2);
    expect(operatorEmbracoCelsius({ ...base, metric: EMBRACO_METRICS.evaporator, raw_value: 65510 })).toBe(
      -2.6,
    );
    expect(operatorEmbracoCelsius({ ...base, raw_value: 0x8000 })).toBe(-3276.8);
    expect(operatorEmbracoCelsius({ ...base, raw_value: 0xffff })).toBe(-0.1);
    expect(operatorEmbracoCelsius({ ...base, raw_value: 0 })).toBe(0);
    expect(operatorEmbracoCelsius({ ...base, raw_value: 32767 })).toBe(3276.7);
  });

  it("does not invent readings for other controllers, channels or missing/error raw", () => {
    for (const changed of [
      { equipment_id: "EMBRACO-96" },
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
    ]) {
      expect(operatorEmbracoCelsius({ ...base, ...changed })).toBeNull();
    }
  });

  it("never changes source sample value/quality/raw evidence", () => {
    const sample = { ...base, raw_value: 65485 };
    expect(operatorEmbracoCelsius(sample)).toBe(-5.1);
    expect(sample.value).toBeNull();
    expect(sample.quality).toBe("unknown");
    expect(sample.raw_value).toBe(65485);
  });
});
