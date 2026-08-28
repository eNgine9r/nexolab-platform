import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import { buildEmbracoTemperatureScene } from "./controller-chart";
import { EMBRACO_METRICS } from "./controller-monitoring";

function sample(quality: TelemetrySample["quality"], value: number | null): TelemetrySample {
  return {
    event_id: `cabinet-${quality}-${String(value)}`,
    node_id: "edge-01",
    captured_at: "2026-08-28T18:00:00.000Z",
    metric: EMBRACO_METRICS.cabinet,
    value,
    unit: "degC",
    quality,
    source: "embraco-sync",
    equipment_id: "EMBRACO-2",
    channel_id: "2-cabinet-temperature",
    alarm: null,
    raw_value: value,
    raw_status: null,
  };
}

describe("buildEmbracoTemperatureScene", () => {
  const range = {
    from: new Date("2026-08-28T17:00:00.000Z"),
    to: new Date("2026-08-28T18:00:00.000Z"),
  };

  it("does not create a chart series from unverified raw temperature samples", () => {
    const history = new Map([[EMBRACO_METRICS.cabinet, [sample("unknown", null)]]]);

    expect(buildEmbracoTemperatureScene(history, range, true).series).toEqual([]);
  });

  it("keeps the series when at least one verified engineering value exists", () => {
    const history = new Map([[EMBRACO_METRICS.cabinet, [sample("unknown", null), sample("valid", 4.2)]]]);

    expect(buildEmbracoTemperatureScene(history, range, true).series).toHaveLength(1);
  });
});
