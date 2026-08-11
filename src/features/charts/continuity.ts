import {
  chartSeriesKey,
  type ChartContinuityBreak,
  type ChartContinuityBreakReason,
  type ChartFreshnessState,
  type ChartPoint,
  type ChartSegment,
  type ChartSeriesIdentity,
} from "./domain";
import type { TelemetryQuality } from "@/lib/telemetry/types";

export interface ChartContinuitySample {
  id: string;
  timestampMs: number;
  value: number | null;
  quality: TelemetryQuality;
  freshness?: ChartFreshnessState;
  sourceEventId?: string;
  explicitBreak?: Exclude<
    ChartContinuityBreakReason,
    "source_gap" | "invalid_quality" | "missing_measurement"
  >;
  pinReasons?: ChartPoint["pinReasons"];
}

export interface ChartContinuityOptions {
  maximumSourceGapMs: number;
}

function invalidReason(sample: ChartContinuitySample): ChartContinuityBreakReason | null {
  if (sample.explicitBreak) return sample.explicitBreak;
  if (sample.freshness === "offline") return "offline";
  if (sample.freshness === "reconnecting") return "reconnect_gap";
  if (sample.quality !== "valid") return "invalid_quality";
  if (sample.value === null || !Number.isFinite(sample.value)) return "missing_measurement";
  return null;
}

export function buildChartSegments(
  identity: ChartSeriesIdentity,
  samples: readonly ChartContinuitySample[],
  options: ChartContinuityOptions,
): ChartSegment[] {
  if (!Number.isFinite(options.maximumSourceGapMs) || options.maximumSourceGapMs <= 0) {
    throw new Error("maximumSourceGapMs must be a positive finite number");
  }

  const key = chartSeriesKey(identity);
  const ordered = [...samples].sort(
    (left, right) => left.timestampMs - right.timestampMs || left.id.localeCompare(right.id),
  );
  const segments: ChartSegment[] = [];
  let points: ChartPoint[] = [];
  let previousTimestamp: number | null = null;
  let pendingBreak: ChartContinuityBreak | undefined;

  const flush = () => {
    if (points.length === 0) return;
    const first = points[0];
    const last = points.at(-1)!;
    segments.push({
      id: `${key}:${first.timestampMs}:${last.timestampMs}`,
      seriesKey: key,
      points,
      ...(pendingBreak ? { precedingBreak: pendingBreak } : {}),
    });
    points = [];
    pendingBreak = undefined;
  };

  for (const sample of ordered) {
    if (!Number.isFinite(sample.timestampMs)) continue;
    const reason = invalidReason(sample);
    if (reason) {
      flush();
      pendingBreak = { reason, atMs: sample.timestampMs, sourceEventId: sample.sourceEventId };
      previousTimestamp = sample.timestampMs;
      continue;
    }

    if (previousTimestamp !== null && sample.timestampMs - previousTimestamp > options.maximumSourceGapMs) {
      flush();
      pendingBreak = { reason: "source_gap", atMs: sample.timestampMs };
    }

    points.push({
      id: sample.id,
      timestampMs: sample.timestampMs,
      value: sample.value!,
      quality: sample.quality,
      sourceEventId: sample.sourceEventId,
      pinReasons: sample.pinReasons,
    });
    previousTimestamp = sample.timestampMs;
  }
  flush();
  return segments;
}
