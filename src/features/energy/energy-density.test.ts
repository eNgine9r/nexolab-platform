import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import { buildEmbracoCompressorScene, buildEmbracoTemperatureScene } from "../refrigeration/controller-chart";
import { EMBRACO_METRICS } from "../refrigeration/controller-monitoring";
import { downsampleEnergyHistory, mergeEnergyHistoryTail } from "./energy-history";

// Well in the past: samples dated after "now" are rejected as future skew.
const T0 = Date.parse("2026-11-10T00:00:00Z");
const COUNT = 6_000;

function power(index: number, value: number): TelemetrySample {
  return {
    event_id: `energy-edge-01-200-${index}`,
    node_id: "edge-01",
    captured_at: new Date(T0 + index * 10_000).toISOString(),
    metric: "electrical.power.active",
    value,
    unit: "W",
    quality: "valid",
    source: "f-and-f-le-01mp",
    equipment_id: "LE01MP-200",
    channel_id: "200-active-power",
    alarm: null,
    raw_value: value,
    raw_status: null,
  };
}

describe("Energy chart detail budget (#1620)", () => {
  const raw = Array.from({ length: COUNT }, (_, index) => power(index, index === 3_333 ? 4_800 : 500));

  it("keeps more points for a higher budget and the spike at every budget", () => {
    const small = downsampleEnergyHistory(raw, 240);
    const large = downsampleEnergyHistory(raw, 2_500);
    expect(small.length).toBeLessThan(large.length);
    expect(large.length).toBeLessThanOrEqual(2_500);
    for (const result of [small, large]) {
      expect(result.map((sample) => sample.value)).toContain(4_800);
    }
  });

  it("applies the budget when a live tail is merged", () => {
    const window = {
      nodeId: "edge-01",
      metric: "electrical.power.active" as const,
      from: new Date(T0 - 1),
      to: new Date(T0 + COUNT * 10_000),
    };
    const merged = mergeEnergyHistoryTail(raw, [power(COUNT, 500)], window, null, 500);
    expect(merged.length).toBeLessThanOrEqual(500);
    expect(merged.map((sample) => sample.value)).toContain(4_800);
  });
});

function embracoSample(metric: string, index: number, value: number): TelemetrySample {
  return {
    event_id: `emb-${metric}-${index}`,
    node_id: "edge-01",
    captured_at: new Date(T0 + index * 10_000).toISOString(),
    metric,
    value,
    unit: metric === EMBRACO_METRICS.compressorSpeed ? "rpm" : "degC",
    quality: "valid",
    source: "embraco-sync",
    equipment_id: "EMBRACO-2",
    channel_id: `2-${metric}`,
    alarm: null,
    raw_value: value,
    raw_status: null,
  };
}

describe("Refrigeration chart detail budget (#1620)", () => {
  const range = { from: new Date(T0), to: new Date(T0 + COUNT * 10_000) } as Parameters<
    typeof buildEmbracoCompressorScene
  >[1];

  it("renders more compressor points with a higher budget and never loses the extreme", () => {
    const history = new Map([
      [
        EMBRACO_METRICS.compressorSpeed,
        Array.from({ length: COUNT }, (_, index) =>
          embracoSample(EMBRACO_METRICS.compressorSpeed, index, index === 2_222 ? 4_000 : 1_800),
        ),
      ],
    ]);
    const points = (budget?: number) =>
      buildEmbracoCompressorScene(history, range, true, budget).series[0].segments.flatMap(
        (segment) => segment.points,
      );
    const auto = points();
    const high = points(2_500);
    expect(auto.length).toBeLessThan(high.length);
    expect(Math.max(...auto.map((point) => point.value))).toBe(4_000);
    expect(Math.max(...high.map((point) => point.value))).toBe(4_000);
  });

  it("applies the budget to the temperature scene as well", () => {
    const history = new Map([
      [
        EMBRACO_METRICS.cabinet,
        Array.from({ length: COUNT }, (_, index) => embracoSample(EMBRACO_METRICS.cabinet, index, 4)),
      ],
    ]);
    const count = (budget?: number) =>
      buildEmbracoTemperatureScene(history, range, true, budget).series[0].segments.flatMap(
        (segment) => segment.points,
      ).length;
    expect(count(120)).toBeLessThan(count(1_000));
  });
});
