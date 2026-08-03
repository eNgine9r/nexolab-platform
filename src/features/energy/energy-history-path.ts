export const ENERGY_HISTORY_GAP_MS = 30_000;
const ENERGY_HISTORY_GAP_MULTIPLIER = 3;
const MINIMUM_CADENCE_SAMPLE_COUNT = 4;

export interface EnergyHistoryPathPoint {
  x: number;
  y: number;
  capturedAt: string;
}

function median(values: readonly number[]): number {
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 1) return sorted[middle];
  return (sorted[middle - 1] + sorted[middle]) / 2;
}

export function resolveEnergyHistoryGapMs(
  points: readonly EnergyHistoryPathPoint[],
  minimumGapMs = ENERGY_HISTORY_GAP_MS,
): number {
  const intervals = points
    .slice(1)
    .map((point, index) => Date.parse(point.capturedAt) - Date.parse(points[index].capturedAt))
    .filter((interval) => Number.isFinite(interval) && interval > 0);

  if (intervals.length < MINIMUM_CADENCE_SAMPLE_COUNT) return minimumGapMs;

  return Math.max(minimumGapMs, median(intervals) * ENERGY_HISTORY_GAP_MULTIPLIER);
}

export function buildEnergyHistoryPath(
  points: readonly EnergyHistoryPathPoint[],
  minimumGapMs = ENERGY_HISTORY_GAP_MS,
): string {
  const gapMs = resolveEnergyHistoryGapMs(points, minimumGapMs);

  return points
    .map((point, index) => {
      const capturedAt = Date.parse(point.capturedAt);
      const previousCapturedAt = index === 0 ? Number.NaN : Date.parse(points[index - 1].capturedAt);
      const startsSegment =
        index === 0 ||
        !Number.isFinite(capturedAt) ||
        !Number.isFinite(previousCapturedAt) ||
        capturedAt - previousCapturedAt > gapMs;
      return `${startsSegment ? "M" : "L"}${point.x.toFixed(2)} ${point.y.toFixed(2)}`;
    })
    .join(" ");
}
