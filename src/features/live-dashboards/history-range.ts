import type { LiveDashboard } from "./types";

export const LIVE_DASHBOARD_HISTORY_PRESETS = ["1h", "6h", "24h", "7d", "30d"] as const;
export const LIVE_DASHBOARD_HISTORY_MAX_RANGE_DAYS = 31;

export type LiveDashboardHistoryPreset = (typeof LIVE_DASHBOARD_HISTORY_PRESETS)[number];
export type LiveDashboardHistoryRangeKind = LiveDashboardHistoryPreset | "custom";

export interface LiveDashboardHistoryRange {
  kind: LiveDashboardHistoryRangeKind;
  from: string;
  to: string;
  label: string;
}

const PRESET_MILLISECONDS: Record<LiveDashboardHistoryPreset, number> = {
  "1h": 60 * 60_000,
  "6h": 6 * 60 * 60_000,
  "24h": 24 * 60 * 60_000,
  "7d": 7 * 24 * 60 * 60_000,
  "30d": 30 * 24 * 60 * 60_000,
};

export function defaultLiveDashboardHistoryPreset(
  dashboardTimeWindow: LiveDashboard["time_window"],
): LiveDashboardHistoryPreset {
  if (dashboardTimeWindow === "5m" || dashboardTimeWindow === "15m" || dashboardTimeWindow === "30m") {
    return "1h";
  }
  if (dashboardTimeWindow === "12h") return "24h";
  return dashboardTimeWindow as LiveDashboardHistoryPreset;
}

export function liveDashboardPresetRange(
  preset: LiveDashboardHistoryPreset,
  anchor = new Date(),
): LiveDashboardHistoryRange {
  const to = new Date(anchor);
  const from = new Date(to.getTime() - PRESET_MILLISECONDS[preset]);
  return {
    kind: preset,
    from: from.toISOString(),
    to: to.toISOString(),
    label: preset,
  };
}

export function liveDashboardCustomRange(from: Date | string, to: Date | string): LiveDashboardHistoryRange {
  const fromDate = new Date(from);
  const toDate = new Date(to);
  const fromMs = fromDate.getTime();
  const toMs = toDate.getTime();
  if (!Number.isFinite(fromMs) || !Number.isFinite(toMs)) {
    throw new Error("Вкажіть коректні дату й час початку та завершення.");
  }
  if (fromMs >= toMs) {
    throw new Error("Початок діапазону має бути раніше завершення.");
  }
  const maximumMs = LIVE_DASHBOARD_HISTORY_MAX_RANGE_DAYS * 24 * 60 * 60_000;
  if (toMs - fromMs > maximumMs) {
    throw new Error(`Діапазон не може перевищувати ${LIVE_DASHBOARD_HISTORY_MAX_RANGE_DAYS} день.`);
  }
  return {
    kind: "custom",
    from: fromDate.toISOString(),
    to: toDate.toISOString(),
    label: "Custom",
  };
}

export function liveDashboardHistoryRangeKey(range: LiveDashboardHistoryRange): string {
  return `${range.kind}:${range.from}:${range.to}`;
}

export function liveDashboardHistoryRangeMilliseconds(range: LiveDashboardHistoryRange): number {
  return Date.parse(range.to) - Date.parse(range.from);
}
