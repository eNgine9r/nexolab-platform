import { chartSeriesKey, type ChartCursorInspection, type ChartPoint, type ChartSeries } from "./domain";
import type { ChartRendererScene } from "./renderer-adapter";

const DEFAULT_CURSOR_TOLERANCE_MS = 30_000;
const CURSOR_CADENCE_TOLERANCE_RATIO = 0.75;

function cursorFallsInsideExplicitGap(series: ChartSeries, timestampMs: number): boolean {
  const nonEmptySegments = series.segments
    .filter((segment) => segment.points.length > 0)
    .sort(
      (left, right) =>
        left.points[0].timestampMs - right.points[0].timestampMs || left.id.localeCompare(right.id),
    );
  for (let index = 1; index < nonEmptySegments.length; index += 1) {
    const previousPoint = nonEmptySegments[index - 1].points.at(-1);
    const nextPoint = nonEmptySegments[index].points[0];
    if (
      previousPoint &&
      nextPoint &&
      timestampMs > previousPoint.timestampMs &&
      timestampMs < nextPoint.timestampMs
    ) {
      return true;
    }
  }
  return false;
}

function seriesCursorToleranceMs(series: ChartSeries): number {
  const deltas = series.segments
    .flatMap((segment) =>
      segment.points.slice(1).map((point, index) => point.timestampMs - segment.points[index].timestampMs),
    )
    .filter((delta) => Number.isFinite(delta) && delta > 0)
    .sort((left, right) => left - right);
  if (deltas.length === 0) return DEFAULT_CURSOR_TOLERANCE_MS;
  const middle = Math.floor(deltas.length / 2);
  const median = deltas.length % 2 === 0 ? (deltas[middle - 1] + deltas[middle]) / 2 : deltas[middle];
  return Math.max(DEFAULT_CURSOR_TOLERANCE_MS, median * CURSOR_CADENCE_TOLERANCE_RATIO);
}

function nearestPoint(series: ChartSeries, timestampMs: number): ChartPoint | null {
  if (cursorFallsInsideExplicitGap(series, timestampMs)) return null;
  let nearest: ChartPoint | null = null;
  for (const segment of series.segments) {
    for (const point of segment.points) {
      if (
        nearest === null ||
        Math.abs(point.timestampMs - timestampMs) < Math.abs(nearest.timestampMs - timestampMs) ||
        (Math.abs(point.timestampMs - timestampMs) === Math.abs(nearest.timestampMs - timestampMs) &&
          (point.timestampMs < nearest.timestampMs ||
            (point.timestampMs === nearest.timestampMs && point.id.localeCompare(nearest.id) < 0)))
      ) {
        nearest = point;
      }
    }
  }
  return nearest;
}

export function inspectChartAtTimestamp(
  scene: ChartRendererScene,
  timestampMs: number,
): ChartCursorInspection {
  if (
    scene.cursorToleranceMs !== undefined &&
    (!Number.isFinite(scene.cursorToleranceMs) || scene.cursorToleranceMs < 0)
  ) {
    throw new Error("Chart cursor tolerance must be a non-negative finite number");
  }
  return {
    timestampMs,
    series: scene.series
      .filter((series) => series.visible)
      .map((series) => {
        const nearest = nearestPoint(series, timestampMs);
        const toleranceMs = scene.cursorToleranceMs ?? seriesCursorToleranceMs(series);
        return {
          seriesKey: chartSeriesKey(series.identity),
          point: nearest && Math.abs(nearest.timestampMs - timestampMs) <= toleranceMs ? nearest : null,
          freshness: series.freshness,
        };
      }),
  };
}

export function chartInspectionTimestamps(scene: ChartRendererScene): number[] {
  return [
    ...new Set(
      scene.series
        .filter((series) => series.visible)
        .flatMap((series) =>
          series.segments.flatMap((segment) => segment.points.map((point) => point.timestampMs)),
        )
        .filter(Number.isFinite),
    ),
  ].sort((left, right) => left - right);
}
