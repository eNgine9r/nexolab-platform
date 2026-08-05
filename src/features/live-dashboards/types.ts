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
  channel_ref_id: string;
  channel_id: string;
  metric: string;
  native_unit: string;
  visualization: LiveDashboardVisualization;
  color: string | null;
  display_unit: string | null;
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
}

export interface LiveDashboardCollection {
  items: LiveDashboard[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface LiveDashboardItemWrite {
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
}

export interface LiveDashboardVersioned<T = LiveDashboard> {
  value: T;
  etag: string;
}

export interface LiveDashboardDraftItem extends LiveDashboardItemWrite {
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
}

export interface LiveDashboardValidation {
  valid: boolean;
  issues: string[];
}

export interface LiveDashboardInventoryItem {
  key: string;
  node_id: string;
  equipment_id: string;
  channel_id: string;
  metric: string;
  native_unit: string;
  source: string;
  quality: TelemetryQuality;
  alarm: TelemetryAlarm | null;
  latest: TelemetrySample;
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
