/**
 * Saved analysis view of a Saved Live Dashboard (#1666): pure conversion between the live view state
 * and the persisted `view_settings`. Device/channel selection, colours and order are the dashboard
 * items themselves; this covers hidden series, the history range, the zoom viewport and the chart
 * detail. Anything stale or unusable on restore is ignored, never applied blindly.
 */

import { isChartDensityMode, type ChartDensityMode } from "@/features/charts/density";
import type { ChartXDomain } from "@/features/charts/domain";
import {
  LIVE_DASHBOARD_HISTORY_PRESETS,
  type LiveDashboardHistoryPreset,
  type LiveDashboardHistoryRange,
} from "@/features/live-dashboards/history-range";
import { dashboardItemIdentity } from "@/features/live-dashboards/model";
import type {
  LiveDashboard,
  LiveDashboardItem,
  LiveDashboardViewSettings,
} from "@/features/live-dashboards/types";

export const LIVE_DASHBOARD_VIEW_SETTINGS_VERSION = 1;

export interface CaptureViewInput {
  /** Identities (`dashboardItemIdentity`) of the series currently hidden. */
  hiddenItemIdentities: readonly string[];
  historyRange: LiveDashboardHistoryRange;
  viewport: ChartXDomain | null;
  density: ChartDensityMode;
}

export function captureViewSettings(input: CaptureViewInput): LiveDashboardViewSettings {
  const custom = input.historyRange.kind === "custom";
  return {
    schema_version: LIVE_DASHBOARD_VIEW_SETTINGS_VERSION,
    hidden_items: [...new Set(input.hiddenItemIdentities)],
    range_kind: input.historyRange.kind,
    range_from: custom ? input.historyRange.from : null,
    range_to: custom ? input.historyRange.to : null,
    viewport_from: input.viewport ? new Date(input.viewport.fromMs).toISOString() : null,
    viewport_to: input.viewport ? new Date(input.viewport.toMs).toISOString() : null,
    density: input.density,
  };
}

export interface RestoredView {
  /** Hidden item identities that still exist in the dashboard. */
  hiddenItemIdentities: string[];
  range:
    | { kind: "preset"; preset: LiveDashboardHistoryPreset }
    | { kind: "custom"; from: string; to: string }
    | null;
  viewport: ChartXDomain | null;
  density: ChartDensityMode | null;
}

function validDate(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** Interprets a stored view against the dashboard's CURRENT items; unusable parts become null/empty. */
export function resolveViewSettings(
  settings: LiveDashboardViewSettings | null | undefined,
  items: readonly Pick<
    LiveDashboardItem,
    "channel_id" | "metric" | "channel_ref_id" | "node_id" | "equipment_id"
  >[],
): RestoredView | null {
  if (!settings || settings.schema_version !== LIVE_DASHBOARD_VIEW_SETTINGS_VERSION) return null;
  const known = new Set(items.map((item) => dashboardItemIdentity(item)));
  const hiddenItemIdentities = settings.hidden_items.filter((identity) => known.has(identity));

  let range: RestoredView["range"] = null;
  if (settings.range_kind === "custom") {
    const from = validDate(settings.range_from);
    const to = validDate(settings.range_to);
    if (from !== null && to !== null && to > from) {
      range = { kind: "custom", from: new Date(from).toISOString(), to: new Date(to).toISOString() };
    }
  } else if (
    settings.range_kind &&
    (LIVE_DASHBOARD_HISTORY_PRESETS as readonly string[]).includes(settings.range_kind)
  ) {
    range = { kind: "preset", preset: settings.range_kind as LiveDashboardHistoryPreset };
  }

  const viewportFrom = validDate(settings.viewport_from);
  const viewportTo = validDate(settings.viewport_to);
  const viewport =
    viewportFrom !== null && viewportTo !== null && viewportTo > viewportFrom
      ? { fromMs: viewportFrom, toMs: viewportTo }
      : null;

  const density = isChartDensityMode(settings.density) ? settings.density : null;
  return { hiddenItemIdentities, range, viewport, density };
}

/** True when the stored viewport still overlaps the window that is being shown. */
export function viewportOverlapsWindow(viewport: ChartXDomain, window: ChartXDomain): boolean {
  return viewport.toMs > window.fromMs && viewport.fromMs < window.toMs;
}

/** Whether the live range already equals the saved one (so no reload is needed). */
export function rangeMatches(
  saved: NonNullable<RestoredView["range"]>,
  current: Pick<LiveDashboardHistoryRange, "kind" | "from" | "to">,
): boolean {
  if (saved.kind === "preset") return current.kind === saved.preset;
  return current.kind === "custom" && current.from === saved.from && current.to === saved.to;
}

export function hasSavedView(dashboard: Pick<LiveDashboard, "view_settings">): boolean {
  return Boolean(dashboard.view_settings);
}
