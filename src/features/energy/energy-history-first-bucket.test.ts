import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import { downsampleEnergyHistory } from "./energy-history";
import { energyHistorySourceEventId, isEnergyHistorySegmentStart } from "./energy-history-segment";

function sample(second: number, quality: TelemetrySample["quality"] = "valid"): TelemetrySample {
  return {
    event_id: `energy-${second}`,
    node_id: "edge-01",
    captured_at: new Date(second * 1_000).toISOString(),
    metric: "electrical.power.active",
    value: quality === "valid" ? second : null,
    unit: "W",
    quality,
    source: "f-and-f-le-01mp",
    equipment_id: "LE01MP-200",
    channel_id: "200-active-power",
    alarm: null,
    raw_value: second,
    raw_status: null,
  };
}

describe("energy history first bucket", () => {
  it("keeps the first endpoint and transfers a later outage marker to the next retained point", () => {
    const result = downsampleEnergyHistory(
      [
        sample(0),
        sample(5, "communication_error"),
        sample(10),
        sample(20),
        sample(30),
        sample(40),
        sample(60),
        sample(90),
        sample(100),
      ],
      4,
      {
        from: new Date(0),
        to: new Date(100_000),
      },
    );

    expect(energyHistorySourceEventId(result[0].event_id)).toBe("energy-0");
    expect(isEnergyHistorySegmentStart(result[0].event_id)).toBe(false);
    expect(isEnergyHistorySegmentStart(result[1].event_id)).toBe(true);
  });
});
