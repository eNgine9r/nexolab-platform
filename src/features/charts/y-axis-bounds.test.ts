import { describe, expect, it } from "vitest";

import { chartSeriesKey, type ChartSeries, type ChartThreshold } from "./domain";
import { buildChartYAxisModel } from "./units";
import {
  computeChartYAxisBounds,
  niceYAxisBounds,
  visibleSeriesExtent,
  type ChartYAxisBounds,
} from "./y-axis-bounds";

const HOUR = 3_600_000;
const T0 = Date.UTC(2026, 10, 20, 0, 0, 0);

function series(
  channel: string,
  values: ReadonlyArray<readonly [number, number]>,
  options: { unit?: string; visible?: boolean; precision?: number; segments?: number[] } = {},
): ChartSeries {
  const identity = {
    nodeId: "node",
    equipmentId: "equipment",
    channelId: channel,
    metric: options.unit === "V" ? "voltage" : "temperature.probe",
    nativeUnit: options.unit ?? "°C",
  };
  const key = chartSeriesKey(identity);
  const points = values.map(([timestampMs, value], index) => ({
    id: `${channel}-${index}`,
    timestampMs,
    value,
    quality: "valid" as const,
  }));
  // Optional split into continuity segments at the given point indexes.
  const cuts = [0, ...(options.segments ?? []), points.length];
  const segments = cuts.slice(0, -1).map((start, index) => ({
    id: `${channel}-segment-${index}`,
    seriesKey: key,
    points: points.slice(start, cuts[index + 1]),
  }));
  return {
    identity,
    name: channel,
    colorToken: "#00C6E0",
    dashStyle: "solid",
    markerShape: "circle",
    freshness: "historical",
    segments,
    visible: options.visible ?? true,
    semanticMode: "instantaneous",
    displayPrecision: options.precision ?? 1,
  } as ChartSeries;
}

/** Seven days at 10-minute spacing: 20–30 °C over the week, ~25.5–29.1 °C in the last 70 minutes. */
function operatorScreenshotSeries(): ChartSeries[] {
  const week: Array<[number, number]> = [];
  for (let minute = 0; minute <= 7 * 24 * 60; minute += 10) {
    const timestampMs = T0 + minute * 60_000;
    const inLastHour = minute >= 7 * 24 * 60 - 70;
    const value = inLastHour ? 25.5 + ((minute % 70) / 70) * 3.6 : 20 + 10 * Math.abs(Math.sin(minute / 997));
    week.push([timestampMs, Math.round(value * 10) / 10]);
  }
  return [
    series("probe-1", week),
    series(
      "probe-2",
      week.map(([time, value]) => [time, value - 0.4]),
    ),
  ];
}

function bounds(input: Parameters<typeof computeChartYAxisBounds>[0]): ChartYAxisBounds[] {
  return [...computeChartYAxisBounds(input).values()];
}

describe("#1843 visible-window Y axis bounds", () => {
  it("fits the operator's zoomed hour instead of the whole week (screenshot regression)", () => {
    const all = operatorScreenshotSeries();
    const end = T0 + 7 * 24 * HOUR;
    const visible = { fromMs: end - 70 * 60_000, toMs: end };
    const full = { fromMs: T0, toMs: end };
    const [axis] = bounds({
      series: all,
      axisModel: buildChartYAxisModel(all),
      visibleDomain: visible,
      fullDomain: full,
    });
    expect(axis.dataMin).toBeGreaterThanOrEqual(25);
    expect(axis.dataMax).toBeLessThanOrEqual(29.2);
    // Before #1843 the axis stayed at the week's 20–30 °C.
    expect(axis.min).toBeGreaterThanOrEqual(24);
    expect(axis.max).toBeLessThanOrEqual(30);
    expect(axis.max - axis.min).toBeLessThanOrEqual(6);
    expect(axis.min).toBeLessThanOrEqual(axis.dataMin!);
    expect(axis.max).toBeGreaterThanOrEqual(axis.dataMax!);

    const [fixed] = bounds({
      series: all,
      axisModel: buildChartYAxisModel(all),
      visibleDomain: visible,
      fullDomain: full,
      scale: { mode: "full" },
    });
    expect(fixed.min).toBeLessThanOrEqual(19.6);
    expect(fixed.max).toBeGreaterThanOrEqual(30);
  });

  it("ignores hidden series and fits each unit on its own axis", () => {
    const temperature = series("t", [
      [T0, 5],
      [T0 + HOUR, 6],
    ]);
    const hiddenSpike = series(
      "spike",
      [
        [T0, 90],
        [T0 + HOUR, 95],
      ],
      { visible: false },
    );
    const voltage = series(
      "v",
      [
        [T0, 229],
        [T0 + HOUR, 231],
      ],
      { unit: "V" },
    );
    const all = [temperature, hiddenSpike, voltage];
    const result = computeChartYAxisBounds({
      series: all,
      axisModel: buildChartYAxisModel(all),
      visibleDomain: { fromMs: T0, toMs: T0 + HOUR },
      fullDomain: { fromMs: T0, toMs: T0 + HOUR },
    });
    const byUnit = [...result.values()].sort((left, right) => left.min - right.min);
    expect(byUnit).toHaveLength(2);
    expect(byUnit[0].max).toBeLessThan(10);
    expect(byUnit[1].min).toBeGreaterThan(200);
  });

  it("includes where a line enters and leaves the window, never points beyond it", () => {
    const line = series("t", [
      [T0, 0],
      [T0 + 10 * HOUR, 100],
    ]);
    // Deep zoom between two measurements: the drawn line runs from 40 to 50.
    expect(visibleSeriesExtent(line, { fromMs: T0 + 4 * HOUR, toMs: T0 + 5 * HOUR })).toEqual({
      min: 40,
      max: 50,
    });
    // A continuity break: the line does not cross it, so nothing is drawn in between.
    const broken = series(
      "b",
      [
        [T0, 0],
        [T0 + 10 * HOUR, 100],
      ],
      { segments: [1] },
    );
    expect(visibleSeriesExtent(broken, { fromMs: T0 + 4 * HOUR, toMs: T0 + 5 * HOUR })).toBeNull();
  });

  it("handles constant, negative and nearly equal values", () => {
    const constant = niceYAxisBounds(25, 25, { resolution: 0.1 });
    expect(constant.min).toBeLessThan(25);
    expect(constant.max).toBeGreaterThan(25);

    const negative = niceYAxisBounds(-21.4, -17.9, { resolution: 0.1 });
    expect(negative.min).toBeLessThanOrEqual(-21.4);
    expect(negative.max).toBeGreaterThanOrEqual(-17.9);
    expect(negative.max).toBeLessThan(0);

    // 0.02 °C of noise on a 0.1 °C display is not stretched over the whole plot.
    const close = niceYAxisBounds(25.01, 25.03, { resolution: 0.1 });
    expect(close.max - close.min).toBeGreaterThanOrEqual(0.5);

    const zero = niceYAxisBounds(0, 0);
    expect(zero.min).toBeLessThan(0);
    expect(zero.max).toBeGreaterThan(0);
  });

  it("aligns bounds to readable ticks", () => {
    const result = niceYAxisBounds(25.53, 29.08, { resolution: 0.1 });
    expect(Math.abs(result.min / result.interval - Math.round(result.min / result.interval))).toBeLessThan(
      1e-9,
    );
    expect(Math.abs(result.max / result.interval - Math.round(result.max / result.interval))).toBeLessThan(
      1e-9,
    );
    expect((result.max - result.min) / result.interval).toBeLessThanOrEqual(10);
  });

  it("keeps the axis while live samples still fill it, refits when they do not", () => {
    const first = [
      series("t", [
        [T0, 20],
        [T0 + HOUR, 25],
      ]),
    ];
    const axisModel = buildChartYAxisModel(first);
    const domain = { fromMs: T0, toMs: T0 + 2 * HOUR };
    const initial = computeChartYAxisBounds({
      series: first,
      axisModel,
      visibleDomain: domain,
      fullDomain: domain,
    });
    const slightlyMore = [
      series("t", [
        [T0, 20],
        [T0 + HOUR, 25],
        [T0 + 1.5 * HOUR, 24.6],
      ]),
    ];
    const kept = computeChartYAxisBounds({
      series: slightlyMore,
      axisModel,
      visibleDomain: domain,
      fullDomain: domain,
      previous: initial,
    });
    expect([...kept.values()][0].min).toBe([...initial.values()][0].min);
    expect([...kept.values()][0].max).toBe([...initial.values()][0].max);

    const excursion = [
      series("t", [
        [T0, 20],
        [T0 + HOUR, 25],
        [T0 + 1.5 * HOUR, 31],
      ]),
    ];
    const refit = computeChartYAxisBounds({
      series: excursion,
      axisModel,
      visibleDomain: domain,
      fullDomain: domain,
      previous: initial,
    });
    expect([...refit.values()][0].max).toBeGreaterThanOrEqual(31);
  });

  it("pulls near thresholds into view and flags distant ones", () => {
    const probe = series("t", [
      [T0, 24],
      [T0 + HOUR, 26],
    ]);
    const key = chartSeriesKey(probe.identity);
    const thresholds: ChartThreshold[] = [
      { id: "near", seriesKey: key, kind: "upper", value: 27, label: "Верхня межа" },
      { id: "far", seriesKey: key, kind: "lower", value: -40, label: "Нижня межа" },
    ];
    const [axis] = bounds({
      series: [probe],
      axisModel: buildChartYAxisModel([probe]),
      visibleDomain: { fromMs: T0, toMs: T0 + HOUR },
      fullDomain: { fromMs: T0, toMs: T0 + HOUR },
      thresholds,
    });
    expect(axis.max).toBeGreaterThanOrEqual(27);
    expect(axis.offScaleThresholds).toEqual([
      { id: "far", label: "Нижня межа", value: -40, direction: "below" },
    ]);
  });

  it("applies manual bounds and keeps the previous axis over an empty window", () => {
    const probe = series("t", [
      [T0, 24],
      [T0 + HOUR, 26],
    ]);
    const axisModel = buildChartYAxisModel([probe]);
    const axisId = axisModel.visibleAxes[0].id;
    const domain = { fromMs: T0, toMs: T0 + HOUR };
    const [manual] = bounds({
      series: [probe],
      axisModel,
      visibleDomain: domain,
      fullDomain: domain,
      scale: { mode: "manual", manual: { [axisId]: { min: 0, max: 50 } } },
    });
    expect([manual.min, manual.max]).toEqual([0, 50]);

    const initial = computeChartYAxisBounds({
      series: [probe],
      axisModel,
      visibleDomain: domain,
      fullDomain: domain,
    });
    const gap = computeChartYAxisBounds({
      series: [probe],
      axisModel,
      visibleDomain: { fromMs: T0 + 5 * HOUR, toMs: T0 + 6 * HOUR },
      fullDomain: domain,
      previous: initial,
    });
    expect([...gap.values()][0].min).toBe([...initial.values()][0].min);
    expect([...gap.values()][0].dataMin).toBeNull();
  });
});
