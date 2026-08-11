import type { ChartPoint, ChartSegment } from "./domain";

export class ChartReductionBudgetError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ChartReductionBudgetError";
  }
}

export interface ChartReductionOptions {
  maximumPoints: number;
  bucketOriginMs?: number;
}

function pointKey(point: ChartPoint): string {
  return point.sourceEventId ? `event:${point.sourceEventId}` : `point:${point.id}`;
}

function isPinned(point: ChartPoint): boolean {
  return (point.pinReasons?.length ?? 0) > 0;
}

function deduplicate(points: readonly ChartPoint[]): ChartPoint[] {
  const byKey = new Map<string, ChartPoint>();
  for (const point of points) {
    const key = pointKey(point);
    const existing = byKey.get(key);
    if (!existing || point.timestampMs < existing.timestampMs) byKey.set(key, point);
  }
  return [...byKey.values()].sort(
    (left, right) => left.timestampMs - right.timestampMs || left.id.localeCompare(right.id),
  );
}

function extrema(points: readonly ChartPoint[]): ChartPoint[] {
  if (points.length === 0) return [];
  let minimum = points[0];
  let maximum = points[0];
  for (const point of points.slice(1)) {
    if (
      point.value < minimum.value ||
      (point.value === minimum.value && point.timestampMs < minimum.timestampMs)
    ) {
      minimum = point;
    }
    if (
      point.value > maximum.value ||
      (point.value === maximum.value && point.timestampMs < maximum.timestampMs)
    ) {
      maximum = point;
    }
  }
  return minimum.id === maximum.id ? [minimum] : [minimum, maximum];
}

function reduceSegment(segment: ChartSegment, budget: number, bucketOriginMs?: number): ChartSegment {
  const source = deduplicate(segment.points);
  if (source.length <= budget) return { ...segment, points: source };
  if (budget < 1) throw new ChartReductionBudgetError("Every non-empty segment requires a point budget");

  const required = deduplicate([
    source[0],
    ...(source.length > 1 ? [source.at(-1)!] : []),
    ...source.filter(isPinned),
  ]);
  if (required.length > budget) {
    throw new ChartReductionBudgetError(
      `Evidence pins require ${required.length} points but the segment budget is ${budget}`,
    );
  }

  const available = budget - required.length;
  if (available === 0) return { ...segment, points: required };
  const candidatePoints = source.filter(
    (point) => !required.some((item) => pointKey(item) === pointKey(point)),
  );
  const bucketCount = Math.max(1, Math.floor(available / 2));
  const from = bucketOriginMs ?? source[0].timestampMs;
  const duration = Math.max(1, source.at(-1)!.timestampMs - from + 1);
  const bucketMs = Math.max(1, Math.ceil(duration / bucketCount));
  const buckets = new Map<number, ChartPoint[]>();
  for (const point of candidatePoints) {
    const index = Math.max(0, Math.min(bucketCount - 1, Math.floor((point.timestampMs - from) / bucketMs)));
    buckets.set(index, [...(buckets.get(index) ?? []), point]);
  }

  const selected = deduplicate([
    ...required,
    ...[...buckets.entries()]
      .sort(([left], [right]) => left - right)
      .flatMap(([, points]) => extrema(points)),
  ]);
  if (selected.length <= budget) return { ...segment, points: selected };

  const requiredKeys = new Set(required.map(pointKey));
  const optional = selected.filter((point) => !requiredKeys.has(pointKey(point)));
  const optionalBudget = budget - required.length;
  return { ...segment, points: deduplicate([...required, ...optional.slice(0, optionalBudget)]) };
}

export function reduceChartSegments(
  segments: readonly ChartSegment[],
  options: ChartReductionOptions,
): ChartSegment[] {
  if (!Number.isInteger(options.maximumPoints) || options.maximumPoints < 1) {
    throw new ChartReductionBudgetError("maximumPoints must be a positive integer");
  }
  const nonEmpty = segments.filter((segment) => segment.points.length > 0);
  if (nonEmpty.length > options.maximumPoints) {
    throw new ChartReductionBudgetError("The point budget cannot preserve one point per continuity segment");
  }

  const minimumBudgets = nonEmpty.map(
    (segment) =>
      deduplicate([
        segment.points[0],
        ...(segment.points.length > 1 ? [segment.points.at(-1)!] : []),
        ...segment.points.filter(isPinned),
      ]).length,
  );
  const minimumTotal = minimumBudgets.reduce((sum, value) => sum + value, 0);
  if (minimumTotal > options.maximumPoints) {
    throw new ChartReductionBudgetError(
      `Evidence boundaries and pins require ${minimumTotal} points but the series budget is ${options.maximumPoints}`,
    );
  }

  let remaining = options.maximumPoints - minimumTotal;
  return nonEmpty.map((segment, index) => {
    const sourceCapacity = Math.max(0, segment.points.length - minimumBudgets[index]);
    const extra = Math.min(sourceCapacity, Math.ceil(remaining / (nonEmpty.length - index)));
    remaining -= extra;
    return reduceSegment(segment, minimumBudgets[index] + extra, options.bucketOriginMs);
  });
}
