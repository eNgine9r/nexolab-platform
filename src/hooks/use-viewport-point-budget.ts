"use client";

import { useSyncExternalStore } from "react";

import type { ChartDensityMode } from "@/features/charts/density";
import {
  CHART_DEFAULT_PLOT_WIDTH_PX,
  chartPlotWidthPx,
  resolveViewportPointBudget,
  subscribeChartPlotWidth,
} from "@/features/charts/viewport-budget";

/**
 * #1844: rendered points per series for zoomed viewport detail, following the widest mounted
 * plot area, the series count and the measured renderer cost. It only sizes detail requests and
 * their display; it never reloads the base history (resizing a window must not re-request it).
 */
export function useViewportPointBudget(mode: ChartDensityMode, seriesCount: number): number {
  const plotWidthPx = useSyncExternalStore(
    subscribeChartPlotWidth,
    chartPlotWidthPx,
    () => CHART_DEFAULT_PLOT_WIDTH_PX,
  );
  return resolveViewportPointBudget({ mode, seriesCount, plotWidthPx });
}
