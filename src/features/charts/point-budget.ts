import type { ChartSegment } from "./domain";
import { ChartReductionBudgetError, reduceChartSegments } from "./reduction";

export const CHART_POINT_BUDGET_DEFAULT = 240;

export type ChartPointBudgetSurface =
  | "overview"
  | "live-history"
  | "saved-dashboard"
  | "energy-history"
  | "refrigeration-controller"
  | "renderer-live-tail";

export interface ChartPointBudgetException {
  maximumPoints: number;
  rationale: string;
}

export const CHART_POINT_BUDGET_EXCEPTIONS: Readonly<
  Partial<Record<ChartPointBudgetSurface, ChartPointBudgetException>>
> = {};

export function chartPointBudget(surface: ChartPointBudgetSurface): number {
  const exception = CHART_POINT_BUDGET_EXCEPTIONS[surface] as ChartPointBudgetException | undefined;
  return exception?.maximumPoints ?? CHART_POINT_BUDGET_DEFAULT;
}

export function reduceChartSegmentsToPointBudget(
  segments: readonly ChartSegment[],
  surface: ChartPointBudgetSurface,
  options: { bucketOriginMs?: number } = {},
): ChartSegment[] {
  const maximumPoints = chartPointBudget(surface);
  const sourcePointCount = segments.reduce((sum, segment) => sum + segment.points.length, 0);
  if (sourcePointCount <= maximumPoints) return [...segments];

  try {
    return reduceChartSegments(segments, { maximumPoints, ...options });
  } catch (error) {
    if (!(error instanceof ChartReductionBudgetError)) throw error;
    // The budget is a performance target, never permission to discard required
    // continuity boundaries or pinned evidence. Preserve the complete evidence set
    // when the reducer proves that the target budget cannot represent it truthfully.
    return reduceChartSegments(segments, { maximumPoints: sourcePointCount, ...options });
  }
}
