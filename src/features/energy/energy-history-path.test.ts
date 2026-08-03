import { describe, expect, it } from "vitest";

import { buildEnergyHistoryPath } from "./energy-history-path";

describe("energy history path", () => {
  it("breaks the SVG path across telemetry outages", () => {
    const path = buildEnergyHistoryPath([
      { x: 10, y: 20, capturedAt: "2026-08-03T10:00:00Z" },
      { x: 20, y: 30, capturedAt: "2026-08-03T10:00:05Z" },
      { x: 30, y: 40, capturedAt: "2026-08-03T10:01:00Z" },
    ]);

    expect(path).toBe("M10.00 20.00 L20.00 30.00 M30.00 40.00");
  });
});
