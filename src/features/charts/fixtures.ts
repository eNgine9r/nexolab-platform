import { buildChartSegments, type ChartContinuitySample } from "./continuity";
import {
  CHART_SERIES_TOKENS,
  chartSeriesKey,
  type ChartSeries,
  type ChartSeriesIdentity,
  type ChartThreshold,
} from "./domain";
import type { ChartRendererScene } from "./renderer-adapter";

export const BENCHMARK_START_MS = Date.UTC(2026, 7, 11, 8, 0, 0);
export const BENCHMARK_INTERVAL_MS = 5_000;

function identity(index: number, nativeUnit = "°C", metric = "temperature.probe"): ChartSeriesIdentity {
  return {
    nodeId: "fixture-edge-01",
    equipmentId: `fixture-equipment-${Math.floor(index / 2) + 1}`,
    channelId: `fixture-channel-${index + 1}`,
    metric,
    nativeUnit,
  };
}

function samples(index: number, count: number, withEvidence: boolean): ChartContinuitySample[] {
  return Array.from({ length: count }, (_, pointIndex) => {
    const excursion = withEvidence && pointIndex === 87 ? 18 : 0;
    const value = -12 + index * 1.2 + Math.sin(pointIndex / 11) * 2.5 + excursion;
    return {
      id: `fixture-${index}-${pointIndex}`,
      sourceEventId: `fixture-event-${index}-${pointIndex}`,
      timestampMs: BENCHMARK_START_MS + pointIndex * BENCHMARK_INTERVAL_MS,
      value,
      quality: "valid" as const,
      ...(withEvidence && pointIndex === 87 ? { pinReasons: ["threshold_crossing", "alarm"] as const } : {}),
    };
  });
}

export function createBenchmarkSeries(
  index: number,
  count = 240,
  options: { withGap?: boolean; withEvidence?: boolean; nativeUnit?: string; metric?: string } = {},
): ChartSeries {
  const seriesIdentity = identity(index, options.nativeUnit, options.metric);
  const source = samples(index, count, options.withEvidence ?? false);
  if (options.withGap && source.length > 140) {
    source.splice(120, 1, {
      id: `fixture-gap-${index}`,
      sourceEventId: `fixture-gap-event-${index}`,
      timestampMs: BENCHMARK_START_MS + 120 * BENCHMARK_INTERVAL_MS,
      value: null,
      quality: "communication_error",
      freshness: "offline",
    });
  }
  const token = CHART_SERIES_TOKENS[index % CHART_SERIES_TOKENS.length];
  return {
    identity: seriesIdentity,
    name: `Fixture channel ${index + 1}`,
    colorToken: token.color,
    dashStyle: token.dashStyle,
    markerShape: token.markerShape,
    freshness: "live",
    visible: true,
    semanticMode: options.metric?.includes("energy") ? "cumulative_counter" : "instantaneous",
    segments: buildChartSegments(seriesIdentity, source, { maximumSourceGapMs: 30_000 }),
  };
}

export function createBenchmarkScene(
  seriesCount: number,
  options: { withGap?: boolean; withEvidence?: boolean } = {},
): ChartRendererScene {
  const series = Array.from({ length: seriesCount }, (_, index) =>
    createBenchmarkSeries(index, 240, options),
  );
  const thresholds: ChartThreshold[] = options.withEvidence
    ? series.map((item) => ({
        id: `threshold-${chartSeriesKey(item.identity)}`,
        seriesKey: chartSeriesKey(item.identity),
        kind: "upper",
        value: 0,
        label: "Upper laboratory limit",
      }))
    : [];
  return {
    series,
    thresholds,
    xDomain: {
      fromMs: BENCHMARK_START_MS,
      toMs: BENCHMARK_START_MS + 239 * BENCHMARK_INTERVAL_MS,
    },
  };
}

export function createSynchronizedBenchmarkScenes(): ChartRendererScene[] {
  return [
    createBenchmarkScene(2),
    {
      ...createBenchmarkScene(1),
      series: [createBenchmarkSeries(4, 240, { nativeUnit: "kPa", metric: "pressure" })],
    },
    {
      ...createBenchmarkScene(1),
      series: [createBenchmarkSeries(6, 240, { nativeUnit: "V", metric: "voltage" })],
    },
  ];
}
