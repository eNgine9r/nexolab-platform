export type TelemetryMode = "demo" | "live";

export type TelemetryQuality = "valid" | "sensor_error" | "communication_error" | "unknown";

export type TelemetryAlarm = "low" | "high";

export interface TelemetrySample {
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
  received_at?: string;
}

export interface TelemetryCollectionResponse {
  items: TelemetrySample[];
  count: number;
  limit: number;
  offset: number;
  next_offset: number | null;
}

export interface TelemetryReadinessResponse {
  status: "ready" | "not_ready";
  database: "ready" | "not_ready";
  mqtt: "ready" | "not_ready";
  queue_size: number;
  websocket_clients: number;
  database_outage_since: string | null;
  last_persisted_at: string | null;
  ingestion_lag_seconds: number | null;
  mqtt_error: string | null;
  database_error: string | null;
  last_error: string | null;
}

export interface TelemetryFilters {
  node_id?: string;
  equipment_id?: string;
  channel_id?: string;
  metric?: string;
  quality?: TelemetryQuality;
  alarm?: TelemetryAlarm;
}

export interface TelemetryPageQuery extends TelemetryFilters {
  limit?: number;
  offset?: number;
}

export interface TelemetryHistoryQuery extends TelemetryPageQuery {
  from: Date | string;
  to: Date | string;
}

export interface TelemetryRuntimeConfig {
  mode: TelemetryMode;
  apiBaseUrl: string | null;
  websocketUrl: string | null;
}

export type TelemetryConnectionState = "connecting" | "connected" | "reconnecting" | "disconnected";

export interface TelemetryLiveHandlers {
  onSample: (sample: TelemetrySample) => void;
  onStateChange?: (state: TelemetryConnectionState) => void;
  onError?: (error: Error) => void;
  onHeartbeat?: (serverTime: string) => void;
}

export interface TelemetrySubscription {
  close: () => void;
}

export interface TelemetryAdapter {
  readiness: (signal?: AbortSignal) => Promise<TelemetryReadinessResponse>;
  latest: (query?: TelemetryPageQuery, signal?: AbortSignal) => Promise<TelemetryCollectionResponse>;
  history: (query: TelemetryHistoryQuery, signal?: AbortSignal) => Promise<TelemetryCollectionResponse>;
  subscribe: (filters: TelemetryFilters, handlers: TelemetryLiveHandlers) => TelemetrySubscription;
}
