import type { TelemetryQuality } from "@/lib/telemetry/types";

export type ChartMeasurementQuality = TelemetryQuality;

export type ChartFreshnessState = "live" | "stale" | "connecting" | "reconnecting" | "offline";

export interface ChartSeriesIdentity {
  nodeId: string;
  equipmentId: string;
  channelId: string;
  metric: string;
  nativeUnit: string;
}

export function chartSeriesKey(identity: ChartSeriesIdentity): string {
  return [identity.nodeId, identity.equipmentId, identity.channelId, identity.metric, identity.nativeUnit]
    .map((part) => `${part.length}:${part}`)
    .join("|");
}

export type ChartEvidencePinReason = "alarm" | "event" | "threshold_crossing" | "segment_boundary";

export interface ChartPoint {
  id: string;
  timestampMs: number;
  value: number;
  quality: ChartMeasurementQuality;
  sourceEventId?: string;
  pinReasons?: readonly ChartEvidencePinReason[];
}

export type ChartContinuityBreakReason =
  "explicit_gap" | "source_gap" | "invalid_quality" | "offline" | "missing_measurement" | "reconnect_gap";

export interface ChartContinuityBreak {
  reason: ChartContinuityBreakReason;
  atMs: number;
  sourceEventId?: string;
}

export interface ChartSegment {
  id: string;
  seriesKey: string;
  points: readonly ChartPoint[];
  precedingBreak?: ChartContinuityBreak;
}

export interface ChartSeries {
  identity: ChartSeriesIdentity;
  name: string;
  colorToken: string;
  dashStyle: "solid" | "dashed" | "dotted";
  markerShape: "circle" | "diamond" | "triangle" | "rect";
  freshness: ChartFreshnessState;
  segments: readonly ChartSegment[];
  visible: boolean;
  semanticMode: "instantaneous" | "cumulative_counter";
}

export interface ChartThreshold {
  id: string;
  seriesKey: string;
  kind: "lower" | "upper";
  value: number;
  label: string;
}

export interface ChartEventMarker {
  id: string;
  timestampMs: number;
  type: string;
  label: string;
  severity?: "info" | "warning" | "alarm";
}

export interface ChartAlarmRegion {
  id: string;
  fromMs: number;
  toMs: number;
  label: string;
  severity: "warning" | "alarm" | "offline";
}

export interface ChartStatistics {
  current: number | null;
  min: number | null;
  max: number | null;
  average: number | null;
  sampleCount: number;
  scope: "requested_interval" | "visible_viewport" | "reduced_visualization";
  fromMs: number;
  toMs: number;
}

export interface ChartCursorInspection {
  timestampMs: number;
  seriesKey: string;
  point: ChartPoint | null;
  freshness: ChartFreshnessState;
}

export interface ChartXDomain {
  fromMs: number;
  toMs: number;
}

export const CHART_SERIES_TOKENS = [
  { color: "#00C6E0", dashStyle: "solid", markerShape: "circle" },
  { color: "#7ED321", dashStyle: "dashed", markerShape: "diamond" },
  { color: "#0077FF", dashStyle: "dotted", markerShape: "triangle" },
  { color: "#A855F7", dashStyle: "solid", markerShape: "rect" },
  { color: "#F5B301", dashStyle: "dashed", markerShape: "circle" },
  { color: "#14B8A6", dashStyle: "dotted", markerShape: "diamond" },
  { color: "#F97316", dashStyle: "solid", markerShape: "triangle" },
  { color: "#F43F5E", dashStyle: "dashed", markerShape: "rect" },
] as const;
