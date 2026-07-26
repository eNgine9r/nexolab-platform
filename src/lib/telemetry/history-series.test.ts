import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "./types";
import { buildTemperatureHistoryChart, mergeTelemetryHistory } from "./history-series";

function sample(
  eventId: string,
  channelId: string,
  capturedAt: string,
  value: number | null,
  quality: TelemetrySample["quality"] = "valid",
): TelemetrySample {
  return {
    event_id: eventId,
    node_id: "edge-01",
    captured_at: capturedAt,
    metric: "temperature.probe",
    value,
    unit: "degC",
    quality,
    source: "dixell-xjp60d",
    equipment_id: "K106",
    channel_id: channelId,
    alarm: null,
    raw_value: value === null ? null : Math.round(value * 10),
    raw_status: null,
  };
}

describe("temperature history series", () => {
  it("deduplicates history and latest samples in chronological order", () => {
    const first = sample("event-1", "106-03", "2026-07-26T05:00:00Z", 3.2);
    const second = sample("event-2", "106-03", "2026-07-26T05:10:00Z", 3.4);

    expect(mergeTelemetryHistory([second, first], [second]).map((item) => item.event_id)).toEqual([
      "event-1",
      "event-2",
    ]);
  });

  it("builds bounded paths only from valid production temperature channels", () => {
    const chart = buildTemperatureHistoryChart(
      [
        sample("event-1", "106-03", "2026-07-26T05:00:00Z", 3.2),
        sample("event-2", "106-03", "2026-07-26T05:30:00Z", 4.1),
        sample("event-3", "106-04", "2026-07-26T05:45:00Z", 2.8),
        sample("event-4", "106-04", "2026-07-26T05:50:00Z", null, "sensor_error"),
        sample("event-5", "115-04", "2026-07-26T05:55:00Z", 8.0),
      ],
      { from: "2026-07-26T05:00:00Z", to: "2026-07-26T06:00:00Z" },
    );

    expect(chart.series.map((item) => item.channelId)).toEqual(["106-03", "106-04"]);
    expect(chart.series[0].path).toMatch(/^M/);
    expect(chart.series.flatMap((item) => item.points)).toHaveLength(3);
    expect(chart.minimum).toBe(2.8);
    expect(chart.maximum).toBe(4.1);
    expect(
      chart.series.flatMap((item) => item.points).every((point) => point.x >= 32 && point.x <= 600),
    ).toBe(true);
  });
});
