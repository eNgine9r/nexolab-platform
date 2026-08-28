import { deriveChartSourceGapMs } from "@/features/charts/continuity";
import type { EnergyCadenceAuthority } from "@/features/energy/energy-cadence-authority";
import {
  clearEnergyHistoryBreakPending,
  clearEnergyHistoryMarkers,
  energyHistorySourceEventId,
  isEnergyHistoryBreakPending,
  isEnergyHistoryInferredSegmentStart,
  isEnergyHistorySegmentStart,
  markEnergyHistoryBreakPending,
  markEnergyHistoryInferredSegmentStart,
  markEnergyHistorySegmentStart,
} from "@/features/energy/energy-history-segment";
import { isEnergySample, resolveEnergyMeter, type EnergyMetricId } from "@/features/energy/energy-telemetry";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

const HISTORY_PAGE_SIZE = 1_000;
const MAX_HISTORY_PAGES = 100;
const SOURCE_CADENCE_TAIL_CACHE_LIMIT = 512;
const SOURCE_CADENCE_RECENT_TIMESTAMP_LIMIT = 4;
export const MAX_HISTORY_POINTS_PER_METER = 240;
export const ENERGY_HISTORY_MAX_FUTURE_SKEW_MS = 30_000;

interface EnergyHistoryCadenceState {
  rawTimestampMs: number[];
  maximumSourceGapMs: number;
}

type SourceGapMarker = "durable" | "inferred";

interface HistoricalSourceGapPolicy {
  maximumSourceGapMs: number;
  marker: SourceGapMarker;
}

type SourceGapPolicyForPair = (
  previousAtMs: number,
  capturedAtMs: number,
) => HistoricalSourceGapPolicy | null;

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

function uniqueOrderedTimestamps(samples: readonly TelemetrySample[]): number[] {
  const timestamps = samples
    .filter(isAcceptedEnergyHistorySample)
    .map((sample) => Date.parse(sample.captured_at))
    .filter(Number.isFinite);
  return [...new Set(timestamps)].sort((left, right) => left - right);
}

function renderableEnergyHistoryTimestamps(samples: readonly TelemetrySample[]): number[] {
  const timestamps = samples
    .filter(isRenderableEnergyHistorySample)
    .map((sample) => Date.parse(sample.captured_at))
    .filter(Number.isFinite);
  return [...new Set(timestamps)].sort((left, right) => left - right);
}

function deriveSourceGapFromTimestamps(timestamps: readonly number[]): number | null {
  const ordered = [...new Set(timestamps.filter(Number.isFinite))].sort((left, right) => left - right);
  if (ordered.length < 2) return null;

  const points =
    ordered.length === 2 ? [ordered[0], ordered[1], ordered[1] + (ordered[1] - ordered[0])] : ordered;
  return deriveChartSourceGapMs(
    points.map((timestampMs) => ({ id: `energy-cadence:${timestampMs}`, timestampMs })),
  );
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
  return cadenceStateFromTimestamps(uniqueOrderedTimestamps(samples));
}

function deriveHistoricalSourceGapByTimestamp(
  samples: readonly TelemetrySample[],
): Map<number, HistoricalSourceGapPolicy> {
  const acquisitionTimestamps = uniqueOrderedTimestamps(samples);
  const renderableTimestamps = new Set(renderableEnergyHistoryTimestamps(samples));
  const policyByTimestamp = new Map<number, HistoricalSourceGapPolicy>();

  for (let index = 1; index < acquisitionTimestamps.length; index += 1) {
    const capturedAt = acquisitionTimestamps[index];
    if (!renderableTimestamps.has(capturedAt)) continue;

    const forward = acquisitionTimestamps.slice(index, index + SOURCE_CADENCE_RECENT_TIMESTAMP_LIMIT);
    const backward = acquisitionTimestamps.slice(
      Math.max(0, index - SOURCE_CADENCE_RECENT_TIMESTAMP_LIMIT),
      index,
    );
    const forwardGapMs = deriveSourceGapFromTimestamps(forward);
    const backwardGapMs = deriveSourceGapFromTimestamps(backward);
    const candidates = [forwardGapMs, backwardGapMs].filter((value): value is number => value !== null);
    if (candidates.length === 0) continue;

    // Timestamp-only cadence is inherently ambiguous around runtime cadence changes.
    // Prefer the stricter observable tolerance and keep the marker reversible. A
    // persisted cadence authority can later recompute it deterministically.
    policyByTimestamp.set(capturedAt, {
      maximumSourceGapMs: Math.min(...candidates),
      marker: "inferred",
    });
  }

  return policyByTimestamp;
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

function annotateSourceSegments(
  samples: readonly TelemetrySample[],
  previousRenderableAt: number | null = null,
  initialBreakPending = false,
  maximumSourceGapMs: number | null | undefined = undefined,
  sourceGapMarker: SourceGapMarker = "durable",
  sourceGapPolicyForPair: SourceGapPolicyForPair | null = null,
): EnergyHistorySegmentAnnotation {
  const sorted = [...samples].sort(
    (left, right) => Date.parse(left.captured_at) - Date.parse(right.captured_at),
  );
  const historicalSourceGapByTimestamp =
    maximumSourceGapMs === undefined ? deriveHistoricalSourceGapByTimestamp(sorted) : null;
  const annotated: TelemetrySample[] = [];
  let previousAt = previousRenderableAt;
  let breakPending = initialBreakPending;

  for (const sourceSample of sorted) {
    const inferredSegment = isEnergyHistoryInferredSegmentStart(sourceSample.event_id);
    const explicitSegment = isEnergyHistorySegmentStart(sourceSample.event_id) && !inferredSegment;
    const pendingAfterSample = isEnergyHistoryBreakPending(sourceSample.event_id);
    const sample = clearEnergyHistoryMarkers(sourceSample);
    const capturedAt = Date.parse(sample.captured_at);
    if (!Number.isFinite(capturedAt)) continue;

    if (!isRenderableEnergyHistorySample(sample)) {
      if (previousAt !== null && capturedAt >= previousAt) breakPending = true;
      continue;
    }

    const authoritativePolicy =
      previousAt !== null && sourceGapPolicyForPair !== null
        ? sourceGapPolicyForPair(previousAt, capturedAt)
        : null;
    const historicalPolicy = historicalSourceGapByTimestamp?.get(capturedAt) ?? null;
    const fallbackPolicy =
      maximumSourceGapMs === undefined
        ? historicalPolicy
        : maximumSourceGapMs === null
          ? null
          : { maximumSourceGapMs, marker: sourceGapMarker };
    const effectivePolicy = authoritativePolicy ?? fallbackPolicy;
    const inferredSourceGap =
      previousAt !== null &&
      capturedAt >= previousAt &&
      effectivePolicy !== null &&
      capturedAt - previousAt > effectivePolicy.maximumSourceGapMs;
    const preserveExistingInferredSegment = authoritativePolicy === null && inferredSegment;

    let annotatedSample = sample;
    if (explicitSegment || breakPending) {
      annotatedSample = markEnergyHistorySegmentStart(sample);
    } else if (preserveExistingInferredSegment || inferredSourceGap) {
      annotatedSample =
        effectivePolicy?.marker === "durable"
          ? markEnergyHistorySegmentStart(sample)
          : markEnergyHistoryInferredSegmentStart(sample);
    }

    annotated.push(annotatedSample);
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
  const explicitSegment = [current, candidate].some(
    (sample) =>
      isEnergyHistorySegmentStart(sample.event_id) && !isEnergyHistoryInferredSegmentStart(sample.event_id),
  );
  const inferredSegment = [current, candidate].some((sample) =>
    isEnergyHistoryInferredSegmentStart(sample.event_id),
  );
  const normalized = clearEnergyHistoryMarkers(selected);
  if (explicitSegment) return markEnergyHistorySegmentStart(normalized);
  if (inferredSegment) return markEnergyHistoryInferredSegmentStart(normalized);
  return normalized;
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
  const firstBucketLaterSegmentIsInferred =
    firstBucketContainsLaterSegment &&
    firstBucketSample !== undefined &&
    isEnergyHistoryInferredSegmentStart(firstBucketSample.event_id);
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
      sampled[firstIndex + 1] = firstBucketLaterSegmentIsInferred
        ? markEnergyHistoryInferredSegmentStart(sampled[firstIndex + 1])
        : markEnergyHistorySegmentStart(sampled[firstIndex + 1]);
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
  cadenceAuthority: EnergyCadenceAuthority | null = null,
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
    .flatMap(([unitId, meterSamples]) => {
      const cadenceState = cadenceStateFromSamples(meterSamples);
      const annotation = annotateSourceSegments(
        meterSamples,
        null,
        false,
        undefined,
        "inferred",
        cadenceAuthority === null
          ? null
          : (previousAtMs, capturedAtMs) => {
              const maximumSourceGapMs = cadenceAuthority.maximumSourceGapMs(
                unitId,
                previousAtMs,
                capturedAtMs,
              );
              return maximumSourceGapMs === null ? null : { maximumSourceGapMs, marker: "durable" };
            },
      );
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
  cadenceAuthority: EnergyCadenceAuthority | null = null,
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
    const fallbackThresholds = [
      inheritedCadenceState?.maximumSourceGapMs,
      incomingCadenceState?.maximumSourceGapMs,
    ].filter((value): value is number => value !== undefined);
    const maximumSourceGapMs = fallbackThresholds.length > 0 ? Math.min(...fallbackThresholds) : null;
    // Retained history may be heavily downsampled, so fallback cadence comes from a
    // bounded raw tail. Timestamp-only evidence is deliberately conservative: it may
    // retain an extra inferred break, but it never erases a real outage. Persisted
    // cadence authority, when available for the pair, overrides this fallback.
    const annotation = annotateSourceSegments(
      incomingSamples,
      lastExistingAt,
      existingBreakPending,
      maximumSourceGapMs,
      "inferred",
      cadenceAuthority === null
        ? null
        : (previousAtMs, capturedAtMs) => {
            const authoritativeGapMs = cadenceAuthority.maximumSourceGapMs(
              unitId,
              previousAtMs,
              capturedAtMs,
            );
            return authoritativeGapMs === null
              ? null
              : { maximumSourceGapMs: authoritativeGapMs, marker: "durable" };
          },
    );
    const nextCadenceState = cadenceStateFromTimestamps([
      ...(inheritedCadenceState?.rawTimestampMs ?? []),
      ...uniqueOrderedTimestamps(incomingSamples),
    ]);
    const byEventId = new Map<string, TelemetrySample>();

    for (const sample of [...normalizedExisting, ...annotation.samples]) {
      byEventId.set(energyHistorySourceEventId(sample.event_id), sample);
    }

    const sampled = bucketDownsampleAnnotated([...byEventId.values()], MAX_HISTORY_POINTS_PER_METER, window);
    const reduced = applyPendingBreak(sampled, annotation.breakPending);
    const latestReduced = reduced.filter(isRenderableEnergyHistorySample).at(-1) ?? null;

    rememberSourceCadenceForTail(
      latestReduced,
      nextCadenceState ?? inheritedCadenceState ?? incomingCadenceState,
    );
    merged.push(...reduced);
  }

  return merged;
}

export async function loadCompleteEnergyHistory(
  adapter: TelemetryAdapter,
  window: EnergyHistoryWindow,
  signal?: AbortSignal,
  cadenceAuthority: EnergyCadenceAuthority | null = null,
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
      return downsampleEnergyHistory(
        [...samples.values()],
        MAX_HISTORY_POINTS_PER_METER,
        window,
        cadenceAuthority,
      );
    }

    const capturedTimes = response.items
      .map((sample) => Date.parse(sample.captured_at))
      .filter(Number.isFinite);
    if (capturedTimes.length === 0) {
      throw new Error("Telemetry history page did not provide a stable cursor");
    }

    const oldestCapturedAt = Math.min(...capturedTimes);
    if (oldestCapturedAt <= window.from.getTime()) {
      return downsampleEnergyHistory(
        [...samples.values()],
        MAX_HISTORY_POINTS_PER_METER,
        window,
        cadenceAuthority,
      );
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
