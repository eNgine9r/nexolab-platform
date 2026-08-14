import type { TelemetryQuality } from "@/lib/telemetry/types";

import {
  chartSeriesKey,
  type ChartContinuityBreak,
  type ChartContinuityBreakReason,
  type ChartFreshnessState,
  type ChartPoint,
  type ChartSegment,
  type ChartSeriesIdentity,
} from "./domain";

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
  maximumSourceGapMs?: number;
}

export const CHART_MINIMUM_SOURCE_GAP_MS = 30_000;
const CHART_SOURCE_GAP_MULTIPLIER = 3;

function invalidReason(sample: ChartContinuitySample): ChartContinuityBreakReason | null {
  if (sample.explicitBreak) return sample.explicitBreak;
  if (sample.freshness === "offline") return "offline";
  if (sample.freshness === "reconnecting") return "reconnect_gap";
  if (sample.quality !== "valid") return "invalid_quality";
  if (sample.value === null || !Number.isFinite(sample.value)) return "missing_measurement";
  return null;
}

function orderedUniqueSamples(samples: readonly ChartContinuitySample[]): ChartContinuitySample[] {
  const ordered = samples
    .filter((sample) => Number.isFinite(sample.timestampMs))
    .sort((left, right) => left.timestampMs - right.timestampMs || left.id.localeCompare(right.id));
  const byId = new Map<string, ChartContinuitySample>();
  for (const sample of ordered) {
    if (!byId.has(sample.id)) byId.set(sample.id, sample);
  }
  return [...byId.values()];
}

/**
 * Derive a render-only continuity tolerance from the observed source cadence.
 *
 * The acquisition scheduler supports multiple configurable cadences, so a fixed
 * 30-second chart threshold can create false gaps for valid low-priority data.
 * Communication failures are emitted as explicit non-valid telemetry samples;
 * this tolerance only detects otherwise silent timestamp gaps in persisted
 * history. It never changes acquisition or fabricates measurements.
 */
export function deriveChartSourceGapMs(
  samples: readonly Pick<ChartContinuitySample, "id" | "timestampMs">[],
  minimumMs = CHART_MINIMUM_SOURCE_GAP_MS,
): number {
  if (!Number.isFinite(minimumMs) || minimumMs <= 0) {
    throw new Error("minimumMs must be a positive finite number");
  }
  const timestamps = [...new Set(samples.map((sample) => sample.timestampMs).filter(Number.isFinite))].sort(
    (left, right) => left - right,
  );
  const deltas = timestamps
    .slice(1)
    .map((timestamp, index) => timestamp - timestamps[index])
    .filter((delta) => delta > 0)
    .sort((left, right) => left - right);
  if (deltas.length < 2) return minimumMs;

  const middle = Math.floor(deltas.length / 2);
  const median = deltas.length % 2 === 0 ? (deltas[middle - 1] + deltas[middle]) / 2 : deltas[middle];
  return Math.max(minimumMs, median * CHART_SOURCE_GAP_MULTIPLIER);
}

export function buildChartSegments(
  identity: ChartSeriesIdentity,
  samples: readonly ChartContinuitySample[],
  options: ChartContinuityOptions = {},
): ChartSegment[] {
  const maximumSourceGapMs = options.maximumSourceGapMs ?? deriveChartSourceGapMs(samples);
  if (!Number.isFinite(maximumSourceGapMs) || maximumSourceGapMs <= 0) {
    throw new Error("maximumSourceGapMs must be a positive finite number");
  }

  const key = chartSeriesKey(identity);
  const ordered = orderedUniqueSamples(samples);
  const segments: ChartSegment[] = [];
  let points: ChartPoint[] = [];
  let previousTimestamp: number | null = null;
  let pendingBreak: ChartContinuityBreak | undefined;
  let activeSegmentBreak: ChartContinuityBreak | undefined;

  const flush = () => {
    if (points.length === 0) return;
    const first = points[0];
    segments.push({
      id: `${key}:segment:${segments.length}:${first.timestampMs}`,
      seriesKey: key,
      points,
      ...(activeSegmentBreak ? { precedingBreak: activeSegmentBreak } : {}),
    });
    points = [];
    activeSegmentBreak = undefined;
  };

  for (const sample of ordered) {
    const reason = invalidReason(sample);
    if (reason) {
      flush();
      pendingBreak = {
        reason,
        atMs: sample.timestampMs,
        sourceEventId: sample.sourceEventId,
      };
      previousTimestamp = sample.timestampMs;
      continue;
    }

    if (
      points.length > 0 &&
      previousTimestamp !== null &&
      sample.timestampMs - previousTimestamp > maximumSourceGapMs
    ) {
      flush();
      pendingBreak = { reason: "source_gap", atMs: sample.timestampMs };
    }

    if (points.length === 0 && pendingBreak) {
      activeSegmentBreak = pendingBreak;
      pendingBreak = undefined;
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
