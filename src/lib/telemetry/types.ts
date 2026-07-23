export const TELEMETRY_QUALITIES = [
  "valid",
  "sensor_error",
  "communication_error",
  "unknown",
] as const;

export const TELEMETRY_ALARMS = ["low", "high"] as const;

export type TelemetryQuality = (typeof TELEMETRY_QUALITIES)[number];
export type TelemetryAlarm = (typeof TELEMETRY_ALARMS)[number];

export interface TelemetryEvent {
  event_id: string;
  node_id: string;
  captured_at: string;
  metric: string;
  value: number | null;
  unit: string;
  quality: TelemetryQuality;
  source: string;
  equipment_id: string;
  channel_id: string;
  alarm: TelemetryAlarm | null;
  raw_value: number | null;
  raw_status: number | null;
}

export interface TelemetrySample extends TelemetryEvent {
  received_at: string;
}

export interface TelemetryCollection {
  items: TelemetrySample[];
  count: number;
  limit: number;
  offset: number;
  next_offset: number | null;
}

export interface TelemetryFilters {
  node_id?: string;
  equipment_id?: string;
  channel_id?: string;
  metric?: string;
  quality?: TelemetryQuality;
  alarm?: TelemetryAlarm;
}

export interface TelemetryPagination {
  limit?: number;
  offset?: number;
}

export interface TelemetryHistoryQuery extends TelemetryFilters, TelemetryPagination {
  from: string;
  to: string;
}

export interface TelemetryHeartbeat {
  type: "heartbeat";
  server_time: string;
}

export type TelemetryLiveMessage = TelemetryEvent | TelemetryHeartbeat;

export type TelemetryConnectionStatus =
  | "idle"
  | "connecting"
  | "live"
  | "reconnecting"
  | "stopped";
