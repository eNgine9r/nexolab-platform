import { describe, expect, it } from "vitest";

import { chartSeriesKey, type ChartSeriesIdentity } from "./domain";
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
