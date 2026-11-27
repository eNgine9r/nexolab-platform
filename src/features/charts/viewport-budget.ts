/**
 * Adaptive viewport point budget (#1844).
 *
 * The rendered-points budget of a zoomed viewport follows what the screen and the renderer can
 * actually show instead of a fixed 240 points per series:
 *
 * - plot width: the evidence-preserving reducer keeps first/min/max/last per bucket, so about two
 *   points per horizontal pixel already show every extreme the plot can resolve; more is wasted;
 * - visible series: the total across a page is bounded, because render cost grows with it;
 * - measured renderer cost: the total target follows the real cost of full chart renders on this
 *   device (an operator PC renders more than a Raspberry Pi), within fixed bounds;
 * - available originals: when the window holds fewer original measurements than the budget, the
 *   detail paths already return every one of them (no reduction at all).
 *
 * Manual density modes (#1620) stay exactly what the operator chose. The budget is soft for
 * mandatory evidence: the reducers still keep gap boundaries, extrema and pinned events.
 */

import {
  CHART_AUTO_AGGREGATE_POINTS,
  CHART_AUTO_MINIMUM_POINTS,
  resolveChartPointBudget,
  type ChartDensityMode,
} from "./density";
import { CHART_POINT_BUDGET_DEFAULT } from "./point-budget";

/** Rendered points per horizontal plot pixel at which a min/max reduction loses nothing visible. */
export const CHART_POINTS_PER_PIXEL = 2;
/** Plot width assumed before any chart reported its size (a typical operator monitor). */
export const CHART_DEFAULT_PLOT_WIDTH_PX = 1_100;
/** Widths are quantized so a few pixels of resize never change a budget (and never re-request). */
const PLOT_WIDTH_STEP_PX = 128;
/** Frame-time target of one full chart render. */
export const CHART_RENDER_TARGET_MS = 16;
/** Bounds of the measured page-wide budget: never below half nor above 2.5× the accepted Pi target. */
export const CHART_ADAPTIVE_AGGREGATE_MIN = Math.round(CHART_AUTO_AGGREGATE_POINTS / 2);
export const CHART_ADAPTIVE_AGGREGATE_MAX = Math.round(CHART_AUTO_AGGREGATE_POINTS * 2.5);
/** Renders with fewer points say little about per-point cost. */
const MIN_MEASURED_POINTS = 500;
const MIN_MEASUREMENTS = 3;
const COST_SMOOTHING = 0.3;

// ----------------------------------------------------------------------------- plot width

const plotWidths = new Map<string, number>();
const listeners = new Set<() => void>();
let publishedWidth = CHART_DEFAULT_PLOT_WIDTH_PX;

function quantize(widthPx: number): number {
  return Math.max(PLOT_WIDTH_STEP_PX, Math.round(widthPx / PLOT_WIDTH_STEP_PX) * PLOT_WIDTH_STEP_PX);
}

function publishPlotWidth(): void {
  const widest = Math.max(0, ...plotWidths.values());
  const next = widest > 0 ? quantize(widest) : CHART_DEFAULT_PLOT_WIDTH_PX;
  if (next === publishedWidth) return;
  publishedWidth = next;
  for (const listener of listeners) listener();
}

/** A mounted chart reports its plot-area width (px); `null` when it unmounts. */
export function reportChartPlotWidth(chartId: string, widthPx: number | null): void {
  if (widthPx === null || !(widthPx > 0)) plotWidths.delete(chartId);
  else plotWidths.set(chartId, widthPx);
  publishPlotWidth();
}

/** The widest mounted plot area, quantized; the typical-monitor default before any chart reported. */
export function chartPlotWidthPx(): number {
  return publishedWidth;
}

export function subscribeChartPlotWidth(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// ----------------------------------------------------------------------------- renderer cost

let msPerPoint: number | null = null;
let measurements = 0;
let publishedAggregate = CHART_AUTO_AGGREGATE_POINTS;
/** A measured total replaces the published one only when it differs by more than this share. */
const AGGREGATE_HYSTERESIS = 0.25;
/** Published totals are multiples of this, so render-time noise never yields a new budget. */
const AGGREGATE_STEP = 480;

/** Records one full chart render (all series rebuilt) of `points` rendered points. */
export function recordChartRenderCost(points: number, durationMs: number): void {
  if (!(points >= MIN_MEASURED_POINTS) || !(durationMs >= 0) || !Number.isFinite(durationMs)) return;
  const sample = durationMs / points;
  msPerPoint = msPerPoint === null ? sample : msPerPoint + (sample - msPerPoint) * COST_SMOOTHING;
  measurements += 1;
}

/**
 * Page-wide rendered-points target from the measured render cost: what fits one frame, bounded to
 * [½, 2.5] × the accepted Raspberry Pi target. Unmeasured devices keep the accepted target.
 *
 * Stable by construction (#1844 review): the published total moves only when the measured one
 * differs by more than 25 %, and then to a multiple of 480 points. Ordinary render-time variation
 * therefore never changes a budget, so a refreshed detail can never feed a new measurement that
 * refreshes it again.
 */
export function adaptiveAggregatePoints(): number {
  if (msPerPoint === null || measurements < MIN_MEASUREMENTS || !(msPerPoint > 0)) return publishedAggregate;
  const fitting = Math.min(
    CHART_ADAPTIVE_AGGREGATE_MAX,
    Math.max(CHART_ADAPTIVE_AGGREGATE_MIN, CHART_RENDER_TARGET_MS / msPerPoint),
  );
  if (Math.abs(fitting - publishedAggregate) > publishedAggregate * AGGREGATE_HYSTERESIS) {
    publishedAggregate = Math.min(
      CHART_ADAPTIVE_AGGREGATE_MAX,
      Math.max(CHART_ADAPTIVE_AGGREGATE_MIN, Math.round(fitting / AGGREGATE_STEP) * AGGREGATE_STEP),
    );
  }
  return publishedAggregate;
}

/** Test seam: forget measured cost and reported widths. */
export function resetChartViewportBudgetState(): void {
  msPerPoint = null;
  measurements = 0;
  publishedAggregate = CHART_AUTO_AGGREGATE_POINTS;
  plotWidths.clear();
  publishedWidth = CHART_DEFAULT_PLOT_WIDTH_PX;
}

// ----------------------------------------------------------------------------- budget

/**
 * Rendered points per series for a zoomed viewport. Auto: two points per plot pixel, bounded by
 * the page-wide (measured) total shared by `seriesCount` series, never below the readability
 * floor nor below the accepted default where the total allows it. Manual: the operator's mode.
 */
export function resolveViewportPointBudget({
  mode,
  seriesCount,
  plotWidthPx = chartPlotWidthPx(),
  aggregatePoints = adaptiveAggregatePoints(),
}: {
  mode: ChartDensityMode;
  seriesCount: number;
  plotWidthPx?: number;
  aggregatePoints?: number;
}): number {
  if (mode !== "auto") return resolveChartPointBudget(mode, seriesCount).perSeries;
  const count = Math.max(1, Math.floor(Number.isFinite(seriesCount) ? seriesCount : 1));
  const screen = Math.max(CHART_POINT_BUDGET_DEFAULT, Math.round(plotWidthPx * CHART_POINTS_PER_PIXEL));
  const share = Math.floor(aggregatePoints / count);
  return Math.max(CHART_AUTO_MINIMUM_POINTS, Math.min(screen, share));
}
