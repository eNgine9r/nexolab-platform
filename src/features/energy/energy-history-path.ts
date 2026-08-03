export const ENERGY_HISTORY_GAP_MS = 30_000;

export interface EnergyHistoryPathPoint {
  x: number;
  y: number;
  capturedAt: string;
}

export function buildEnergyHistoryPath(
  points: readonly EnergyHistoryPathPoint[],
  gapMs = ENERGY_HISTORY_GAP_MS,
): string {
  return points
    .map((point, index) => {
      const capturedAt = Date.parse(point.capturedAt);
      const previousCapturedAt =
        index === 0 ? Number.NaN : Date.parse(points[index - 1].capturedAt);
      const startsSegment =
        index === 0 ||
        !Number.isFinite(capturedAt) ||
        !Number.isFinite(previousCapturedAt) ||
        capturedAt - previousCapturedAt > gapMs;
      return `${startsSegment ? "M" : "L"}${point.x.toFixed(2)} ${point.y.toFixed(2)}`;
    })
    .join(" ");
}
