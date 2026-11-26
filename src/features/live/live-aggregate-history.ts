import type { IntervalStatistics } from "@/features/charts/interval-statistics";
import {
  INTERVAL_MINIMUM_AVERAGE_COVERAGE,
  INTERVAL_MINIMUM_AVERAGE_SAMPLES,
} from "@/features/charts/interval-statistics";
import { CADENCE_OBSERVATION_LIMIT } from "@/features/live/freshness";
import {
  LIVE_HISTORY_FALLBACK_SOURCE_GAP_MS,
  LIVE_HISTORY_MIN_SOURCE_GAP_MS,
  deriveLiveSourceGapMsByChannel,
  downsampleLiveHistory,
  groupByChannelKey,
  isLiveHistorySegmentStart,
  markSegmentStart,
  newestRawSamplesPerChannel,
  sortByCapturedAt,
  type LiveHistoryResult,
  type LiveHistoryWindow,
} from "@/features/live/live-history";
import { recordLiveIntervalSamples, type LiveIntervalColumns } from "@/features/live/live-interval-columns";
import { liveChannelKey } from "@/features/live/live-telemetry";
import { HISTORY_PAGE_RETRY_DELAYS_MS, isRetryableHistoryError } from "@/lib/telemetry/history";
import {
  AGGREGATE_SERIES_PER_REQUEST,
  type HistoryAggregateResponse,
  type HistoryAggregateSeries,
  type HistoryIntervalStatisticsWire,
  type HistorySeriesKey,
} from "@/lib/telemetry/history-aggregate";
import type { TelemetryAdapter, TelemetryQuality, TelemetrySample } from "@/lib/telemetry/types";

/** #1813: points drawn per aggregated bucket (first, minimum, maximum, last). */
export const POINTS_PER_BUCKET = 4;
/** Zoom detail covers the viewport plus this share of its width on each side, for smooth panning. */
export const DETAIL_MARGIN_RATIO = 0.5;

export interface AggregatedLiveHistoryResult extends LiveHistoryResult {
  /** Channels whose display came from server buckets (no raw columns in the browser). */
  aggregatedChannels: Set<string>;
  /** Exact statistics of the loaded window for aggregated channels (from original rows). */
  windowStatistics: Map<string, IntervalStatistics>;
}

export interface ViewportDetail {
  fromMs: number;
  toMs: number;
  /** Detail replaces display points of these channels within [fromMs, coveredToMs]. */
  coveredToMs: number;
  channels: Set<string>;
  samples: TelemetrySample[];
}

const QUALITIES = new Set<TelemetryQuality>(["valid", "sensor_error", "communication_error", "unknown"]);

function keyOf(
  identity: Pick<TelemetrySample, "node_id" | "equipment_id" | "channel_id" | "metric">,
): HistorySeriesKey {
  return {
    node_id: identity.node_id,
    equipment_id: identity.equipment_id,
    channel_id: identity.channel_id,
    metric: identity.metric,
  };
}

function sameSeries(left: HistorySeriesKey, right: HistorySeriesKey): boolean {
  return (
    left.node_id === right.node_id &&
    left.equipment_id === right.equipment_id &&
    left.channel_id === right.channel_id &&
    left.metric === right.metric
  );
}

function sampleFrom(
  identity: TelemetrySample,
  eventId: string,
  timestampMs: number,
  value: number | null,
  quality: TelemetryQuality,
  alarm: TelemetrySample["alarm"] = null,
): TelemetrySample {
  return {
    event_id: eventId,
    node_id: identity.node_id,
    equipment_id: identity.equipment_id,
    channel_id: identity.channel_id,
    metric: identity.metric,
    unit: identity.unit,
    source: identity.source,
    captured_at: new Date(timestampMs).toISOString(),
    value,
    quality,
    alarm,
    raw_value: null,
    raw_status: null,
  };
}

function rawSamples(identity: TelemetrySample, series: HistoryAggregateSeries): TelemetrySample[] {
  return series.raw.map(([timestampMs, value, quality, alarm, eventId]) =>
    sampleFrom(
      identity,
      eventId,
      timestampMs,
      value,
      QUALITIES.has(quality as TelemetryQuality) ? (quality as TelemetryQuality) : "unknown",
      alarm === "low" || alarm === "high" ? alarm : null,
    ),
  );
}

/**
 * Display points of an aggregated series: each bucket's real first, minimum, maximum and last
 * measurements in time order (M4), nothing interpolated. A line breaks where an invalid sample
 * lies between two points, or where two consecutive points are further apart than both two bucket
 * widths and the source tolerance (a missing bucket of silence).
 */
export function aggregateSeriesToSamples(
  identity: TelemetrySample,
  series: HistoryAggregateSeries,
  bucketMs: number,
  sourceGapMs = LIVE_HISTORY_FALLBACK_SOURCE_GAP_MS,
): TelemetrySample[] {
  const breakAfterMs = Math.max(2 * bucketMs, sourceGapMs);
  const invalidSpans = series.buckets
    .filter((bucket) => bucket.firstInvalidMs !== null && bucket.lastInvalidMs !== null)
    .map((bucket) => [bucket.firstInvalidMs!, bucket.lastInvalidMs!] as const);
  const key = liveChannelKey(identity);
  // [time, value, bucket index]
  const points: Array<[number, number, number]> = [];
  for (const bucket of series.buckets) {
    const seen = new Set<string>();
    const candidates = [bucket.first, bucket.minimum, bucket.maximum, bucket.last]
      .filter((point): point is [number, number] => point !== null)
      .sort((left, right) => left[0] - right[0] || left[1] - right[1]);
    for (const point of candidates) {
      const id = `${point[0]}:${point[1]}`;
      if (seen.has(id)) continue;
      seen.add(id);
      points.push([point[0], point[1], bucket.index]);
    }
  }
  const result: TelemetrySample[] = [];
  let previous: [number, number, number] | null = null;
  for (const point of points) {
    const sample = sampleFrom(
      identity,
      `agg:${key}:${point[0]}:${result.length}`,
      point[0],
      point[1],
      "valid",
    );
    const invalidBetween =
      previous !== null && invalidSpans.some(([from, to]) => to > previous![0] && from < point[0]);
    // An empty bucket between two points is a span without any sample: an outage once the points
    // are further apart than the source tolerance (as the raw path decides).
    const skippedBucket =
      previous !== null && point[2] > previous[2] + 1 && point[0] - previous[0] > sourceGapMs;
    const silent = previous !== null && (skippedBucket || point[0] - previous[0] > breakAfterMs);
    result.push(invalidBetween || silent ? markSegmentStart(sample) : sample);
    previous = point;
  }
  return result;
}

/** Same semantics as computeIntervalStatistics() over raw columns (interval-statistics.ts). */
export function wireToIntervalStatistics(
  wire: HistoryIntervalStatisticsWire,
  fromMs: number,
  toMs: number,
): IntervalStatistics {
  const base = { fromMs, toMs, invalidCount: wire.invalid_count, basis: "raw_persisted" as const };
  if (wire.valid_count === 0) {
    return {
      ...base,
      min: null,
      max: null,
      average: null,
      averageStatus: "no_data",
      validCount: 0,
      firstTimestampMs: null,
      lastTimestampMs: null,
      cadenceMs: null,
      expectedCount: null,
      coverageRatio: null,
      coverageStatus: "no_data",
      gaps: { count: 0, totalMs: 0, longestMs: 0 },
    };
  }
  const cadenceMs = wire.median_spacing_ms;
  const expectedCount = cadenceMs === null ? null : Math.max(1, Math.floor((toMs - fromMs) / cadenceMs) + 1);
  const coverageRatio = expectedCount === null ? null : Math.min(1, wire.valid_count / expectedCount);
  const sufficient =
    coverageRatio !== null &&
    coverageRatio >= INTERVAL_MINIMUM_AVERAGE_COVERAGE &&
    wire.valid_count >= INTERVAL_MINIMUM_AVERAGE_SAMPLES;
  return {
    ...base,
    min: wire.minimum,
    max: wire.maximum,
    average: sufficient ? wire.valid_sum / wire.valid_count : null,
    averageStatus: sufficient ? "available" : "insufficient_coverage",
    validCount: wire.valid_count,
    firstTimestampMs: wire.first_valid_ms,
    lastTimestampMs: wire.last_valid_ms,
    cadenceMs,
    expectedCount,
    coverageRatio,
    coverageStatus: sufficient ? "sufficient" : "insufficient",
    gaps: { count: wire.gap_count, totalMs: wire.gap_total_ms, longestMs: wire.gap_longest_ms },
  };
}

function abortError(): Error {
  return new DOMException("Aggregated history load was aborted", "AbortError");
}

async function fetchGroup(
  adapter: TelemetryAdapter,
  series: readonly HistorySeriesKey[],
  window: LiveHistoryWindow,
  buckets: number,
  options: { signal?: AbortSignal; snapshotAt?: string; statistics?: boolean },
): Promise<HistoryAggregateResponse> {
  if (!adapter.historyAggregate) throw new Error("Aggregated history is not supported by this adapter");
  const delays = HISTORY_PAGE_RETRY_DELAYS_MS;
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await adapter.historyAggregate(
        {
          from: window.from,
          to: window.to,
          series,
          buckets,
          snapshot_at: options.snapshotAt,
          statistics: options.statistics,
        },
        options.signal,
      );
    } catch (error) {
      if (options.signal?.aborted || attempt >= delays.length || !isRetryableHistoryError(error)) throw error;
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(resolve, delays[attempt]);
        options.signal?.addEventListener(
          "abort",
          () => {
            clearTimeout(timer);
            reject(abortError());
          },
          { once: true },
        );
      });
    }
  }
}

/**
 * Aggregated history for several series: groups of at most four series per request (bounded by
 * the shared history limiter), all under the snapshot fixed by the first group. The first failure
 * aborts the other groups.
 */
export async function fetchAggregatedSeries(
  adapter: TelemetryAdapter,
  keys: readonly HistorySeriesKey[],
  window: LiveHistoryWindow,
  buckets: number,
  options: { signal?: AbortSignal; statistics?: boolean } = {},
): Promise<{ snapshotAt: string; bucketMs: number; series: HistoryAggregateSeries[] }> {
  const groups: HistorySeriesKey[][] = [];
  for (let index = 0; index < keys.length; index += AGGREGATE_SERIES_PER_REQUEST) {
    groups.push(keys.slice(index, index + AGGREGATE_SERIES_PER_REQUEST));
  }
  const linked = new AbortController();
  const forward = () => linked.abort();
  if (options.signal?.aborted) linked.abort();
  else options.signal?.addEventListener("abort", forward, { once: true });
  try {
    const guard = <T>(promise: Promise<T>) =>
      promise.catch((error: unknown) => {
        linked.abort();
        throw error;
      });
    const first = await guard(
      fetchGroup(adapter, groups[0], window, buckets, {
        signal: linked.signal,
        statistics: options.statistics,
      }),
    );
    const rest = await Promise.all(
      groups.slice(1).map((group) =>
        guard(
          fetchGroup(adapter, group, window, buckets, {
            signal: linked.signal,
            snapshotAt: first.snapshotAt,
            statistics: options.statistics,
          }),
        ),
      ),
    );
    return {
      snapshotAt: first.snapshotAt,
      bucketMs: first.bucketMs,
      series: [first, ...rest].flatMap((response) => response.series),
    };
  } finally {
    options.signal?.removeEventListener("abort", forward);
  }
}

/** Live Data history through the aggregate endpoint (#1813). Raw-mode series keep the raw pipeline. */
export async function loadAggregatedLiveHistory(
  adapter: TelemetryAdapter,
  identities: readonly TelemetrySample[],
  window: LiveHistoryWindow,
  signal: AbortSignal | undefined,
  maximumPointsPerChannel: number,
  sourceGapMsFor: (channelKey: string) => number | undefined = () => undefined,
): Promise<AggregatedLiveHistoryResult> {
  const buckets = Math.max(1, Math.ceil(maximumPointsPerChannel / POINTS_PER_BUCKET));
  const response = await fetchAggregatedSeries(adapter, identities.map(keyOf), window, buckets, {
    signal,
    statistics: true,
  });
  const intervalColumns: LiveIntervalColumns = {};
  const sourceGapMsByChannel = new Map<string, number>();
  const aggregatedChannels = new Set<string>();
  const windowStatistics = new Map<string, IntervalStatistics>();
  let samples: TelemetrySample[] = [];
  let cadenceSamples: TelemetrySample[] = [];
  for (const identity of identities) {
    const series = response.series.find((item) => sameSeries(item, keyOf(identity)));
    if (!series) continue;
    const key = liveChannelKey(identity);
    if (series.mode === "raw") {
      const raw = rawSamples(identity, series);
      recordLiveIntervalSamples(intervalColumns, raw);
      for (const [channel, gapMs] of deriveLiveSourceGapMsByChannel(raw))
        sourceGapMsByChannel.set(channel, gapMs);
      samples = samples.concat(downsampleLiveHistory(raw, window, maximumPointsPerChannel));
      cadenceSamples = cadenceSamples.concat(newestRawSamplesPerChannel(raw, CADENCE_OBSERVATION_LIMIT));
    } else {
      aggregatedChannels.add(key);
      // Same continuity tolerance and cadence as the raw path, from the server's exact median
      // spacing and its newest real sample times (no raw history needed in the browser).
      const median = series.statistics?.median_spacing_ms ?? null;
      const tolerance =
        median !== null ? Math.max(LIVE_HISTORY_MIN_SOURCE_GAP_MS, median * 3) : sourceGapMsFor(key);
      if (median !== null && tolerance !== undefined) sourceGapMsByChannel.set(key, tolerance);
      cadenceSamples = cadenceSamples.concat(
        (series.statistics?.recent_valid_ms ?? []).map((timestampMs) =>
          sampleFrom(identity, `cadence:${key}:${timestampMs}`, timestampMs, null, "unknown"),
        ),
      );
      if (series.statistics) {
        windowStatistics.set(
          key,
          wireToIntervalStatistics(series.statistics, window.from.getTime(), window.to.getTime()),
        );
      }
      samples = samples.concat(aggregateSeriesToSamples(identity, series, response.bucketMs, tolerance));
    }
  }
  return {
    samples: groupByChannelKey(samples),
    snapshotAt: response.snapshotAt,
    cadenceSamples,
    intervalColumns,
    sourceGapMsByChannel,
    aggregatedChannels,
    windowStatistics,
  };
}

function lowerBound(values: readonly number[], target: number): number {
  let low = 0;
  let high = values.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (values[middle] < target) low = middle + 1;
    else high = middle;
  }
  return low;
}

/**
 * Viewport detail from the browser's raw columns (raw path, current backends): every original
 * measurement in the visible range plus margin, reduced only if it exceeds the point budget, with
 * breaks at invalid samples and silent gaps. No request is made.
 */
export function columnsViewportDetail(
  identities: readonly TelemetrySample[],
  columns: LiveIntervalColumns,
  domain: { fromMs: number; toMs: number },
  maximumPointsPerChannel: number,
  sourceGapMsFor: (channelKey: string) => number | undefined,
  nowMs = Date.now(),
): ViewportDetail {
  const span = domain.toMs - domain.fromMs;
  const fromMs = domain.fromMs - span * DETAIL_MARGIN_RATIO;
  const toMs = domain.toMs + span * DETAIL_MARGIN_RATIO;
  const channels = new Set<string>();
  const samples: TelemetrySample[] = [];
  let coveredToMs = fromMs;
  for (const identity of identities) {
    const key = liveChannelKey(identity);
    const store = columns[key];
    if (!store) continue;
    channels.add(key);
    const tolerance = sourceGapMsFor(key) ?? LIVE_HISTORY_FALLBACK_SOURCE_GAP_MS;
    const stamps = store.validTimestamps;
    const values = store.validValues;
    const invalid = store.invalidTimestamps;
    const start = lowerBound(stamps, fromMs);
    const end = lowerBound(stamps, toMs + 1);
    if (end <= start) continue;
    // A break precedes index i when an invalid sample or a silent gap lies between i-1 and i.
    const breakBefore = new Uint8Array(end - start);
    // From the first in-range sample: its preceding raw sample may lie before the detail range,
    // and a break there must survive the merge with the coarse points outside it.
    for (let index = Math.max(start, 1); index < end; index += 1) {
      const silent = stamps[index] - stamps[index - 1] > tolerance;
      const invalidBetween = lowerBound(invalid, stamps[index - 1] + 1) < lowerBound(invalid, stamps[index]);
      if (silent || invalidBetween) breakBefore[index - start] = 1;
    }
    let indices: number[];
    if (end - start <= maximumPointsPerChannel) {
      indices = Array.from({ length: end - start }, (_, offset) => start + offset);
    } else {
      // #1813: reduce on the numeric columns (first, min, max, last per bucket plus both sides of
      // every break) so only display points become objects; materializing every raw sample of a
      // wide viewport made each zoom commit a long task.
      const bucketCount = Math.max(1, Math.floor(maximumPointsPerChannel / 4));
      const firstMs = stamps[start];
      const widthMs = Math.max(1, (stamps[end - 1] - firstMs + 1) / bucketCount);
      const keep = new Set<number>();
      let bucket = -1;
      let minIndex = start;
      let maxIndex = start;
      let lastIndex = start;
      const flush = () => {
        if (bucket < 0) return;
        keep.add(minIndex);
        keep.add(maxIndex);
        keep.add(lastIndex);
      };
      for (let index = start; index < end; index += 1) {
        const current = Math.min(bucketCount - 1, Math.floor((stamps[index] - firstMs) / widthMs));
        if (current !== bucket) {
          flush();
          bucket = current;
          keep.add(index);
          minIndex = index;
          maxIndex = index;
        } else {
          if (values[index] < values[minIndex]) minIndex = index;
          if (values[index] > values[maxIndex]) maxIndex = index;
        }
        lastIndex = index;
        if (breakBefore[index - start] === 1) {
          keep.add(index - 1);
          keep.add(index);
        }
      }
      flush();
      indices = [...keep].sort((left, right) => left - right);
    }
    for (const index of indices) {
      const sample = sampleFrom(
        identity,
        `raw:${key}:${stamps[index]}`,
        stamps[index],
        values[index],
        "valid",
      );
      samples.push(breakBefore[index - start] === 1 ? markSegmentStart(sample) : sample);
    }
    coveredToMs = Math.max(coveredToMs, stamps[end - 1]);
  }
  return { fromMs, toMs, coveredToMs: Math.min(Math.max(coveredToMs, fromMs), nowMs), channels, samples };
}

/** Viewport detail through the aggregate endpoint (aggregated channels). Cancellable. */
export async function aggregateViewportDetail(
  adapter: TelemetryAdapter,
  identities: readonly TelemetrySample[],
  domain: { fromMs: number; toMs: number },
  maximumPointsPerChannel: number,
  sourceGapMsFor: (channelKey: string) => number | undefined,
  signal: AbortSignal,
  nowMs = Date.now(),
  /** The loaded history window: the margin never extends the request beyond it (review). */
  bounds?: { fromMs: number; toMs: number },
): Promise<ViewportDetail> {
  const span = domain.toMs - domain.fromMs;
  // A wide zoom plus its margin could exceed the longest range the aggregate API serves (31 d,
  // HTTP 422); the request stays inside the loaded window, which the API already accepted.
  const fromMs = Math.max(
    domain.fromMs - span * DETAIL_MARGIN_RATIO,
    bounds?.fromMs ?? Number.NEGATIVE_INFINITY,
  );
  const toMs = Math.min(
    domain.toMs + span * DETAIL_MARGIN_RATIO,
    nowMs,
    bounds?.toMs ?? Number.POSITIVE_INFINITY,
  );
  const window = { from: new Date(fromMs), to: new Date(Math.max(toMs, fromMs + 1)) };
  const buckets = Math.max(1, Math.ceil(maximumPointsPerChannel / POINTS_PER_BUCKET));
  const response = await fetchAggregatedSeries(adapter, identities.map(keyOf), window, buckets, { signal });
  const channels = new Set<string>();
  let samples: TelemetrySample[] = [];
  for (const identity of identities) {
    const series = response.series.find((item) => sameSeries(item, keyOf(identity)));
    if (!series) continue;
    const key = liveChannelKey(identity);
    channels.add(key);
    const points =
      series.mode === "raw"
        ? downsampleLiveHistory(rawSamples(identity, series), window, maximumPointsPerChannel)
        : aggregateSeriesToSamples(identity, series, response.bucketMs, sourceGapMsFor(key) ?? undefined);
    samples = samples.concat(points);
  }
  return { fromMs, toMs: window.to.getTime(), coveredToMs: window.to.getTime(), channels, samples };
}

/**
 * Replaces each detailed channel's display points inside [detail.fromMs, detail.coveredToMs] by
 * the detail points. Live points newer than the detail stay, so new measurements keep appearing.
 */
export function mergeViewportDetail(
  history: readonly TelemetrySample[],
  detail: ViewportDetail | null,
): readonly TelemetrySample[] {
  if (!detail || detail.channels.size === 0) return history;
  // Per channel: keys and timestamps computed once; no global comparator sort (#1813 perf).
  const byChannel = new Map<string, TelemetrySample[]>();
  // First replaced coarse point per channel: a break it carried lies between the last coarse point
  // before the detail and itself, so it must survive when the detail does not show it.
  const firstReplaced = new Map<string, TelemetrySample>();
  for (const sample of history) {
    const key = liveChannelKey(sample);
    if (detail.channels.has(key)) {
      const timestampMs = Date.parse(sample.captured_at);
      if (timestampMs >= detail.fromMs && timestampMs <= detail.coveredToMs) {
        if (!firstReplaced.has(key)) firstReplaced.set(key, sample);
        continue;
      }
    }
    const list = byChannel.get(key);
    if (list) list.push(sample);
    else byChannel.set(key, [sample]);
  }
  const detailByChannel = new Map<string, TelemetrySample[]>();
  for (const sample of detail.samples) {
    const key = liveChannelKey(sample);
    const list = detailByChannel.get(key);
    if (list) list.push(sample);
    else detailByChannel.set(key, [sample]);
  }
  for (const [key, points] of detailByChannel) {
    const ordered = sortByCapturedAt(points);
    const replaced = firstReplaced.get(key);
    if (replaced && isLiveHistorySegmentStart(replaced) && ordered[0]) {
      const boundaryMs = Date.parse(replaced.captured_at);
      const shown = ordered.some(
        (point) => isLiveHistorySegmentStart(point) && Date.parse(point.captured_at) <= boundaryMs,
      );
      if (!shown) ordered[0] = markSegmentStart(ordered[0]);
    }
    const list = byChannel.get(key);
    if (list) list.push(...ordered);
    else byChannel.set(key, ordered);
  }
  return [...byChannel.keys()]
    .sort((left, right) => left.localeCompare(right, "uk-UA"))
    .flatMap((key) => {
      const list = byChannel.get(key)!;
      return detail.channels.has(key) ? sortByCapturedAt(list) : list;
    });
}
