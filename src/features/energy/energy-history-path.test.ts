import { describe, expect, it } from "vitest";

import { markEnergyHistorySegmentStart } from "./energy-history-segment";
import { buildEnergyHistoryPath } from "./energy-history-path";
import type { TelemetrySample } from "@/lib/telemetry/types";

function point(index: number, eventId = `event-${index}`) {
  return {
    id: eventId,
    x: index * 10,
    y: index * 5,
    capturedAt: new Date(Date.parse("2026-08-03T10:00:00Z") + index * 363_000).toISOString(),
  };
}

describe("energy history path", () => {
  it("keeps normal downsampled 24-hour points connected", () => {
    const points = Array.from({ length: 6 }, (_, index) => point(index));

    expect(buildEnergyHistoryPath(points).match(/M/g)).toHaveLength(1);
  });

  it("breaks only at a source-preserved telemetry outage", () => {
    const marker = markEnergyHistorySegmentStart({
      event_id: "event-4",
    } as TelemetrySample).event_id;
    const points = [point(0), point(1), point(2), point(3), point(4, marker), point(5)];

    expect(buildEnergyHistoryPath(points)).toContain("M40.00 20.00");
    expect(buildEnergyHistoryPath(points).match(/M/g)).toHaveLength(2);
  });
});
