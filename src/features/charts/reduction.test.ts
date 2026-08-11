import { describe, expect, it } from "vitest";

import type { ChartPoint, ChartSegment } from "./domain";
import { ChartReductionBudgetError, reduceChartSegments } from "./reduction";

function point(
  id: string,
  timestampMs: number,
  value: number,
  overrides: Partial<ChartPoint> = {},
): ChartPoint {
  return { id, timestampMs, value, quality: "valid", ...overrides };
}

function segment(id: string, points: ChartPoint[]): ChartSegment {
  return { id, seriesKey: "series-1", points };
}

function ids(segments: readonly ChartSegment[]): string[] {
  return segments.flatMap((item) => item.points.map((point) => point.id));
}

describe("segment-aware min/max reduction", () => {
  it("preserves first and last points", () => {
    const result = reduceChartSegments(
      [
        segment(
          "a",
          Array.from({ length: 20 }, (_, index) => point(`p${index}`, index, index)),
        ),
      ],
      { maximumPoints: 6 },
    );
    expect(ids(result)).toContain("p0");
    expect(ids(result)).toContain("p19");
  });

  it("preserves local minimum and maximum", () => {
    const source = [point("first", 0, 0), point("min", 1, -20), point("max", 2, 40), point("last", 3, 1)];
    expect(ids(reduceChartSegments([segment("a", source)], { maximumPoints: 4 }))).toEqual([
      "first",
      "min",
      "max",
      "last",
    ]);
  });

  it("keeps min-before-max chronology", () => {
    const source = [point("first", 0, 0), point("min", 1, -8), point("max", 2, 9), point("last", 3, 1)];
    expect(ids(reduceChartSegments([segment("a", source)], { maximumPoints: 4 }))).toEqual([
      "first",
      "min",
      "max",
      "last",
    ]);
  });

  it("keeps max-before-min chronology", () => {
    const source = [point("first", 0, 0), point("max", 1, 9), point("min", 2, -8), point("last", 3, 1)];
    expect(ids(reduceChartSegments([segment("a", source)], { maximumPoints: 4 }))).toEqual([
      "first",
      "max",
      "min",
      "last",
    ]);
  });

  it("does not reduce across an explicit gap", () => {
    const result = reduceChartSegments(
      [
        segment("before", [point("a", 0, 1), point("b", 1, 2)]),
        segment("after", [point("c", 10, 3), point("d", 11, 4)]),
      ],
      { maximumPoints: 4 },
    );
    expect(result.map((item) => item.id)).toEqual(["before", "after"]);
    expect(result.map((item) => item.points.map((item) => item.id))).toEqual([
      ["a", "b"],
      ["c", "d"],
    ]);
  });

  it("operates only on valid renderable segment points", () => {
    const result = reduceChartSegments(
      [segment("a", [point("a", 0, 1), point("b", 1, 2), point("c", 2, 3)])],
      { maximumPoints: 2 },
    );
    expect(result[0].points.every((item) => item.quality === "valid" && Number.isFinite(item.value))).toBe(
      true,
    );
  });

  it("preserves threshold crossing context", () => {
    const crossing = point("cross", 5, 11, { pinReasons: ["threshold_crossing"] });
    const source = [
      point("first", 0, 0),
      ...Array.from({ length: 9 }, (_, index) => point(`p${index}`, index + 1, 1)),
      crossing,
      point("last", 20, 2),
    ];
    expect(ids(reduceChartSegments([segment("a", source)], { maximumPoints: 5 }))).toContain("cross");
  });

  it("deduplicates a duplicate pinned event identity", () => {
    const source = [
      point("first", 0, 0),
      point("alarm-a", 1, 5, { sourceEventId: "alarm-1", pinReasons: ["alarm"] }),
      point("alarm-b", 2, 5, { sourceEventId: "alarm-1", pinReasons: ["alarm"] }),
      point("last", 3, 0),
    ];
    const result = reduceChartSegments([segment("a", source)], { maximumPoints: 4 });
    expect(result[0].points.filter((item) => item.sourceEventId === "alarm-1")).toHaveLength(1);
  });

  it("keeps output within the requested bound", () => {
    const source = Array.from({ length: 1_000 }, (_, index) => point(`p${index}`, index, Math.sin(index)));
    const result = reduceChartSegments([segment("a", source)], { maximumPoints: 240 });
    expect(result.flatMap((item) => item.points).length).toBeLessThanOrEqual(240);
  });

  it("preserves a one-point segment", () => {
    expect(ids(reduceChartSegments([segment("a", [point("only", 1, 2)])], { maximumPoints: 1 }))).toEqual([
      "only",
    ]);
  });

  it("preserves a two-point segment", () => {
    expect(
      ids(
        reduceChartSegments([segment("a", [point("first", 1, 2), point("last", 2, 3)])], {
          maximumPoints: 2,
        }),
      ),
    ).toEqual(["first", "last"]);
  });

  it("preserves multiple independent segments", () => {
    const result = reduceChartSegments(
      [
        segment("a", [point("a1", 0, 1), point("a2", 1, 2)]),
        segment("b", [point("b1", 10, 3), point("b2", 11, 4)]),
      ],
      { maximumPoints: 4 },
    );
    expect(result).toHaveLength(2);
    expect(ids(result)).toEqual(["a1", "a2", "b1", "b2"]);
  });

  it("fails truthfully when pinned evidence exceeds the budget", () => {
    const source = [
      point("first", 0, 0),
      point("one", 1, 1, { pinReasons: ["event"] }),
      point("two", 2, 2, { pinReasons: ["event"] }),
      point("last", 3, 3),
    ];
    expect(() => reduceChartSegments([segment("a", source)], { maximumPoints: 3 })).toThrow(
      ChartReductionBudgetError,
    );
  });
});
