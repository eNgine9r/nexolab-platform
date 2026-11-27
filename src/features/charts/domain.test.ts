import { describe, expect, it } from "vitest";

import { CHART_SERIES_TOKENS, chartSeriesKey, type ChartSeriesIdentity } from "./domain";
import { CANONICAL_CHART_TIME_RANGES } from "./time-ranges";

describe("chart domain contracts", () => {
  it("derives stable series identity only from telemetry identity fields", () => {
    const identity: ChartSeriesIdentity = {
      nodeId: "edge-01",
      equipmentId: "chamber-01",
      channelId: "kk2-01",
      metric: "temperature.probe",
      nativeUnit: "°C",
    };

    expect(chartSeriesKey(identity)).toBe(chartSeriesKey({ ...identity }));
    expect(chartSeriesKey({ ...identity, channelId: "kk2-02" })).not.toBe(chartSeriesKey(identity));
  });

  it("publishes every canonical time range without making custom implicit", () => {
    expect(CANONICAL_CHART_TIME_RANGES.map((range) => range.id)).toEqual([
      "live",
      "5m",
      "15m",
      "1h",
      "6h",
      "24h",
      "7d",
      "custom",
    ]);
    expect(CANONICAL_CHART_TIME_RANGES.find((range) => range.id === "custom")?.durationMs).toBeNull();
  });
});

describe("#1868 solid measurement lines", () => {
  it("every palette token draws a solid line (colour and legend tell series apart)", () => {
    for (const token of CHART_SERIES_TOKENS) expect(token.dashStyle).toBe("solid");
    expect(new Set(CHART_SERIES_TOKENS.map((token) => token.color)).size).toBe(CHART_SERIES_TOKENS.length);
  });
});
