import { isEnergyHistorySegmentStart } from "@/features/energy/energy-history-segment";

export interface EnergyHistoryPathPoint {
  id: string;
  x: number;
  y: number;
  capturedAt: string;
}

export function buildEnergyHistoryPath(points: readonly EnergyHistoryPathPoint[]): string {
  return points
    .map((point, index) => {
      const capturedAt = Date.parse(point.capturedAt);
      const startsSegment =
        index === 0 ||
        isEnergyHistorySegmentStart(point.id) ||
        !Number.isFinite(capturedAt);
      return `${startsSegment ? "M" : "L"}${point.x.toFixed(2)} ${point.y.toFixed(2)}`;
    })
    .join(" ");
}
