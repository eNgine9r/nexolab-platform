import { deriveChartSourceGapMs } from "@/features/charts/continuity";
import type { ChartPoint, ChartSegment } from "@/features/charts/domain";
import { chartPointBudget } from "@/features/charts/point-budget";
import { reduceChartSegmentsPreservingEvidence } from "@/features/charts/reduction";
import {
  CADENCE_OBSERVATION_LIMIT,
  seedCadenceFromSamples,
  type CadenceObservations,
} from "@/features/live/freshness";
import { recordLiveIntervalSamples, type LiveIntervalColumns } from "@/features/live/live-interval-columns";
import { liveChannelKey } from "@/features/live/live-telemetry";
import { loadCompleteTelemetryHistoryForSeries, type TelemetryHistoryWindow } from "@/lib/telemetry/history";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

const SEGMENT_PREFIX = "nexolab-live-segment:";
export const LIVE_HISTORY_MAX_POINTS_PER_CHANNEL = chartPointBudget("live-history");
export const LIVE_HISTORY_MIN_SOURCE_GAP_MS = 30_000;
export const LIVE_HISTORY_MAX_FUTURE_SKEW_MS = 30_000;
/**
 * Continuity tolerance for a live-tail channel whose raw cadence is unknown (no persisted history
 * and no cadence observation yet): 3 × the slowest standard acquisition preset (60 s).
 */
export const LIVE_HISTORY_FALLBACK_SOURCE_GAP_MS = 180_000;
/**
 * A channel may exceed its point budget by this share (at least 16 points) before the live tail is
 * re-reduced. Without hysteresis every new sample would re-reduce the whole series.
 */
const LIVE_TAIL_REDUCTION_HYSTERESIS_RATIO = 0.25;
const LIVE_TAIL_REDUCTION_HYSTERESIS_MINIMUM = 16;
/** Three distinct timestamps give the two spacings `deriveChartSourceGapMs` needs. */
const MIN_RAW_TIMESTAMPS_FOR_TOLERANCE = 3;

export type LiveHistoryWindow = TelemetryHistoryWindow;

export interface LiveHistoryResult {
  /** Chart series, reduced to the chart point budget. Never use for cadence. */
  samples: TelemetrySample[];
  snapshotAt: string;
  /**
   * #1522: newest raw (pre-reduction) accepted samples per channel, bounded to
   * the cadence observation window. Reduced chart points are spaced by bucket
   * width, not by acquisition cadence, and would hide stale data.
   */
  cadenceSamples: TelemetrySample[];
  /**
   * #1660: raw (pre-reduction) per-channel measurement columns for exact interval statistics.
   * Compact numbers only (timestamp + value), never the reduced chart series.
   */
  intervalColumns: LiveIntervalColumns;
  /**
   * #1805: per-channel continuity tolerance derived once from the RAW samples. The live tail is
   * appended with this tolerance; it is never re-derived from reduced chart points.
   */
  sourceGapMsByChannel: Map<string, number>;
}

/** Resolves the raw-derived continuity tolerance for a live channel key, if known. */
export type LiveSourceGapLookup = (channelKey: string) => number | undefined;

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

/**
 * Moves a rolling window forward with wall-clock time, keeping its duration. Without this a
 * silent channel's last line would keep reaching the right edge and look live (chart audit
 * 2026-11-21). Returns the same object when no move is needed.
 */
export function advanceWindowToClock(current: LiveHistoryWindow, nowMs: number): LiveHistoryWindow {
  const fromMs = current.from.getTime();
  const toMs = current.to.getTime();
  if (!Number.isFinite(nowMs) || !(toMs > fromMs) || nowMs <= toMs) return current;
  return { from: new Date(nowMs - (toMs - fromMs)), to: new Date(nowMs) };
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

function rawSourceGapMs(sorted: readonly TelemetrySample[]): number {
  return deriveChartSourceGapMs(
    sorted.map((sample) => ({
      id: sourceEventId(sample.event_id),
      timestampMs: parsedTimestamp(sample.captured_at),
    })),
    LIVE_HISTORY_MIN_SOURCE_GAP_MS,
  );
}

function annotateSourceSegments(samples: readonly TelemetrySample[]): TelemetrySample[] {
  const sorted = [...samples].sort(
    (left, right) => parsedTimestamp(left.captured_at) - parsedTimestamp(right.captured_at),
  );
  // Only ever called on RAW samples (history load): the median spacing is the acquisition cadence.
  const sourceGapMs = rawSourceGapMs(sorted);
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
  return reduceAnnotatedChannel(annotateSourceSegments(samples), window, maximumPoints);
}

/**
 * Reduces one channel whose continuity is ALREADY decided (segment-start markers set from raw
 * data). It never re-derives gaps, so it is safe to apply to previously reduced points.
 */
function reduceAnnotatedChannel(
  annotated: readonly TelemetrySample[],
  window: LiveHistoryWindow,
  maximumPoints: number,
): TelemetrySample[] {
  if (annotated.length <= maximumPoints) return [...annotated];

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

  const reduced = reduceChartSegmentsPreservingEvidence(segments, {
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
  maximumPointsPerChannel = LIVE_HISTORY_MAX_POINTS_PER_CHANNEL,
): Promise<LiveHistoryResult> {
  if (identities.length === 0) {
    throw new Error("At least one channel identity is required for history loading");
  }

  // #1809: channels load in parallel under one snapshot (bounded by the shared history limiter).
  // Each channel is reduced as soon as it has loaded; only compact raw columns (for exact
  // statistics) and the reduced series are kept, not every channel's raw sample objects.
  const intervalColumns: LiveIntervalColumns = {};
  const sourceGapMsByChannel = new Map<string, number>();
  const perChannel = await loadCompleteTelemetryHistoryForSeries(
    adapter,
    identities.map((identity) => ({
      node_id: identity.node_id,
      equipment_id: identity.equipment_id,
      channel_id: identity.channel_id,
      metric: identity.metric,
    })),
    window,
    { signal },
    (result) => {
      recordLiveIntervalSamples(
        intervalColumns,
        result.samples.filter((sample) => acceptedSample(sample)),
      );
      for (const [key, gapMs] of deriveLiveSourceGapMsByChannel(result.samples)) {
        sourceGapMsByChannel.set(key, gapMs);
      }
      return {
        snapshotAt: result.snapshotAt,
        reduced: downsampleLiveHistory(result.samples, window, maximumPointsPerChannel),
        cadence: newestRawSamplesPerChannel(result.samples, CADENCE_OBSERVATION_LIMIT),
      };
    },
  );
  // Same channel order as a single downsampleLiveHistory call (stable sort keeps time order).
  const samples = perChannel
    .flatMap((channel) => channel.reduced)
    .sort((left, right) => liveChannelKey(left).localeCompare(liveChannelKey(right), "uk-UA"));
  return {
    samples,
    intervalColumns,
    snapshotAt: perChannel[0].snapshotAt,
    cadenceSamples: perChannel.flatMap((channel) => channel.cadence),
    sourceGapMsByChannel,
  };
}

/** #1805: per-channel continuity tolerance from RAW samples (the acquisition cadence × 3, ≥ 30 s). */
export function deriveLiveSourceGapMsByChannel(rawSamples: readonly TelemetrySample[]): Map<string, number> {
  const groups = new Map<string, TelemetrySample[]>();
  for (const sample of rawSamples) {
    if (!acceptedSample(sample)) continue;
    const key = liveChannelKey(sample);
    const current = groups.get(key);
    if (current) current.push(sample);
    else groups.set(key, [sample]);
  }
  const result = new Map<string, number>();
  for (const [key, channelSamples] of groups) {
    // Fewer than two spacings cannot establish a cadence (e.g. a new 60 s channel). Leave the
    // channel out so the live cadence observation or the fallback decides, instead of freezing
    // the 30 s minimum and breaking every on-time sample.
    const distinct = new Set(channelSamples.map((sample) => parsedTimestamp(sample.captured_at)));
    if (distinct.size < MIN_RAW_TIMESTAMPS_FOR_TOLERANCE) continue;
    channelSamples.sort(
      (left, right) => parsedTimestamp(left.captured_at) - parsedTimestamp(right.captured_at),
    );
    result.set(key, rawSourceGapMs(channelSamples));
  }
  return result;
}

/**
 * #1522: seeds cadence from a history load. Accepts only the raw cadence tail
 * by type, so the chart-reduced `samples` can never be used by mistake.
 */
export function seedCadenceFromHistoryLoad(
  observations: CadenceObservations,
  result: Pick<LiveHistoryResult, "cadenceSamples">,
): CadenceObservations {
  return seedCadenceFromSamples(observations, result.cadenceSamples, liveChannelKey);
}

function newestRawSamplesPerChannel(samples: readonly TelemetrySample[], limit: number): TelemetrySample[] {
  const groups = new Map<string, TelemetrySample[]>();
  for (const sample of samples) {
    if (!acceptedSample(sample)) continue;
    const key = liveChannelKey(sample);
    const current = groups.get(key);
    if (current) current.push(sample);
    else groups.set(key, [sample]);
  }
  return [...groups.values()].flatMap((channelSamples) =>
    channelSamples
      .sort((left, right) => parsedTimestamp(left.captured_at) - parsedTimestamp(right.captured_at))
      .slice(-limit),
  );
}

export interface LiveHistoryTailOptions {
  /** Raw-derived continuity tolerance per channel; unknown channels use the fallback tolerance. */
  sourceGapMsFor?: LiveSourceGapLookup;
  /**
   * Channels whose last live sample was not renderable (invalid quality or missing value). The next
   * renderable sample of such a channel starts a new segment. Mutated in place so the state
   * survives between single-sample calls.
   */
  pendingBreakChannels?: Set<string>;
}

/**
 * #1805: appends raw live samples to an already reduced, continuity-annotated history.
 *
 * Continuity of `current` was decided on raw data and is kept as is. Each new sample is compared
 * with the previous retained point of its channel using the raw-derived tolerance, never with a
 * tolerance re-derived from reduced points (which turned minute-spaced reduced points into false
 * "source gaps" and broke continuous 24 h charts into dozens of pieces). Points that left the
 * window are dropped. A channel is re-reduced only when it exceeds its budget by the hysteresis
 * margin, and the re-reduction respects the existing segment markers.
 */
export function appendLiveHistoryTail(
  current: readonly TelemetrySample[],
  incoming: readonly TelemetrySample[],
  window: LiveHistoryWindow,
  maximumPointsPerChannel = LIVE_HISTORY_MAX_POINTS_PER_CHANNEL,
  options: LiveHistoryTailOptions = {},
): TelemetrySample[] {
  const from = window.from.getTime();
  const to = window.to.getTime();
  const inWindow = (sample: TelemetrySample) => {
    const capturedAt = parsedTimestamp(sample.captured_at);
    return acceptedSample(sample) && capturedAt >= from && capturedAt <= to;
  };
  const byChannel = new Map<string, TelemetrySample[]>();
  const unsorted = new Set<string>();
  // Source event id -> the sample object currently retained in its channel list. A repeated
  // event keeps the newest captured_at (repository invariant).
  const retained = new Map<string, TelemetrySample>();

  for (const sample of current) {
    if (!inWindow(sample)) continue;
    const id = sourceEventId(sample.event_id);
    const existing = retained.get(id);
    if (existing && parsedTimestamp(sample.captured_at) <= parsedTimestamp(existing.captured_at)) continue;
    retained.set(id, sample);
  }
  for (const sample of retained.values()) {
    const key = liveChannelKey(sample);
    const list = byChannel.get(key);
    if (!list) {
      byChannel.set(key, [sample]);
      continue;
    }
    if (parsedTimestamp(sample.captured_at) < parsedTimestamp(list.at(-1)!.captured_at)) unsorted.add(key);
    list.push(sample);
  }
  for (const key of unsorted) {
    byChannel
      .get(key)!
      .sort((left, right) => parsedTimestamp(left.captured_at) - parsedTimestamp(right.captured_at));
  }

  const pending = options.pendingBreakChannels ?? new Set<string>();
  const ordered = [...incoming].sort(
    (left, right) => parsedTimestamp(left.captured_at) - parsedTimestamp(right.captured_at),
  );
  for (const sample of ordered) {
    if (!inWindow(sample)) continue;
    const id = sourceEventId(sample.event_id);
    const capturedAt = parsedTimestamp(sample.captured_at);
    const existing = retained.get(id);
    let inheritedBreak = false;
    if (existing) {
      if (capturedAt <= parsedTimestamp(existing.captured_at)) continue;
      // A newer occurrence of a retained event replaces it and keeps its continuity marker.
      const existingList = byChannel.get(liveChannelKey(existing));
      const index = existingList?.indexOf(existing) ?? -1;
      if (existingList && index >= 0) existingList.splice(index, 1);
      retained.delete(id);
      inheritedBreak = isLiveHistorySegmentStart(existing);
    }
    const key = liveChannelKey(sample);
    if (!isRenderable(clearSegmentStart(sample))) {
      pending.add(key);
      continue;
    }
    const list = byChannel.get(key) ?? [];
    byChannel.set(key, list);
    const previous = list.at(-1);
    const previousAt = previous ? parsedTimestamp(previous.captured_at) : null;
    if (previousAt !== null && capturedAt <= previousAt) {
      // Late sample inside already covered history: keep it in time order, continuity unchanged.
      const stored = inheritedBreak ? markSegmentStart(clearSegmentStart(sample)) : clearSegmentStart(sample);
      const index = list.findIndex((item) => parsedTimestamp(item.captured_at) > capturedAt);
      list.splice(index < 0 ? list.length : index, 0, stored);
      retained.set(id, stored);
      continue;
    }
    const toleranceMs = options.sourceGapMsFor?.(key) ?? LIVE_HISTORY_FALLBACK_SOURCE_GAP_MS;
    const startsSegment =
      inheritedBreak ||
      isLiveHistorySegmentStart(sample) ||
      pending.has(key) ||
      (previousAt !== null && capturedAt - previousAt > toleranceMs);
    const stored = startsSegment ? markSegmentStart(clearSegmentStart(sample)) : clearSegmentStart(sample);
    list.push(stored);
    retained.set(id, stored);
    pending.delete(key);
  }

  const hysteresis = Math.max(
    LIVE_TAIL_REDUCTION_HYSTERESIS_MINIMUM,
    Math.ceil(maximumPointsPerChannel * LIVE_TAIL_REDUCTION_HYSTERESIS_RATIO),
  );
  return [...byChannel.entries()]
    .sort(([left], [right]) => left.localeCompare(right, "uk-UA"))
    .flatMap(([, channelSamples]) =>
      channelSamples.length > maximumPointsPerChannel + hysteresis
        ? reduceAnnotatedChannel(channelSamples, window, maximumPointsPerChannel)
        : channelSamples,
    );
}

export function mergeLiveHistoryTail(
  current: readonly TelemetrySample[],
  incoming: readonly TelemetrySample[],
  selectedKeys: ReadonlySet<string>,
  window: LiveHistoryWindow,
  maximumPointsPerChannel = LIVE_HISTORY_MAX_POINTS_PER_CHANNEL,
  sourceGapMsFor?: LiveSourceGapLookup,
): TelemetrySample[] {
  const selected = (sample: TelemetrySample) => selectedKeys.has(liveChannelKey(sample));
  return appendLiveHistoryTail(
    current.filter(selected),
    incoming.filter(selected),
    window,
    maximumPointsPerChannel,
    { sourceGapMsFor },
  );
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
