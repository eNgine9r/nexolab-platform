/**
 * Requested range vs. the history that actually exists (#1677).
 *
 * A chart asked for 7 days on a device that only started logging yesterday must say so instead of
 * silently drawing 20 % of the axis. Coverage is derived from the earliest plotted measurement of
 * the visible series (the density reducer always preserves first/last evidence), never guessed.
 */

import type { ChartSeries } from "./domain";

export interface HistoryCoverage {
  /** `full`: data reaches the start of the window; `partial`: starts later; `none`: no plotted data. */
  kind: "full" | "partial" | "none";
  requestedFromMs: number;
  requestedToMs: number;
  /** Earliest plotted measurement (epoch ms) when any exists. */
  availableFromMs: number | null;
  /** Share of the requested window that lies after the first measurement, 0..1. */
  coverageRatio: number;
}

/** Ignore start gaps below this share of the window or this absolute floor (poll cadence slack). */
const MINIMUM_GAP_RATIO = 0.05;
const MINIMUM_GAP_MS = 5 * 60_000;

export function assessHistoryCoverage(
  series: readonly ChartSeries[],
  window: { fromMs: number; toMs: number },
): HistoryCoverage | null {
  const span = window.toMs - window.fromMs;
  if (!Number.isFinite(span) || span <= 0) return null;
  let first: number | null = null;
  for (const item of series) {
    if (!item.visible) continue;
    for (const segment of item.segments) {
      const point = segment.points[0];
      if (point && Number.isFinite(point.timestampMs) && (first === null || point.timestampMs < first)) {
        first = point.timestampMs;
      }
    }
  }
  if (first === null) {
    return {
      kind: "none",
      requestedFromMs: window.fromMs,
      requestedToMs: window.toMs,
      availableFromMs: null,
      coverageRatio: 0,
    };
  }
  const gap = first - window.fromMs;
  const covered = Math.min(1, Math.max(0, (window.toMs - Math.max(first, window.fromMs)) / span));
  return {
    kind: gap > Math.max(MINIMUM_GAP_MS, span * MINIMUM_GAP_RATIO) ? "partial" : "full",
    requestedFromMs: window.fromMs,
    requestedToMs: window.toMs,
    availableFromMs: first,
    coverageRatio: covered,
  };
}
