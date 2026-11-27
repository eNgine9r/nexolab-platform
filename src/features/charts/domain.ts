import type { TelemetryQuality } from "@/lib/telemetry/types";

export type ChartMeasurementQuality = TelemetryQuality;

/**
 * "invalid" = the channel is reporting, but its newest sample has no valid measurement
 * (unknown / sensor_error / communication_error). It must never be presented as "live".
 * "historical" = the series belongs to a fixed custom period (#1683): it has no liveness at all,
 * so it is neither "live" nor "stale".
 */
export type ChartFreshnessState =
  "live" | "stale" | "invalid" | "connecting" | "reconnecting" | "offline" | "historical";

/** The true newest sample of a series, including non-plottable quality (legend/inspector truth). */
export interface ChartSeriesLatest {
  timestampMs: number;
  value: number | null;
  quality: ChartMeasurementQuality;
}

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
  /**
   * While `freshness === "live"`: the instant (epoch ms) the series turns stale, so surfaces can
   * flip a silent series on a clock tick without rebuilding the scene (see series-freshness.ts).
   */
  freshUntilMs?: number;
  segments: readonly ChartSegment[];
  visible: boolean;
  semanticMode: "instantaneous" | "cumulative_counter";
  areaFillOpacity?: number;
  displayPrecision?: number;
  /** Newest sample regardless of quality; when absent the legend falls back to the last plotted point. */
  latest?: ChartSeriesLatest;
}

export interface ChartThreshold {
  id: string;
  seriesKey: string;
  kind: "lower" | "upper";
  value: number;
  label: string;
}

export interface ChartEventSource {
  entityId: string;
  entityType: string;
  equipmentId?: string;
  channelId?: string;
}

export interface ChartEventMarker {
  id: string;
  timestampMs: number;
  type: string;
  label: string;
  source: ChartEventSource;
  severity?: "info" | "warning" | "alarm";
  status?: string;
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

export interface ChartSeriesCursorInspection {
  seriesKey: string;
  point: ChartPoint | null;
  freshness: ChartFreshnessState;
}

export interface ChartCursorInspection {
  timestampMs: number;
  series: readonly ChartSeriesCursorInspection[];
}

export interface ChartXDomain {
  fromMs: number;
  toMs: number;
}

/**
 * #1868: every analog measurement line is SOLID; sensors are told apart by colour, name and the
 * interactive legend (markers only where a single isolated measurement needs one). Dashed/dotted
 * styles stay reserved for references that are not measurements (thresholds, events, setpoints).
 * The palette applies to every surface, including dashboards saved before this change (their
 * style was never stored; it always came from this palette).
 */
export const CHART_SERIES_TOKENS = [
  { color: "#00C6E0", dashStyle: "solid", markerShape: "circle" },
  { color: "#7ED321", dashStyle: "solid", markerShape: "diamond" },
  { color: "#0077FF", dashStyle: "solid", markerShape: "triangle" },
  { color: "#A855F7", dashStyle: "solid", markerShape: "rect" },
  { color: "#F5B301", dashStyle: "solid", markerShape: "circle" },
  { color: "#14B8A6", dashStyle: "solid", markerShape: "diamond" },
  { color: "#F97316", dashStyle: "solid", markerShape: "triangle" },
  { color: "#F43F5E", dashStyle: "solid", markerShape: "rect" },
] as const;
