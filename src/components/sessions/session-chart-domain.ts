import type { ChartXDomain } from "@/features/charts/domain";

export interface SessionHistoryWindow {
  fromMs: number;
  toMs: number;
}

/**
 * X domain of the session history chart (#1662). When the requested history window is known it is
 * the domain — so leading/trailing periods without measurements stay visible as gaps instead of
 * being cropped to the first/last sample. Without a window it falls back to the sample span.
 */
export function sessionChartDomain(
  timestampsMs: readonly number[],
  window: SessionHistoryWindow | null | undefined,
): ChartXDomain | null {
  if (
    window &&
    Number.isFinite(window.fromMs) &&
    Number.isFinite(window.toMs) &&
    window.toMs > window.fromMs
  ) {
    return { fromMs: window.fromMs, toMs: window.toMs };
  }
  const finite = timestampsMs.filter(Number.isFinite);
  if (finite.length === 0) return null;
  const fromMs = Math.min(...finite);
  const toMs = Math.max(...finite);
  return { fromMs, toMs: toMs > fromMs ? toMs : fromMs + 60_000 };
}
