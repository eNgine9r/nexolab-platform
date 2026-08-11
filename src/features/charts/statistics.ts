import type { ChartPoint, ChartStatistics } from "./domain";

export function calculateChartStatistics(
  points: readonly ChartPoint[],
  scope: ChartStatistics["scope"],
  fromMs: number,
  toMs: number,
): ChartStatistics {
  const samples = points.filter(
    (point) =>
      point.quality === "valid" &&
      Number.isFinite(point.value) &&
      point.timestampMs >= fromMs &&
      point.timestampMs <= toMs,
  );
  if (samples.length === 0) {
    return { current: null, min: null, max: null, average: null, sampleCount: 0, scope, fromMs, toMs };
  }
  const values = samples.map((point) => point.value);
  const current = samples.reduce((latest, point) =>
    point.timestampMs > latest.timestampMs ? point : latest,
  );
  return {
    current: current.value,
    min: Math.min(...values),
    max: Math.max(...values),
    average: values.reduce((sum, value) => sum + value, 0) / values.length,
    sampleCount: values.length,
    scope,
    fromMs,
    toMs,
  };
}
