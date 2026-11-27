"use client";

import { createContext, useContext } from "react";

import type { ChartXDomain } from "@/features/charts/domain";
import type { ChartYScale } from "@/features/charts/y-axis-bounds";

/**
 * View state a ChartShell shares with the ChartRendererHost inside it (#1843): the operator's
 * Y-axis mode, and the visible time window reported back so the header can name the interval
 * actually shown after zoom or pan. Surfaces need no wiring of their own.
 */
export interface ChartViewContextValue {
  yScale: ChartYScale | undefined;
  reportVisibleDomain: (visible: ChartXDomain, full: ChartXDomain) => void;
}

export const ChartViewContext = createContext<ChartViewContextValue>({
  yScale: undefined,
  reportVisibleDomain: () => undefined,
});

export function useChartView(): ChartViewContextValue {
  return useContext(ChartViewContext);
}
