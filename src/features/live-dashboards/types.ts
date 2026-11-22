import type { TelemetryAlarm, TelemetryQuality, TelemetrySample } from "@/lib/telemetry/types";

export const LIVE_DASHBOARD_MAX_ITEMS = 64;
export const LIVE_DASHBOARD_NAME_MAX_LENGTH = 128;
export const LIVE_DASHBOARD_DESCRIPTION_MAX_LENGTH = 1024;
export const LIVE_DASHBOARD_REFRESH_SECONDS = [1, 2, 5, 10, 15, 30, 60] as const;
export const LIVE_DASHBOARD_TIME_WINDOWS = ["5m", "15m", "30m", "1h", "6h", "12h", "24h", "7d"] as const;
export const LIVE_DASHBOARD_VISUALIZATIONS = ["line", "area", "gauge", "value"] as const;

export type LiveDashboardRefreshSeconds = (typeof LIVE_DASHBOARD_REFRESH_SECONDS)[number];
export type LiveDashboardTimeWindow = (typeof LIVE_DASHBOARD_TIME_WINDOWS)[number];
export type LiveDashboardVisualization = (typeof LIVE_DASHBOARD_VISUALIZATIONS)[number];
export type LiveDashboardStatus = "active" | "archived";

export interface LiveDashboardItem {
  id: string;
  position: number;
  channel_ref_id: string | null;
  node_id?: string | null;
  equipment_id?: string | null;
  channel_id: string;
  metric: string;
  native_unit: string;
  visualization: LiveDashboardVisualization;
  color: string | null;
  display_unit: string | null;
}

/** Saved analysis view (#1666); mirrors the backend `view_settings` JSON. */
export interface LiveDashboardViewSettings {
  schema_version: number;
  hidden_items: string[];
  range_kind: "1h" | "6h" | "24h" | "7d" | "30d" | "custom" | null;
  range_from: string | null;
  range_to: string | null;
  viewport_from: string | null;
  viewport_to: string | null;
  density: "auto" | 250 | 500 | 1000 | 2500 | 5000 | null;
}

export interface LiveDashboard {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  owner_subject: string;
  refresh_seconds: LiveDashboardRefreshSeconds;
  time_window: LiveDashboardTimeWindow;
  version: number;
  status: LiveDashboardStatus;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
  archived_by: string | null;
  archived_at: string | null;
  items: LiveDashboardItem[];
  view_settings?: LiveDashboardViewSettings | null;
}

export interface LiveDashboardCollection {
  items: LiveDashboard[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface LiveDashboardItemWrite {
  node_id?: string | null;
  equipment_id?: string | null;
  channel_id: string;
  metric: string;
  visualization: LiveDashboardVisualization;
  color: string | null;
  display_unit: string | null;
}

export interface LiveDashboardWrite {
  name: string;
  description: string | null;
  refresh_seconds: LiveDashboardRefreshSeconds;
  time_window: LiveDashboardTimeWindow;
  items: LiveDashboardItemWrite[];
  /** Omitted keeps the stored view (older clients); null clears it. */
  view_settings?: LiveDashboardViewSettings | null;
}

export interface LiveDashboardVersioned<T = LiveDashboard> {
  value: T;
  etag: string;
}

export interface LiveDashboardDraftItem extends LiveDashboardItemWrite {
  observed?: boolean;
  native_unit: string;
  node_id: string | null;
  equipment_id: string | null;
  source: string | null;
}

export interface LiveDashboardDraft {
  id: string | null;
  name: string;
  description: string;
  refresh_seconds: LiveDashboardRefreshSeconds;
  time_window: LiveDashboardTimeWindow;
  items: LiveDashboardDraftItem[];
  version: number | null;
  etag: string | null;
  /** Set only when the view is being saved or cleared; absent keeps the stored view. */
  view_settings?: LiveDashboardViewSettings | null;
}

export interface LiveDashboardValidation {
  valid: boolean;
  issues: string[];
}

export interface LiveDashboardInventoryItem {
  key: string;
  channel_ref_id: string | null;
  node_id: string;
  equipment_id: string;
  equipment_name: string;
  climate_chamber_id: string | null;
  climate_chamber_code: string | null;
  climate_chamber_name: string | null;
  equipment_type: string;
  laboratory: string | null;
  zone: string | null;
  channel_id: string;
  channel_name: string;
  metric: string;
  native_unit: string;
  source: string;
  quality: TelemetryQuality;
  alarm: TelemetryAlarm | null;
  latest: TelemetrySample | null;
}

export interface LiveDashboardInventoryCollection {
  items: LiveDashboardInventoryItem[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface LiveDashboardInventoryFilters {
  search: string;
  node_id: string;
  equipment_id: string;
  metric: string;
  quality: "all" | TelemetryQuality;
  alarm: "all" | "capable" | "active" | "none";
}

export type LiveDashboardWorkspaceMode = "library" | "editor" | "live";

export type LiveDashboardTelemetryStatus =
  | "idle"
  | "connecting"
  | "live"
  | "reconnecting"
  | "stale"
  | "offline"
  | "unauthorized"
  | "forbidden"
  | "configuration_error"
  | "error";

export interface LiveDashboardSeries {
  item: LiveDashboardItem;
  latest: TelemetrySample | null;
  history: TelemetrySample[];
}
