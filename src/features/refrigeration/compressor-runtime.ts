import { deriveChartSourceGapMs } from "@/features/charts/continuity";

export interface CompressorSpeedSample {
  capturedAt: string;
  value: number | null;
  quality: string;
  eventId?: string;
}

export interface CompressorStartEvent {
  previousObservedAtMs: number;
  observedAtMs: number;
  previousValueRpm: number;
  valueRpm: number;
  previousEventId: string | null;
  eventId: string | null;
}

export interface CompressorRuntimeDuty {
  status: "available" | "unavailable";
  dutyPercent: number | null;
  coveragePercent: number;
  runningMs: number;
  observedMs: number;
  requestedMs: number;
  continuityBreaks: number;
  sourceGapMs: number;
  startCount: number;
}

const VALID_QUALITY = "valid";
const DEFAULT_SOURCE_GAP_MS = 90_000;

type NormalizedCompressorSample = {
  capturedAtMs: number;
  value: number | null;
  valid: boolean;
  eventId: string | null;
};

function timestampMs(value: string): number | null {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function resolveRangeMs(range: { from: string; to: string }): { fromMs: number; toMs: number } {
  const fromMs = timestampMs(range.from);
  const toMs = timestampMs(range.to);
  if (fromMs === null || toMs === null || toMs <= fromMs) {
    throw new Error("Compressor runtime range must be a valid positive interval");
  }
  return { fromMs, toMs };
}

function normalizeCompressorSamples(samples: readonly CompressorSpeedSample[]): NormalizedCompressorSample[] {
  const byTimestamp = new Map<number, NormalizedCompressorSample>();
  for (const sample of samples) {
    const capturedAtMs = timestampMs(sample.capturedAt);
    if (capturedAtMs === null) continue;
    const valid =
      sample.quality === VALID_QUALITY &&
      sample.value !== null &&
      Number.isFinite(sample.value) &&
      sample.value >= 0;
    byTimestamp.set(capturedAtMs, {
      capturedAtMs,
      value: valid ? sample.value : null,
      valid,
      eventId: sample.eventId ?? null,
    });
  }
  return [...byTimestamp.values()].sort((left, right) => left.capturedAtMs - right.capturedAtMs);
}

function compressorSourceGapMs(samples: readonly NormalizedCompressorSample[]): number {
  return deriveChartSourceGapMs(
    samples.map((sample, index) => ({ id: `compressor-speed-${index}`, timestampMs: sample.capturedAtMs })),
    DEFAULT_SOURCE_GAP_MS,
  );
}

export function buildCompressorStartEvents(
  samples: readonly CompressorSpeedSample[],
  range: { from: string; to: string },
): CompressorStartEvent[] {
  const { fromMs, toMs } = resolveRangeMs(range);
  const ordered = normalizeCompressorSamples(samples);
  const sourceGapMs = compressorSourceGapMs(ordered);
  const starts: CompressorStartEvent[] = [];

  for (let index = 1; index < ordered.length; index += 1) {
    const previous = ordered[index - 1];
    const current = ordered[index];
    if (!previous || !current || !previous.valid || !current.valid) continue;
    if (previous.value === null || current.value === null) continue;
    const durationMs = current.capturedAtMs - previous.capturedAtMs;
    if (durationMs <= 0 || durationMs > sourceGapMs) continue;
    if (current.capturedAtMs < fromMs || current.capturedAtMs > toMs) continue;
    if (previous.value !== 0 || current.value <= 0) continue;
    starts.push({
      previousObservedAtMs: previous.capturedAtMs,
      observedAtMs: current.capturedAtMs,
      previousValueRpm: previous.value,
      valueRpm: current.value,
      previousEventId: previous.eventId,
      eventId: current.eventId,
    });
  }
  return starts;
}

export function calculateCompressorRuntimeDuty(
  samples: readonly CompressorSpeedSample[],
  range: { from: string; to: string },
): CompressorRuntimeDuty {
  const { fromMs, toMs } = resolveRangeMs(range);
  const requestedMs = toMs - fromMs;
  const ordered = normalizeCompressorSamples(samples);
  const sourceGapMs = compressorSourceGapMs(ordered);

  let runningMs = 0;
  let observedMs = 0;
  let continuityBreaks = 0;
  for (let index = 0; index < ordered.length - 1; index += 1) {
    const current = ordered[index];
    const next = ordered[index + 1];
    if (!current || !next) continue;
    const durationMs = next.capturedAtMs - current.capturedAtMs;
    if (durationMs <= 0) continue;

    const overlapFromMs = Math.max(fromMs, current.capturedAtMs);
    const overlapToMs = Math.min(toMs, next.capturedAtMs);
    const overlapMs = overlapToMs - overlapFromMs;
    if (overlapMs <= 0) continue;

    if (durationMs > sourceGapMs) {
      continuityBreaks += 1;
      continue;
    }
    if (!current.valid || !next.valid) {
      continuityBreaks += 1;
      continue;
    }
    observedMs += overlapMs;
    if ((current.value ?? 0) > 0) runningMs += overlapMs;
  }

  const coveragePercent = Math.min(100, (observedMs / requestedMs) * 100);
  return {
    status: observedMs > 0 ? "available" : "unavailable",
    dutyPercent: observedMs > 0 ? (runningMs / observedMs) * 100 : null,
    coveragePercent,
    runningMs,
    observedMs,
    requestedMs,
    continuityBreaks,
    sourceGapMs,
    startCount: buildCompressorStartEvents(samples, range).length,
  };
}
