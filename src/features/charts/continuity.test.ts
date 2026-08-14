import { describe, expect, it } from "vitest";

import { buildChartSegments, deriveChartSourceGapMs, type ChartContinuitySample } from "./continuity";
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

  it("uses observed cadence so a normal 30-second schedule with jitter does not create false gaps", () => {
    const samples = [
      sample("a", 0, 1),
      sample("b", 30_000, 2),
      sample("c", 61_000, 3),
      sample("d", 91_000, 4),
    ];

    expect(deriveChartSourceGapMs(samples)).toBe(90_000);
    expect(buildChartSegments(identity, samples)).toHaveLength(1);
  });

  it("still exposes a real silent source gap once the normal cadence is established", () => {
    const samples = [
      sample("a", 0, 1),
      sample("b", 5_000, 2),
      sample("c", 10_000, 3),
      sample("d", 15_000, 4),
      sample("e", 120_000, 5),
    ];
    const segments = buildChartSegments(identity, samples);

    expect(segments).toHaveLength(2);
    expect(segments[1].precedingBreak?.reason).toBe("source_gap");
  });

  it("deduplicates repeated event identities and keeps a stable active segment id as the tail grows", () => {
    const first = buildChartSegments(identity, [sample("a", 0, 1), sample("b", 5_000, 2)]);
    const second = buildChartSegments(identity, [
      sample("a", 0, 1),
      sample("b", 5_000, 2),
      sample("b", 5_000, 2),
      sample("c", 10_000, 3),
    ]);

    expect(second[0].points.map((point) => point.id)).toEqual(["a", "b", "c"]);
    expect(second[0].id).toBe(first[0].id);
  });

  it("omits malformed timestamps before renderer input", () => {
    const segments = buildChartSegments(identity, [
      sample("a", 0, 1),
      sample("invalid-time", Number.NaN, 99),
      sample("b", 5_000, 2),
    ]);

    expect(segments.flatMap((segment) => segment.points).map((point) => point.id)).toEqual(["a", "b"]);
  });
});
