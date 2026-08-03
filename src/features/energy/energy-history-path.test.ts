import { describe, expect, it } from "vitest";

import { buildEnergyHistoryPath, resolveEnergyHistoryGapMs } from "./energy-history-path";

describe("energy history path", () => {
  it("breaks the SVG path across telemetry outages", () => {
    const path = buildEnergyHistoryPath([
      { x: 10, y: 20, capturedAt: "2026-08-03T10:00:00Z" },
      { x: 20, y: 30, capturedAt: "2026-08-03T10:00:05Z" },
      { x: 30, y: 40, capturedAt: "2026-08-03T10:01:00Z" },
    ]);

    expect(path).toBe("M10.00 20.00 L20.00 30.00 M30.00 40.00");
  });

  it("keeps normal downsampled 24-hour points connected", () => {
    const points = Array.from({ length: 6 }, (_, index) => ({
      x: index * 10,
      y: index * 5,
      capturedAt: new Date(Date.parse("2026-08-03T10:00:00Z") + index * 363_000).toISOString(),
    }));

    expect(resolveEnergyHistoryGapMs(points)).toBe(1_089_000);
    expect(buildEnergyHistoryPath(points).match(/M/g)).toHaveLength(1);
  });

  it("still breaks a long outage relative to the sampled cadence", () => {
    const start = Date.parse("2026-08-03T10:00:00Z");
    const offsets = [0, 363_000, 726_000, 1_089_000, 1_452_000, 3_000_000];
    const points = offsets.map((offset, index) => ({
      x: index * 10,
      y: index * 5,
      capturedAt: new Date(start + offset).toISOString(),
    }));

    expect(buildEnergyHistoryPath(points).match(/M/g)).toHaveLength(2);
  });
});
