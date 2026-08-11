import { describe, expect, it } from "vitest";

import { buildChartSegments, type ChartContinuitySample } from "./continuity";
import type { ChartSeriesIdentity } from "./domain";

const identity: ChartSeriesIdentity = {
  nodeId: "edge-01",
  equipmentId: "chamber-01",
  channelId: "probe-01",
  metric: "temperature.probe",
  nativeUnit: "°C",
};

function sample(
  id: string,
  timestampMs: number,
  value: number | null,
  overrides: Partial<ChartContinuitySample> = {},
): ChartContinuitySample {
  return { id, timestampMs, value, quality: "valid", ...overrides };
}

describe("chart continuity", () => {
  it("breaks at an explicit communication gap", () => {
    const segments = buildChartSegments(
      identity,
      [
        sample("a", 0, 1),
        sample("gap", 1_000, null, { explicitBreak: "explicit_gap" }),
        sample("b", 2_000, 2),
      ],
      { maximumSourceGapMs: 30_000 },
    );

    expect(segments.map((segment) => segment.points.map((point) => point.id))).toEqual([["a"], ["b"]]);
    expect(segments[1].precedingBreak?.reason).toBe("explicit_gap");
  });

  it("breaks at invalid quality and never turns it into zero", () => {
    const segments = buildChartSegments(
      identity,
      [
        sample("a", 0, -4),
        sample("fault", 1_000, null, { quality: "communication_error" }),
        sample("b", 2_000, -3),
      ],
      { maximumSourceGapMs: 30_000 },
    );

    expect(segments).toHaveLength(2);
    expect(segments.flatMap((segment) => segment.points).map((point) => point.value)).toEqual([-4, -3]);
    expect(segments[1].precedingBreak?.reason).toBe("invalid_quality");
  });

  it.each([
    ["offline", "offline"],
    ["reconnecting", "reconnect_gap"],
  ] as const)("breaks across %s delivery state", (freshness, reason) => {
    const segments = buildChartSegments(
      identity,
      [sample("a", 0, 1), sample("state", 1_000, null, { freshness }), sample("b", 2_000, 2)],
      { maximumSourceGapMs: 30_000 },
    );
    expect(segments[1].precedingBreak?.reason).toBe(reason);
  });

  it("breaks when source cadence exceeds the threshold", () => {
    const segments = buildChartSegments(identity, [sample("a", 0, 1), sample("b", 30_001, 2)], {
      maximumSourceGapMs: 30_000,
    });
    expect(segments).toHaveLength(2);
    expect(segments[1].precedingBreak?.reason).toBe("source_gap");
  });
});
