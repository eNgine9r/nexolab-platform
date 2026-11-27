import { chartSeriesKey, type ChartCursorInspection, type ChartPoint, type ChartSeries } from "./domain";
import type { ChartRendererScene } from "./renderer-adapter";

const DEFAULT_CURSOR_TOLERANCE_MS = 30_000;
const CURSOR_CADENCE_TOLERANCE_RATIO = 0.75;

interface SeriesInspectionIndex {
  /** Every point of every segment, by timestamp then id (the documented tie order). */
  points: ChartPoint[];
  times: Float64Array;
  /** Open intervals between consecutive non-empty segments (explicit continuity gaps). */
  gaps: Array<[number, number]>;
  toleranceMs: number;
}

/**
 * #1866: built once per series object (scenes are immutable and memoized), not on every pointer
 * move. Sorting every cadence delta and scanning every point of every series per inspection made
 * each cursor commit O(n log n) over all channels.
 */
const indexCache = new WeakMap<ChartSeries, SeriesInspectionIndex>();

function seriesIndex(series: ChartSeries): SeriesInspectionIndex {
  const cached = indexCache.get(series);
  if (cached) return cached;
  const points = series.segments
    .flatMap((segment) => segment.points)
    .filter((point) => Number.isFinite(point.timestampMs))
    .sort((left, right) => left.timestampMs - right.timestampMs || left.id.localeCompare(right.id));
  const nonEmpty = series.segments
    .filter((segment) => segment.points.length > 0)
    .sort(
      (left, right) =>
        left.points[0].timestampMs - right.points[0].timestampMs || left.id.localeCompare(right.id),
    );
  const gaps: Array<[number, number]> = [];
  for (let index = 1; index < nonEmpty.length; index += 1) {
    gaps.push([nonEmpty[index - 1].points.at(-1)!.timestampMs, nonEmpty[index].points[0].timestampMs]);
  }
  const deltas: number[] = [];
  for (const segment of series.segments) {
    for (let index = 1; index < segment.points.length; index += 1) {
      const delta = segment.points[index].timestampMs - segment.points[index - 1].timestampMs;
      if (Number.isFinite(delta) && delta > 0) deltas.push(delta);
    }
  }
  deltas.sort((left, right) => left - right);
  let toleranceMs = DEFAULT_CURSOR_TOLERANCE_MS;
  if (deltas.length > 0) {
    const middle = Math.floor(deltas.length / 2);
    const median = deltas.length % 2 === 0 ? (deltas[middle - 1] + deltas[middle]) / 2 : deltas[middle];
    toleranceMs = Math.max(DEFAULT_CURSOR_TOLERANCE_MS, median * CURSOR_CADENCE_TOLERANCE_RATIO);
  }
  const index: SeriesInspectionIndex = {
    points,
    times: Float64Array.from(points, (point) => point.timestampMs),
    gaps,
    toleranceMs,
  };
  indexCache.set(series, index);
  return index;
}

function lowerBound(values: ArrayLike<number>, target: number): number {
  let low = 0;
  let high = values.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (values[middle] < target) low = middle + 1;
    else high = middle;
  }
  return low;
}

function cursorFallsInsideExplicitGap(index: SeriesInspectionIndex, timestampMs: number): boolean {
  for (const [from, to] of index.gaps) {
    if (timestampMs > from && timestampMs < to) return true;
  }
  return false;
}

function seriesCursorToleranceMs(series: ChartSeries): number {
  return seriesIndex(series).toleranceMs;
}

/** Nearest point by binary search; ties prefer the earlier timestamp, then the smaller id. */
function nearestPoint(series: ChartSeries, timestampMs: number): ChartPoint | null {
  const index = seriesIndex(series);
  if (index.points.length === 0 || cursorFallsInsideExplicitGap(index, timestampMs)) return null;
  const after = lowerBound(index.times, timestampMs);
  let best = -1;
  if (after < index.times.length) best = after;
  if (after > 0) {
    // The earliest-id point of the previous timestamp group.
    const previous = lowerBound(index.times, index.times[after - 1]);
    if (
      best < 0 ||
      Math.abs(index.times[previous] - timestampMs) <= Math.abs(index.times[best] - timestampMs)
    ) {
      best = previous;
    }
  }
  return best < 0 ? null : index.points[best];
}

export function inspectChartAtTimestamp(
  scene: ChartRendererScene,
  timestampMs: number,
  { withinObservedSpan = false }: { withinObservedSpan?: boolean } = {},
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
        const observed =
          !withinObservedSpan ||
          series.segments.some(
            ({ points }) =>
              points.length > 0 &&
              timestampMs >= points[0].timestampMs &&
              timestampMs <= points.at(-1)!.timestampMs,
          );
        const nearest = observed ? nearestPoint(series, timestampMs) : null;
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
