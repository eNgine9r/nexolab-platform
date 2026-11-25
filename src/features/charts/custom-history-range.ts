/**
 * "Власний період" for the Overview and Energy history charts (#1683).
 *
 * A custom period is a FIXED [from, to] window: it never follows the wall clock, never receives
 * live samples and never drops anything from its front. A `to` in the future is clamped to the
 * moment the period is applied, so the window never claims data that cannot exist yet.
 * Validation is shared with Saved Dashboards (same messages, same 31-day limit).
 */

import { formatOperationalTimestamp } from "@/features/display-time/format";
import {
  LIVE_DASHBOARD_HISTORY_MAX_RANGE_DAYS,
  liveDashboardCustomRange,
} from "@/features/live-dashboards/history-range";

export const CUSTOM_HISTORY_RANGE_LABEL = "Власний період";
export const CUSTOM_HISTORY_MAX_RANGE_DAYS = LIVE_DASHBOARD_HISTORY_MAX_RANGE_DAYS;
export const CUSTOM_HISTORY_FIXED_NOTICE = "Фіксований період: нові вимірювання не додаються";

export interface CustomHistoryWindow {
  /** ISO-8601 instant. */
  from: string;
  /** ISO-8601 instant, never later than the moment the period was applied. */
  to: string;
}

/**
 * Validates an operator-entered period and returns the fixed window to load.
 * Throws an `Error` with a Ukrainian operator message when the period is not acceptable.
 */
export function resolveCustomHistoryWindow(
  fromMs: number | null,
  toMs: number | null,
  now: number = Date.now(),
): CustomHistoryWindow {
  if (fromMs === null || toMs === null || !Number.isFinite(fromMs) || !Number.isFinite(toMs)) {
    throw new Error("Вкажіть коректні дату й час початку та завершення.");
  }
  if (fromMs >= now) {
    throw new Error("Початок періоду має бути в минулому.");
  }
  const range = liveDashboardCustomRange(new Date(fromMs), new Date(Math.min(toMs, now)));
  return { from: range.from, to: range.to };
}

/** Operator label of a custom window in the display time zone, e.g. "01.11.2026, 08:00 → …". */
export function formatCustomHistoryWindow(window: CustomHistoryWindow, timeZone: string): string {
  const options: Intl.DateTimeFormatOptions = { dateStyle: "short", timeStyle: "short" };
  return `${formatOperationalTimestamp(window.from, timeZone, options)} → ${formatOperationalTimestamp(window.to, timeZone, options)}`;
}

/** Cache/annotation key of a custom window; presets keep their own bare keys. */
export function customHistoryRangeKey(window: CustomHistoryWindow): string {
  return `custom:${window.from}:${window.to}`;
}
