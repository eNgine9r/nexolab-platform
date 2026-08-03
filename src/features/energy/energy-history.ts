import {
  clearEnergyHistorySegmentStart,
  energyHistorySourceEventId,
  isEnergyHistorySegmentStart,
  markEnergyHistorySegmentStart,
} from "@/features/energy/energy-history-segment";
import { isEnergySample, resolveEnergyMeter, type EnergyMetricId } from "@/features/energy/energy-telemetry";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

const HISTORY_PAGE_SIZE = 1_000;
const MAX_HISTORY_PAGES = 100;
export const MAX_HISTORY_POINTS_PER_METER = 240;
export const ENERGY_HISTORY_MAX_FUTURE_SKEW_MS = 30_000;
export const ENERGY_HISTORY_SOURCE_GAP_MS = 30_000;

export interface EnergyHistoryWindow {
  nodeId: string;
  metric: EnergyMetricId;
  from: Date;
  to: Date;
}

function isRenderableEnergyHistorySample(sample: TelemetrySample): boolean {
  return sample.quality === "valid" && sample.value !== null && Number.isFinite(sample.value);
}

function isAcceptedEnergyHistorySample(sample: TelemetrySample): boolean {
  return isEnergySample(sample) && Number.isFinite(Date.parse(sample.captured_at));
}

function annotateSourceSegments(
  samples: readonly TelemetrySample[],
  previousRenderableAt: number | null = null,
): TelemetrySample[] {
  const sorted = [...samples].sort(
    (left, right) => Date.parse(left.captured_at) - Date.parse(right.captured_at),
  );
  const annotated: TelemetrySample[] = [];
  let previousAt = previousRenderableAt;
  let breakPending = false;

  for (const sourceSample of sorted) {
    const sample = clearEnergyHistorySegmentStart(sourceSample);
    const capturedAt = Date.parse(sample.captured_at);
    if (!Number.isFinite(capturedAt)) continue;

    if (!isRenderableEnergyHistorySample(sample)) {
      if (previousAt !== null && capturedAt >= previousAt) breakPending = true;
      continue;
    }

    const explicitSegment = isEnergyHistorySegmentStart(sourceSample.event_id);
    const startsSegment =
      explicitSegment ||
      (previousAt !== null &&
        capturedAt >= previousAt &&
        (breakPending || capturedAt - previousAt > ENERGY_HISTORY_SOURCE_GAP_MS));

    annotated.push(startsSegment ? markEnergyHistorySegmentStart(sample) : sample);
    if (previousAt === null || capturedAt >= previousAt) previousAt = capturedAt;
    breakPending = false;
  }

  return annotated;
}

function mergeBucketSample(
  current: TelemetrySample | undefined,
  candidate: TelemetrySample,
): TelemetrySample {
  if (!current) return candidate;

  const selected = Date.parse(current.captured_at) <= Date.parse(candidate.captured_at) ? candidate : current;
  const startsSegment =
    isEnergyHistorySegmentStart(current.event_id) || isEnergyHistorySegmentStart(candidate.event_id);
  const normalized = clearEnergyHistorySegmentStart(selected);
  return startsSegment ? markEnergyHistorySegmentStart(normalized) : normalized;
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
  buckets.set(firstBucket, mergeBucketSample(buckets.get(firstBucket), first));
  buckets.set(lastBucket, mergeBucketSample(buckets.get(lastBucket), last));

  return [...buckets.values()]
    .sort((left, right) => Date.parse(left.captured_at) - Date.parse(right.captured_at))
    .slice(-maximumPoints);
}

function downsampleAnnotatedEnergyHistory(
  samples: readonly TelemetrySample[],
  maximumPointsPerMeter: number,
  window?: Pick<EnergyHistoryWindow, "from" | "to">,
): TelemetrySample[] {
  const byMeter = new Map<number, TelemetrySample[]>();

  for (const sample of samples) {
    if (!isRenderableEnergyHistorySample(sample)) continue;
    const meter = resolveEnergyMeter(sample);
    if (!meter) continue;
    const current = byMeter.get(meter.unitId) ?? [];
    current.push(sample);
    byMeter.set(meter.unitId, current);
  }

  return [...byMeter.entries()]
    .sort(([left], [right]) => left - right)
    .flatMap(([, meterSamples]) =>
      bucketDownsampleAnnotated(meterSamples, maximumPointsPerMeter, window),
    );
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
    .flatMap(([, meterSamples]) =>
      bucketDownsampleAnnotated(annotateSourceSegments(meterSamples), maximumPointsPerMeter, window),
    );
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
    const lastExistingAt =
      existing
        .filter(isRenderableEnergyHistorySample)
        .map((sample) => Date.parse(sample.captured_at))
        .filter(Number.isFinite)
        .at(-1) ?? null;
    const annotatedIncoming = annotateSourceSegments(incomingByMeter.get(unitId) ?? [], lastExistingAt);
    const byEventId = new Map<string, TelemetrySample>();

    for (const sample of [...existing, ...annotatedIncoming]) {
      byEventId.set(energyHistorySourceEventId(sample.event_id), sample);
    }

    merged.push(
      ...bucketDownsampleAnnotated([...byEventId.values()], MAX_HISTORY_POINTS_PER_METER, window),
    );
  }

  return downsampleAnnotatedEnergyHistory(merged, MAX_HISTORY_POINTS_PER_METER, window);
}

export async function loadCompleteEnergyHistory(
  adapter: TelemetryAdapter,
  window: EnergyHistoryWindow,
  signal?: AbortSignal,
): Promise<TelemetrySample[]> {
  const samples = new Map<string, TelemetrySample>();
  let cursorTo = new Date(window.to);

  for (let page = 0; page < MAX_HISTORY_PAGES; page += 1) {
    const response = await adapter.history(
      {
        node_id: window.nodeId,
        metric: window.metric,
        from: window.from,
        to: cursorTo,
        limit: HISTORY_PAGE_SIZE,
        offset: 0,
      },
      signal,
    );

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
