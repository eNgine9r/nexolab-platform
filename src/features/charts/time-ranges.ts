export type CanonicalChartTimeRangeId = "live" | "5m" | "15m" | "1h" | "6h" | "24h" | "7d" | "custom";

export interface CanonicalChartTimeRange {
  id: CanonicalChartTimeRangeId;
  label: string;
  durationMs: number | null;
  liveFollow: boolean;
}

export const CANONICAL_CHART_TIME_RANGES: readonly CanonicalChartTimeRange[] = [
  { id: "live", label: "Live", durationMs: 15 * 60_000, liveFollow: true },
  { id: "5m", label: "5 min", durationMs: 5 * 60_000, liveFollow: false },
  { id: "15m", label: "15 min", durationMs: 15 * 60_000, liveFollow: false },
  { id: "1h", label: "1 h", durationMs: 60 * 60_000, liveFollow: false },
  { id: "6h", label: "6 h", durationMs: 6 * 60 * 60_000, liveFollow: false },
  { id: "24h", label: "24 h", durationMs: 24 * 60 * 60_000, liveFollow: false },
  { id: "7d", label: "7 d", durationMs: 7 * 24 * 60 * 60_000, liveFollow: false },
  { id: "custom", label: "Custom", durationMs: null, liveFollow: false },
];
