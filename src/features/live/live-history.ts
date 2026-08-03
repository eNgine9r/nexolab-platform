import { liveChannelKey } from "@/features/live/live-telemetry";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

const HISTORY_PAGE_SIZE = 1_000;
const MAX_HISTORY_PAGES = 100;
const SEGMENT_PREFIX = "nexolab-live-segment:";
export const LIVE_HISTORY_MAX_POINTS_PER_CHANNEL = 240;
export const LIVE_HISTORY_SOURCE_GAP_MS = 30_000;
export const LIVE_HISTORY_MAX_FUTURE_SKEW_MS = 30_000;

export interface LiveHistoryWindow {
  from: Date;
  to: Date;
}

export interface LiveHistoryResult {
  samples: TelemetrySample[];
  snapshotAt: string;
}

export interface LiveHistoryOrderingState {
  newestCapturedAtByChannel: Map<string, number>;
  pendingBreakChannels: Set<string>;
}

export interface LiveHistoryReconciliation {
  samples: TelemetrySample[];
  state: LiveHistoryOrderingState;
}

function parsedTimestamp(value: string): number {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

function sourceEventId(eventId: string): string {
  return eventId.startsWith(SEGMENT_PREFIX) ? eventId.slice(SEGMENT_PREFIX.length) : eventId;
}

export function isLiveHistorySegmentStart(sample: TelemetrySample): boolean {
  return sample.event_id.startsWith(SEGMENT_PREFIX);
}

function markSegmentStart(sample: TelemetrySample): TelemetrySample {
  if (isLiveHistorySegmentStart(sample)) return sample;
  return { ...sample, event_id: `${SEGMENT_PREFIX}${sample.event_id}` };
}

function clearSegmentStart(sample: TelemetrySample): TelemetrySample {
  if (!isLiveHistorySegmentStart(sample)) return sample;
  return { ...sample, event_id: sourceEventId(sample.event_id) };
}

function isRenderable(sample: TelemetrySample): boolean {
  return sample.quality === "valid" && sample.value !== null && Number.isFinite(sample.value);
}

function belongsToIdentity(sample: TelemetrySample, identity: TelemetrySample): boolean {
  return liveChannelKey(sample) === liveChannelKey(identity);
}

function acceptedSample(sample: TelemetrySample, now = Date.now()): boolean {
  const capturedAt = parsedTimestamp(sample.captured_at);
  return Number.isFinite(capturedAt) && capturedAt <= now + LIVE_HISTORY_MAX_FUTURE_SKEW_MS;
}

function annotateSourceSegments(samples: readonly TelemetrySample[]): TelemetrySample[] {
  const sorted = [...samples].sort(
    (left, right) => parsedTimestamp(left.captured_at) - parsedTimestamp(right.captured_at),
  );
  const annotated: TelemetrySample[] = [];
  let previousRenderableAt: number | null = null;
  let breakPending = false;

  for (const original of sorted) {
    const explicitSegment = isLiveHistorySegmentStart(original);
    const sample = clearSegmentStart(original);
    const capturedAt = parsedTimestamp(sample.captured_at);
    if (!Number.isFinite(capturedAt)) continue;

    if (!isRenderable(sample)) {
      breakPending = true;
      continue;
    }

    const startsSegment =
      explicitSegment ||
      breakPending ||
      (previousRenderableAt !== null && capturedAt - previousRenderableAt > LIVE_HISTORY_SOURCE_GAP_MS);
    annotated.push(startsSegment ? markSegmentStart(sample) : sample);
    previousRenderableAt = capturedAt;
    breakPending = false;
  }

  return annotated;
}

function mergeBucketSample(
  current: TelemetrySample | undefined,
  candidate: TelemetrySample,
): TelemetrySample {
  if (!current) return candidate;
  const selected =
    parsedTimestamp(candidate.captured_at) >= parsedTimestamp(current.captured_at) ? candidate : current;
  const startsSegment = isLiveHistorySegmentStart(current) || isLiveHistorySegmentStart(candidate);
  const normalized = clearSegmentStart(selected);
  return startsSegment ? markSegmentStart(normalized) : normalized;
}

function downsampleChannel(
  samples: readonly TelemetrySample[],
  window: LiveHistoryWindow,
  maximumPoints: number,
): TelemetrySample[] {
  const annotated = annotateSourceSegments(samples);
  if (annotated.length <= maximumPoints) return annotated;
  if (maximumPoints <= 1) return [annotated.at(-1)!];
  if (maximumPoints === 2) return [annotated[0], annotated.at(-1)!];

  const rangeMs = Math.max(1, window.to.getTime() - window.from.getTime());
  const bucketMs = Math.max(1, Math.ceil(rangeMs / (maximumPoints - 2)));
  const buckets = new Map<number, TelemetrySample>();

  for (const sample of annotated) {
    const bucket = Math.floor((parsedTimestamp(sample.captured_at) - window.from.getTime()) / bucketMs);
    buckets.set(bucket, mergeBucketSample(buckets.get(bucket), sample));
  }

  const first = annotated[0];
  const last = annotated.at(-1)!;
  const firstBucket = Math.floor((parsedTimestamp(first.captured_at) - window.from.getTime()) / bucketMs);
  const lastBucket = Math.floor((parsedTimestamp(last.captured_at) - window.from.getTime()) / bucketMs);
  const firstBucketSample = buckets.get(firstBucket);
  const transferFirstBucketSegment =
    firstBucketSample !== undefined &&
    isLiveHistorySegmentStart(firstBucketSample) &&
    sourceEventId(firstBucketSample.event_id) !== sourceEventId(first.event_id);

  buckets.set(firstBucket, first);
  buckets.set(lastBucket, mergeBucketSample(buckets.get(lastBucket), last));

  const sampled = [...buckets.values()]
    .sort((left, right) => parsedTimestamp(left.captured_at) - parsedTimestamp(right.captured_at))
    .slice(-maximumPoints);

  if (transferFirstBucketSegment && sampled.length > 1) sampled[1] = markSegmentStart(sampled[1]);
  return sampled;
}

export function downsampleLiveHistory(
  samples: readonly TelemetrySample[],
  window: LiveHistoryWindow,
  maximumPointsPerChannel = LIVE_HISTORY_MAX_POINTS_PER_CHANNEL,
): TelemetrySample[] {
  const groups = new Map<string, TelemetrySample[]>();

  for (const sample of samples) {
    if (!acceptedSample(sample)) continue;
    const key = liveChannelKey(sample);
    const current = groups.get(key) ?? [];
    current.push(sample);
    groups.set(key, current);
  }

  return [...groups.entries()]
    .sort(([left], [right]) => left.localeCompare(right, "uk-UA"))
    .flatMap(([, channelSamples]) => downsampleChannel(channelSamples, window, maximumPointsPerChannel));
}

export function seedLiveHistoryOrderingState(samples: readonly TelemetrySample[]): LiveHistoryOrderingState {
  const newestCapturedAtByChannel = new Map<string, number>();
  for (const sample of samples) {
    const capturedAt = parsedTimestamp(sample.captured_at);
    if (!acceptedSample(sample) || !Number.isFinite(capturedAt)) continue;
    const key = liveChannelKey(sample);
    const current = newestCapturedAtByChannel.get(key);
    if (current === undefined || capturedAt > current) newestCapturedAtByChannel.set(key, capturedAt);
  }
  return { newestCapturedAtByChannel, pendingBreakChannels: new Set() };
}

export function reconcileLiveHistoryEvents(
  incoming: readonly TelemetrySample[],
  currentState: LiveHistoryOrderingState,
): LiveHistoryReconciliation {
  const newestCapturedAtByChannel = new Map(currentState.newestCapturedAtByChannel);
  const pendingBreakChannels = new Set(currentState.pendingBreakChannels);
  const samples: TelemetrySample[] = [];
  const sorted = [...incoming].sort(
    (left, right) => parsedTimestamp(left.captured_at) - parsedTimestamp(right.captured_at),
  );

  for (const sample of sorted) {
    if (!acceptedSample(sample)) continue;
    const key = liveChannelKey(sample);
    const capturedAt = parsedTimestamp(sample.captured_at);
    const newest = newestCapturedAtByChannel.get(key);
    if (newest !== undefined && capturedAt <= newest) continue;

    newestCapturedAtByChannel.set(key, capturedAt);
    if (!isRenderable(sample)) {
      pendingBreakChannels.add(key);
      continue;
    }

    const startsSegment =
      pendingBreakChannels.has(key) ||
      (newest !== undefined && capturedAt - newest > LIVE_HISTORY_SOURCE_GAP_MS);
    samples.push(startsSegment ? markSegmentStart(sample) : sample);
    pendingBreakChannels.delete(key);
  }

  return {
    samples,
    state: { newestCapturedAtByChannel, pendingBreakChannels },
  };
}

async function loadIdentityHistory(
  adapter: TelemetryAdapter,
  identity: TelemetrySample,
  window: LiveHistoryWindow,
  sharedSnapshotAt: string | undefined,
  signal?: AbortSignal,
): Promise<{ samples: TelemetrySample[]; snapshotAt: string }> {
  const samples = new Map<string, TelemetrySample>();
  let cursorTo = new Date(window.to);
  let snapshotAt = sharedSnapshotAt;

  for (let page = 0; page < MAX_HISTORY_PAGES; page += 1) {
    const response = await adapter.history(
      {
        node_id: identity.node_id,
        equipment_id: identity.equipment_id,
        channel_id: identity.channel_id,
        metric: identity.metric,
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
    if (snapshotAt === undefined) snapshotAt = responseSnapshotAt;
    if (responseSnapshotAt !== snapshotAt) {
      throw new Error("Telemetry history ingestion snapshot changed during channel comparison");
    }

    for (const sample of response.items) {
      if (belongsToIdentity(sample, identity) && acceptedSample(sample)) {
        samples.set(sourceEventId(sample.event_id), sample);
      }
    }

    if (response.next_offset === null) {
      return { samples: [...samples.values()], snapshotAt };
    }

    const capturedTimes = response.items
      .map((sample) => parsedTimestamp(sample.captured_at))
      .filter(Number.isFinite);
    if (capturedTimes.length === 0) {
      throw new Error("Telemetry history page did not provide a stable captured-time cursor");
    }

    const oldestCapturedAt = Math.min(...capturedTimes);
    if (oldestCapturedAt <= window.from.getTime()) {
      return { samples: [...samples.values()], snapshotAt };
    }
    if (capturedTimes.filter((capturedAt) => capturedAt === oldestCapturedAt).length >= HISTORY_PAGE_SIZE) {
      throw new Error("Telemetry history timestamp density exceeds the safe cursor window");
    }

    const currentCursor = cursorTo.getTime();
    cursorTo = new Date(Math.min(oldestCapturedAt + 1, currentCursor - 1));
  }

  throw new Error("Telemetry history exceeded the supported pagination window");
}

export async function loadCompleteLiveHistory(
  adapter: TelemetryAdapter,
  identities: readonly TelemetrySample[],
  window: LiveHistoryWindow,
  signal?: AbortSignal,
): Promise<LiveHistoryResult> {
  if (identities.length === 0) {
    throw new Error("At least one channel identity is required for history loading");
  }

  const allSamples: TelemetrySample[] = [];
  let snapshotAt: string | undefined;

  for (const identity of identities) {
    const result = await loadIdentityHistory(adapter, identity, window, snapshotAt, signal);
    snapshotAt = result.snapshotAt;
    allSamples.push(...result.samples);
  }

  return {
    samples: downsampleLiveHistory(allSamples, window),
    snapshotAt: snapshotAt!,
  };
}

export function mergeLiveHistoryTail(
  current: readonly TelemetrySample[],
  incoming: readonly TelemetrySample[],
  selectedKeys: ReadonlySet<string>,
  window: LiveHistoryWindow,
): TelemetrySample[] {
  const from = window.from.getTime();
  const to = window.to.getTime();
  const byEventId = new Map<string, TelemetrySample>();

  for (const sample of [...current, ...incoming]) {
    const capturedAt = parsedTimestamp(sample.captured_at);
    if (
      !selectedKeys.has(liveChannelKey(sample)) ||
      !acceptedSample(sample) ||
      capturedAt < from ||
      capturedAt > to
    ) {
      continue;
    }
    const key = sourceEventId(sample.event_id);
    const existing = byEventId.get(key);
    if (!existing || parsedTimestamp(sample.captured_at) >= parsedTimestamp(existing.captured_at)) {
      byEventId.set(key, sample);
    }
  }

  return downsampleLiveHistory([...byEventId.values()], window);
}

export function liveHistorySegments(samples: readonly TelemetrySample[]): TelemetrySample[][] {
  const sorted = [...samples].sort(
    (left, right) => parsedTimestamp(left.captured_at) - parsedTimestamp(right.captured_at),
  );
  const segments: TelemetrySample[][] = [];

  for (const sample of sorted) {
    if (segments.length === 0 || isLiveHistorySegmentStart(sample)) segments.push([]);
    segments.at(-1)!.push(clearSegmentStart(sample));
  }
  return segments.filter((segment) => segment.length > 0);
}
