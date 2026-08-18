import { deriveChartSourceGapMs } from "@/features/charts/continuity";
import type { ChartPoint, ChartSegment } from "@/features/charts/domain";
import { reduceChartSegments } from "@/features/charts/reduction";
import { liveChannelKey } from "@/features/live/live-telemetry";
import {
  loadCompleteTelemetryHistory,
  type TelemetryHistoryWindow,
} from "@/lib/telemetry/history";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

const SEGMENT_PREFIX = "nexolab-live-segment:";
export const LIVE_HISTORY_MAX_POINTS_PER_CHANNEL = 240;
export const LIVE_HISTORY_MIN_SOURCE_GAP_MS = 30_000;
export const LIVE_HISTORY_MAX_FUTURE_SKEW_MS = 30_000;

export type LiveHistoryWindow = TelemetryHistoryWindow;

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

function acceptedSample(sample: TelemetrySample, now = Date.now()): boolean {
  const capturedAt = parsedTimestamp(sample.captured_at);
  return Number.isFinite(capturedAt) && capturedAt <= now + LIVE_HISTORY_MAX_FUTURE_SKEW_MS;
}

export function advanceLiveHistoryWindow(
  current: LiveHistoryWindow,
  incoming: readonly TelemetrySample[],
): LiveHistoryWindow {
  const fromMs = current.from.getTime();
  const toMs = current.to.getTime();
  const durationMs = toMs - fromMs;
  if (!Number.isFinite(durationMs) || durationMs <= 0) {
    throw new Error("Live history window must have a positive finite duration");
  }

  let nextToMs = toMs;
  for (const sample of incoming) {
    if (!acceptedSample(sample)) continue;
    const capturedAt = parsedTimestamp(sample.captured_at);
    if (capturedAt > nextToMs) nextToMs = capturedAt;
  }

  if (nextToMs === toMs) return current;
  return {
    from: new Date(nextToMs - durationMs),
    to: new Date(nextToMs),
  };
}

function annotateSourceSegments(samples: readonly TelemetrySample[]): TelemetrySample[] {
  const sorted = [...samples].sort(
    (left, right) => parsedTimestamp(left.captured_at) - parsedTimestamp(right.captured_at),
  );
  const sourceGapMs = deriveChartSourceGapMs(
    sorted.map((sample) => ({
      id: sourceEventId(sample.event_id),
      timestampMs: parsedTimestamp(sample.captured_at),
    })),
    LIVE_HISTORY_MIN_SOURCE_GAP_MS,
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
      (previousRenderableAt !== null && capturedAt - previousRenderableAt > sourceGapMs);
    annotated.push(startsSegment ? markSegmentStart(sample) : sample);
    previousRenderableAt = capturedAt;
    breakPending = false;
  }

  return annotated;
}

function alarmTransitionPins(samples: readonly TelemetrySample[]): Set<string> {
  const pins = new Set<string>();
  let previous: TelemetrySample | null = null;

  for (const sample of samples) {
    if (previous === null) {
      if (sample.alarm !== null) pins.add(sourceEventId(sample.event_id));
      previous = sample;
      continue;
    }

    if (previous.alarm !== sample.alarm) {
      pins.add(sourceEventId(previous.event_id));
      pins.add(sourceEventId(sample.event_id));
    }
    previous = sample;
  }

  return pins;
}

function downsampleChannel(
  samples: readonly TelemetrySample[],
  window: LiveHistoryWindow,
  maximumPoints: number,
): TelemetrySample[] {
  const annotated = annotateSourceSegments(samples);
  if (annotated.length <= maximumPoints) return annotated;

  const seriesKey = annotated[0] ? liveChannelKey(annotated[0]) : "unknown";
  const pins = alarmTransitionPins(annotated);
  const originals = new Map(
    annotated.map((sample) => [sourceEventId(sample.event_id), clearSegmentStart(sample)] as const),
  );
  const segments: ChartSegment[] = liveHistorySegments(annotated).map((segment, index) => {
    const points: ChartPoint[] = segment.map((sample) => {
      const id = sourceEventId(sample.event_id);
      return {
        id,
        timestampMs: parsedTimestamp(sample.captured_at),
        value: sample.value!,
        quality: sample.quality,
        sourceEventId: id,
        ...(pins.has(id) ? { pinReasons: ["alarm"] as const } : {}),
      };
    });
    return {
      id: `${seriesKey}:segment:${index}:${points[0]?.timestampMs ?? "empty"}`,
      seriesKey,
      points,
      ...(index > 0 && points[0]
        ? { precedingBreak: { reason: "explicit_gap" as const, atMs: points[0].timestampMs } }
        : {}),
    };
  });

  const reduced = reduceChartSegments(segments, {
    maximumPoints,
    bucketOriginMs: window.from.getTime(),
  });

  return reduced.flatMap((segment, segmentIndex) =>
    segment.points.flatMap((point, pointIndex) => {
      const original = originals.get(point.id);
      if (!original) return [];
      return segmentIndex > 0 && pointIndex === 0 ? [markSegmentStart(original)] : [original];
    }),
  );
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

    const startsSegment = pendingBreakChannels.has(key);
    samples.push(startsSegment ? markSegmentStart(sample) : sample);
    pendingBreakChannels.delete(key);
  }

  return {
    samples,
    state: { newestCapturedAtByChannel, pendingBreakChannels },
  };
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
    const result = await loadCompleteTelemetryHistory(
      adapter,
      {
        node_id: identity.node_id,
        equipment_id: identity.equipment_id,
        channel_id: identity.channel_id,
        metric: identity.metric,
      },
      window,
      { signal, snapshotAt },
    );
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
