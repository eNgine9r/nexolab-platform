import { deriveChartSourceGapMs } from "@/features/charts/continuity";
import {
  clearEnergyHistoryBreakPending,
  clearEnergyHistoryMarkers,
  energyHistorySourceEventId,
  isEnergyHistoryBreakPending,
  isEnergyHistorySegmentStart,
  markEnergyHistoryBreakPending,
  markEnergyHistorySegmentStart,
} from "@/features/energy/energy-history-segment";
import { isEnergySample, resolveEnergyMeter, type EnergyMetricId } from "@/features/energy/energy-telemetry";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

const HISTORY_PAGE_SIZE = 1_000;
const MAX_HISTORY_PAGES = 100;
const SOURCE_CADENCE_TAIL_CACHE_LIMIT = 512;
const SOURCE_CADENCE_RECENT_TIMESTAMP_LIMIT = 5;
export const MAX_HISTORY_POINTS_PER_METER = 240;
export const ENERGY_HISTORY_MAX_FUTURE_SKEW_MS = 30_000;

interface EnergyHistoryCadenceState {
  rawTimestampMs: number[];
  maximumSourceGapMs: number;
}

const sourceCadenceByTailEventId = new Map<string, EnergyHistoryCadenceState>();

export interface EnergyHistoryWindow {
  nodeId: string;
  metric: EnergyMetricId;
  from: Date;
  to: Date;
}

interface EnergyHistorySegmentAnnotation {
  samples: TelemetrySample[];
  breakPending: boolean;
}

function isRenderableEnergyHistorySample(sample: TelemetrySample): boolean {
  return sample.quality === "valid" && sample.value !== null && Number.isFinite(sample.value);
}

function isAcceptedEnergyHistorySample(sample: TelemetrySample): boolean {
  return isEnergySample(sample) && Number.isFinite(Date.parse(sample.captured_at));
}

function renderableEnergyHistoryTimestamps(samples: readonly TelemetrySample[]): number[] {
  return [...new Set(samples.filter(isRenderableEnergyHistorySample).map((sample) => Date.parse(sample.captured_at)))]
    .filter(Number.isFinite)
    .sort((left, right) => left - right);
}

function cadenceStateFromTimestamps(timestamps: readonly number[]): EnergyHistoryCadenceState | null {
  const rawTimestampMs = [...new Set(timestamps.filter(Number.isFinite))]
    .sort((left, right) => left - right)
    .slice(-SOURCE_CADENCE_RECENT_TIMESTAMP_LIMIT);
  if (rawTimestampMs.length < 3) return null;

  return {
    rawTimestampMs,
    maximumSourceGapMs: deriveChartSourceGapMs(
      rawTimestampMs.map((timestampMs) => ({ id: `energy-cadence:${timestampMs}`, timestampMs })),
    ),
  };
}

function cadenceStateFromSamples(samples: readonly TelemetrySample[]): EnergyHistoryCadenceState | null {
  return cadenceStateFromTimestamps(renderableEnergyHistoryTimestamps(samples));
}

function rememberSourceCadenceForTail(
  sample: TelemetrySample | null,
  cadenceState: EnergyHistoryCadenceState | null,
): void {
  if (sample === null || cadenceState === null) return;
  if (!Number.isFinite(cadenceState.maximumSourceGapMs) || cadenceState.maximumSourceGapMs <= 0) return;

  const sourceEventId = energyHistorySourceEventId(sample.event_id);
  sourceCadenceByTailEventId.delete(sourceEventId);
  sourceCadenceByTailEventId.set(sourceEventId, cadenceState);

  while (sourceCadenceByTailEventId.size > SOURCE_CADENCE_TAIL_CACHE_LIMIT) {
    const oldestKey = sourceCadenceByTailEventId.keys().next().value;
    if (oldestKey === undefined) break;
    sourceCadenceByTailEventId.delete(oldestKey);
  }
}

function sourceCadenceForTail(sample: TelemetrySample | null): EnergyHistoryCadenceState | null {
  if (sample === null) return null;
  return sourceCadenceByTailEventId.get(energyHistorySourceEventId(sample.event_id)) ?? null;
}

function deriveEnergyHistorySourceGapMs(samples: readonly TelemetrySample[]): number {
  return deriveChartSourceGapMs(
    samples.filter(isRenderableEnergyHistorySample).map((sample) => ({
      id: energyHistorySourceEventId(sample.event_id),
      timestampMs: Date.parse(sample.captured_at),
    })),
  );
}

function annotateSourceSegments(
  samples: readonly TelemetrySample[],
  previousRenderableAt: number | null = null,
  initialBreakPending = false,
  maximumSourceGapMs: number | null = deriveEnergyHistorySourceGapMs(samples),
): EnergyHistorySegmentAnnotation {
  const sorted = [...samples].sort(
    (left, right) => Date.parse(left.captured_at) - Date.parse(right.captured_at),
  );
  const annotated: TelemetrySample[] = [];
  let previousAt = previousRenderableAt;
  let breakPending = initialBreakPending;

  for (const sourceSample of sorted) {
    const explicitSegment = isEnergyHistorySegmentStart(sourceSample.event_id);
    const pendingAfterSample = isEnergyHistoryBreakPending(sourceSample.event_id);
    const sample = clearEnergyHistoryMarkers(sourceSample);
    const capturedAt = Date.parse(sample.captured_at);
    if (!Number.isFinite(capturedAt)) continue;

    if (!isRenderableEnergyHistorySample(sample)) {
      if (previousAt !== null && capturedAt >= previousAt) breakPending = true;
      continue;
    }

    const startsSegment =
      explicitSegment ||
      (previousAt !== null &&
        capturedAt >= previousAt &&
        (breakPending || (maximumSourceGapMs !== null && capturedAt - previousAt > maximumSourceGapMs)));

    annotated.push(startsSegment ? markEnergyHistorySegmentStart(sample) : sample);
    if (previousAt === null || capturedAt >= previousAt) previousAt = capturedAt;
    breakPending = pendingAfterSample;
  }

  return { samples: annotated, breakPending };
}

function mergeBucketSample(
  current: TelemetrySample | undefined,
  candidate: TelemetrySample,
): TelemetrySample {
  if (!current) return candidate;

  const selected = Date.parse(current.captured_at) <= Date.parse(candidate.captured_at) ? candidate : current;
  const startsSegment =
    isEnergyHistorySegmentStart(current.event_id) || isEnergyHistorySegmentStart(candidate.event_id);
  const normalized = clearEnergyHistoryMarkers(selected);
  return startsSegment ? markEnergyHistorySegmentStart(normalized) : normalized;
}

function applyPendingBreak(samples: readonly TelemetrySample[], breakPending: boolean): TelemetrySample[] {
  if (!breakPending || samples.length === 0) return [...samples];
  const marked = [...samples];
  marked[marked.length - 1] = markEnergyHistoryBreakPending(marked[marked.length - 1]);
  return marked;
}

function bucketDownsampleAnnotated(
  samples: readonly TelemetrySample[],
  maximumPoints: number,
  window?: Pick<EnergyHistoryWindow, "from" | "to">,
): TelemetrySample[] {
  const sorted = [...samples].sort(
    (left, right) => Date.parse(left.captured_at) - Date.parse(right.captured_at),
  );
  if (sorted.length <= maximumPoints) return sorted;
  if (maximumPoints <= 1) return [sorted.at(-1)!];
  if (maximumPoints === 2) return [sorted[0], sorted.at(-1)!];

  const sampleFrom = Date.parse(sorted[0].captured_at);
  const sampleTo = Date.parse(sorted.at(-1)!.captured_at);
  const from = window?.from.getTime() ?? sampleFrom;
  const to = window?.to.getTime() ?? sampleTo;
  const rangeMs = Math.max(1, to - from);
  const bucketMs = Math.max(1, Math.ceil(rangeMs / (maximumPoints - 2)));
  const buckets = new Map<number, TelemetrySample>();

  for (const sample of sorted) {
    const capturedAt = Date.parse(sample.captured_at);
    if (!Number.isFinite(capturedAt)) continue;
    const bucket = Math.floor(capturedAt / bucketMs);
    buckets.set(bucket, mergeBucketSample(buckets.get(bucket), sample));
  }

  const first = sorted[0];
  const last = sorted.at(-1)!;
  const firstBucket = Math.floor(Date.parse(first.captured_at) / bucketMs);
  const lastBucket = Math.floor(Date.parse(last.captured_at) / bucketMs);
  const firstBucketSample = buckets.get(firstBucket);
  const firstBucketContainsLaterSegment =
    firstBucketSample !== undefined &&
    isEnergyHistorySegmentStart(firstBucketSample.event_id) &&
    energyHistorySourceEventId(firstBucketSample.event_id) !== energyHistorySourceEventId(first.event_id);
  buckets.set(firstBucket, first);
  buckets.set(lastBucket, mergeBucketSample(buckets.get(lastBucket), last));

  const sampled = [...buckets.values()]
    .sort((left, right) => Date.parse(left.captured_at) - Date.parse(right.captured_at))
    .slice(-maximumPoints);

  if (firstBucketContainsLaterSegment) {
    const firstIndex = sampled.findIndex(
      (sample) => energyHistorySourceEventId(sample.event_id) === energyHistorySourceEventId(first.event_id),
    );
    if (firstIndex >= 0 && firstIndex + 1 < sampled.length) {
      sampled[firstIndex + 1] = markEnergyHistorySegmentStart(sampled[firstIndex + 1]);
    }
  }

  return sampled;
}

export function selectEnergyHistoryTail(
  samples: readonly TelemetrySample[],
  nodeId: string,
  metric: EnergyMetricId,
  now: number = Date.now(),
  maximumFutureSkewMs = ENERGY_HISTORY_MAX_FUTURE_SKEW_MS,
): TelemetrySample[] {
  return samples.filter((sample) => {
    const capturedAt = Date.parse(sample.captured_at);
    return (
      sample.node_id === nodeId &&
      sample.metric === metric &&
      isAcceptedEnergyHistorySample(sample) &&
      capturedAt <= now + maximumFutureSkewMs
    );
  });
}

export function downsampleEnergyHistory(
  samples: readonly TelemetrySample[],
  maximumPointsPerMeter = MAX_HISTORY_POINTS_PER_METER,
  window?: Pick<EnergyHistoryWindow, "from" | "to">,
): TelemetrySample[] {
  const byMeter = new Map<number, TelemetrySample[]>();

  for (const sample of samples) {
    if (!isAcceptedEnergyHistorySample(sample)) continue;
    const meter = resolveEnergyMeter(sample);
    if (!meter) continue;
    const current = byMeter.get(meter.unitId) ?? [];
    current.push(sample);
    byMeter.set(meter.unitId, current);
  }

  return [...byMeter.entries()]
    .sort(([left], [right]) => left - right)
    .flatMap(([, meterSamples]) => {
      const cadenceState = cadenceStateFromSamples(meterSamples);
      const maximumSourceGapMs = cadenceState?.maximumSourceGapMs ?? deriveEnergyHistorySourceGapMs(meterSamples);
      const annotation = annotateSourceSegments(meterSamples, null, false, maximumSourceGapMs);
      const sampled = bucketDownsampleAnnotated(annotation.samples, maximumPointsPerMeter, window);
      const reduced = applyPendingBreak(sampled, annotation.breakPending);

      rememberSourceCadenceForTail(
        reduced.filter(isRenderableEnergyHistorySample).at(-1) ?? null,
        cadenceState,
      );

      return reduced;
    });
}

export function mergeEnergyHistoryTail(
  current: readonly TelemetrySample[],
  incoming: readonly TelemetrySample[],
  window: EnergyHistoryWindow,
): TelemetrySample[] {
  const from = window.from.getTime();
  const to = window.to.getTime();
  const currentByMeter = new Map<number, TelemetrySample[]>();
  const incomingByMeter = new Map<number, TelemetrySample[]>();

  const collect = (target: Map<number, TelemetrySample[]>, sample: TelemetrySample) => {
    const capturedAt = Date.parse(sample.captured_at);
    if (
      sample.node_id !== window.nodeId ||
      sample.metric !== window.metric ||
      !isAcceptedEnergyHistorySample(sample) ||
      capturedAt < from ||
      capturedAt > to
    ) {
      return;
    }

    const meter = resolveEnergyMeter(sample);
    if (!meter) return;
    const values = target.get(meter.unitId) ?? [];
    values.push(sample);
    target.set(meter.unitId, values);
  };

  current.forEach((sample) => collect(currentByMeter, sample));
  incoming.forEach((sample) => collect(incomingByMeter, sample));

  const unitIds = new Set([...currentByMeter.keys(), ...incomingByMeter.keys()]);
  const merged: TelemetrySample[] = [];

  for (const unitId of [...unitIds].sort((left, right) => left - right)) {
    const existing = [...(currentByMeter.get(unitId) ?? [])].sort(
      (left, right) => Date.parse(left.captured_at) - Date.parse(right.captured_at),
    );
    const latestExisting = existing.filter(isRenderableEnergyHistorySample).at(-1) ?? null;
    const existingBreakPending =
      latestExisting !== null && isEnergyHistoryBreakPending(latestExisting.event_id);
    const normalizedExisting = existing.map(clearEnergyHistoryBreakPending);
    const lastExistingAt =
      normalizedExisting
        .filter(isRenderableEnergyHistorySample)
        .map((sample) => Date.parse(sample.captured_at))
        .filter(Number.isFinite)
        .at(-1) ?? null;
    const incomingSamples = incomingByMeter.get(unitId) ?? [];
    const inheritedCadenceState = sourceCadenceForTail(latestExisting);
    const incomingCadenceState = cadenceStateFromSamples(incomingSamples);
    const maximumSourceGapMs =
      inheritedCadenceState?.maximumSourceGapMs ?? incomingCadenceState?.maximumSourceGapMs ?? null;
    // Retained history may be heavily downsampled, so the current physical cadence is
    // carried from a bounded raw tail rather than inferred from rendered points. Every
    // raw live sample extends that tail and continuously relearns later cadence changes.
    const annotation = annotateSourceSegments(
      incomingSamples,
      lastExistingAt,
      existingBreakPending,
      maximumSourceGapMs,
    );
    const byEventId = new Map<string, TelemetrySample>();

    for (const sample of [...normalizedExisting, ...annotation.samples]) {
      byEventId.set(energyHistorySourceEventId(sample.event_id), sample);
    }

    const sampled = bucketDownsampleAnnotated([...byEventId.values()], MAX_HISTORY_POINTS_PER_METER, window);
    const reduced = applyPendingBreak(sampled, annotation.breakPending);
    const latestReduced = reduced.filter(isRenderableEnergyHistorySample).at(-1) ?? null;
    const nextCadenceState = cadenceStateFromTimestamps([
      ...(inheritedCadenceState?.rawTimestampMs ?? []),
      ...renderableEnergyHistoryTimestamps(incomingSamples),
    ]);

    rememberSourceCadenceForTail(latestReduced, nextCadenceState ?? inheritedCadenceState ?? incomingCadenceState);
    merged.push(...reduced);
  }

  return merged;
}

export async function loadCompleteEnergyHistory(
  adapter: TelemetryAdapter,
  window: EnergyHistoryWindow,
  signal?: AbortSignal,
): Promise<TelemetrySample[]> {
  const samples = new Map<string, TelemetrySample>();
  let cursorTo = new Date(window.to);
  let snapshotAt: string | undefined;

  for (let page = 0; page < MAX_HISTORY_PAGES; page += 1) {
    const response = await adapter.history(
      {
        node_id: window.nodeId,
        metric: window.metric,
        from: window.from,
        to: cursorTo,
        snapshot_at: snapshotAt,
        limit: HISTORY_PAGE_SIZE,
        offset: 0,
      },
      signal,
    );

    const responseSnapshotAt = response.snapshot_at;
    if (!responseSnapshotAt || Number.isNaN(Date.parse(responseSnapshotAt))) {
      throw new Error("Telemetry history page did not provide an ingestion snapshot watermark");
    }
    if (snapshotAt === undefined) {
      snapshotAt = responseSnapshotAt;
    } else if (responseSnapshotAt !== snapshotAt) {
      throw new Error("Telemetry history ingestion snapshot changed during pagination");
    }

    for (const sample of response.items) {
      if (
        sample.node_id === window.nodeId &&
        sample.metric === window.metric &&
        isAcceptedEnergyHistorySample(sample)
      ) {
        samples.set(sample.event_id, sample);
      }
    }

    if (response.next_offset === null) {
      return downsampleEnergyHistory([...samples.values()], MAX_HISTORY_POINTS_PER_METER, window);
    }

    const capturedTimes = response.items
      .map((sample) => Date.parse(sample.captured_at))
      .filter(Number.isFinite);
    if (capturedTimes.length === 0) {
      throw new Error("Telemetry history page did not provide a stable cursor");
    }

    const oldestCapturedAt = Math.min(...capturedTimes);
    if (oldestCapturedAt <= window.from.getTime()) {
      return downsampleEnergyHistory([...samples.values()], MAX_HISTORY_POINTS_PER_METER, window);
    }

    const boundaryCount = capturedTimes.filter((capturedAt) => capturedAt === oldestCapturedAt).length;
    if (boundaryCount >= HISTORY_PAGE_SIZE) {
      throw new Error("Telemetry history timestamp density exceeds the safe cursor window");
    }

    const currentCursor = cursorTo.getTime();
    const overlappingBoundaryCursor = oldestCapturedAt + 1;
    cursorTo = new Date(
      overlappingBoundaryCursor < currentCursor ? overlappingBoundaryCursor : currentCursor - 1,
    );
  }

  throw new Error("Telemetry history exceeded the supported pagination window");
}
