import {
  computeIntervalStatistics,
  createIntervalSampleColumns,
  type IntervalSampleColumns,
  type IntervalStatistics,
} from "@/features/charts/interval-statistics";
import type { ChartSeriesIdentity } from "@/features/charts/domain";
import { columnsViewportDetail, type ViewportDetail } from "@/features/live/live-aggregate-history";
import { groupByChannelKey, LIVE_HISTORY_MIN_SOURCE_GAP_MS } from "@/features/live/live-history";
import { pruneLiveIntervalSamples, type LiveIntervalColumns } from "@/features/live/live-interval-columns";
import { liveChannelKey } from "@/features/live/live-telemetry";
import { isTemperatureProbeSample } from "@/lib/telemetry/temperature-channel";
import type { TelemetrySample } from "@/lib/telemetry/types";

/**
 * Overview temperature history held compactly (P0 charts, 7 d / 30 d): every RAW measurement as
 * numeric columns per series (exact statistics, viewport detail, continuity), one identity sample
 * and the newest raw sample per series (freshness). No raw sample objects are kept, so a week of
 * history costs ~16 bytes per measurement instead of ~345.
 */
export interface OverviewHistoryStore {
  columns: LiveIntervalColumns;
  identities: Map<string, TelemetrySample>;
  latest: Map<string, TelemetrySample>;
}

export function createOverviewHistoryStore(): OverviewHistoryStore {
  return { columns: {}, identities: new Map(), latest: new Map() };
}

function capturedMs(sample: TelemetrySample): number {
  return Date.parse(sample.captured_at);
}

/**
 * Merges ascending, unique `addTimestamps` (with `addValues` when given) into the ascending
 * `stamps`/`values` columns; an existing timestamp wins (as appendIntervalSample). Appending after
 * or prepending before the held range is a concat; overlaps take one linear merge — never a splice
 * per row (inserting older slices row by row was quadratic: ~36 s for 30 d at 10 s, review).
 */
function mergeSorted(
  stamps: number[],
  values: number[] | null,
  addTimestamps: number[],
  addValues: number[] | null,
): { stamps: number[]; values: number[] | null } {
  if (addTimestamps.length === 0) return { stamps, values };
  if (stamps.length === 0 || addTimestamps[0] > stamps[stamps.length - 1]) {
    return {
      stamps: stamps.concat(addTimestamps),
      values: values && addValues ? values.concat(addValues) : null,
    };
  }
  if (addTimestamps[addTimestamps.length - 1] < stamps[0]) {
    return {
      stamps: addTimestamps.concat(stamps),
      values: values && addValues ? addValues.concat(values) : null,
    };
  }
  const mergedStamps: number[] = [];
  const mergedValues: number[] | null = values && addValues ? [] : null;
  let left = 0;
  let right = 0;
  while (left < stamps.length || right < addTimestamps.length) {
    const takeLeft =
      right >= addTimestamps.length || (left < stamps.length && stamps[left] <= addTimestamps[right]);
    if (takeLeft) {
      if (right < addTimestamps.length && stamps[left] === addTimestamps[right]) right += 1;
      mergedStamps.push(stamps[left]);
      if (mergedValues && values) mergedValues.push(values[left]);
      left += 1;
    } else {
      mergedStamps.push(addTimestamps[right]);
      if (mergedValues && addValues) mergedValues.push(addValues[right]);
      right += 1;
    }
  }
  return { stamps: mergedStamps, values: mergedValues };
}

/** Records RAW temperature-probe samples (any order; duplicates by timestamp are ignored). */
export function recordOverviewSamples(
  store: OverviewHistoryStore,
  samples: readonly TelemetrySample[],
): void {
  const probes = samples.filter(isTemperatureProbeSample);
  // Per series: valid and non-valid polls, each sorted and unique, merged in one step.
  const batches = new Map<string, { valid: Array<[number, number]>; invalid: number[] }>();
  for (const sample of probes) {
    const timestampMs = capturedMs(sample);
    if (!Number.isFinite(timestampMs)) continue;
    const key = liveChannelKey(sample);
    let batch = batches.get(key);
    if (!batch) {
      batch = { valid: [], invalid: [] };
      batches.set(key, batch);
    }
    const valid = sample.quality === "valid" && sample.value !== null && Number.isFinite(sample.value);
    if (valid) batch.valid.push([timestampMs, sample.value as number]);
    else batch.invalid.push(timestampMs);
  }
  for (const [key, batch] of batches) {
    const columns = (store.columns[key] ??= createIntervalSampleColumns());
    batch.valid.sort((left, right) => left[0] - right[0]);
    const validStamps: number[] = [];
    const validValues: number[] = [];
    for (const [timestampMs, value] of batch.valid) {
      if (validStamps[validStamps.length - 1] === timestampMs) continue;
      validStamps.push(timestampMs);
      validValues.push(value);
    }
    const merged = mergeSorted(columns.validTimestamps, columns.validValues, validStamps, validValues);
    columns.validTimestamps = merged.stamps;
    columns.validValues = merged.values ?? [];
    const invalid = [...new Set(batch.invalid)].sort((left, right) => left - right);
    columns.invalidTimestamps = mergeSorted(columns.invalidTimestamps, null, invalid, null).stamps;
  }
  for (const sample of probes) {
    const key = liveChannelKey(sample);
    if (!store.identities.has(key)) store.identities.set(key, sample);
    const current = store.latest.get(key);
    if (!current || capturedMs(sample) > capturedMs(current)) store.latest.set(key, sample);
  }
}

export function pruneOverviewHistory(store: OverviewHistoryStore, fromMs: number): void {
  pruneLiveIntervalSamples(store.columns, fromMs);
}

/** Series key of a chart identity, equal to `liveChannelKey` of its samples. */
export function overviewColumnsKey(identity: ChartSeriesIdentity): string {
  return [identity.nodeId, identity.equipmentId, identity.channelId, identity.metric, identity.nativeUnit]
    .map((part) => encodeURIComponent(part))
    .join("|");
}

const CADENCE_SAMPLE_SPACINGS = 1_000;

/** Continuity tolerance from the RAW spacing: 3 × the median of the newest spacings, ≥ 30 s. */
export function overviewSourceGapMs(columns: IntervalSampleColumns | undefined): number | undefined {
  const stamps = columns?.validTimestamps;
  if (!stamps || stamps.length < 3) return undefined;
  const start = Math.max(1, stamps.length - CADENCE_SAMPLE_SPACINGS);
  const spacings: number[] = [];
  for (let index = start; index < stamps.length; index += 1) spacings.push(stamps[index] - stamps[index - 1]);
  spacings.sort((left, right) => left - right);
  const middle = Math.floor(spacings.length / 2);
  const median = spacings.length % 2 === 0 ? (spacings[middle - 1] + spacings[middle]) / 2 : spacings[middle];
  return Math.max(LIVE_HISTORY_MIN_SOURCE_GAP_MS, median * 3);
}

/** The newest `limit` distinct RAW timestamps (valid and non-valid polls), oldest first. */
export function overviewRecentTimestamps(
  columns: IntervalSampleColumns | undefined,
  limit: number,
): number[] {
  if (!columns) return [];
  const merged = [...columns.validTimestamps.slice(-limit), ...columns.invalidTimestamps.slice(-limit)].sort(
    (left, right) => left - right,
  );
  const distinct: number[] = [];
  for (const value of merged) if (distinct.at(-1) !== value) distinct.push(value);
  return distinct.slice(-limit);
}

/**
 * Extremum-preserving display points of every series for `domain` (first/min/max/last per bucket,
 * plus both sides of every break), with breaks at invalid polls and silent gaps decided on RAW
 * spacing. Nothing is interpolated.
 */
export function overviewViewportDetail(
  store: OverviewHistoryStore,
  domain: { fromMs: number; toMs: number },
  maximumPointsPerSeries: number,
  nowMs = Date.now(),
): ViewportDetail {
  return columnsViewportDetail(
    [...store.identities.values()],
    store.columns,
    domain,
    maximumPointsPerSeries,
    (key) => overviewSourceGapMs(store.columns[key]),
    nowMs,
  );
}

/** Continuity-annotated display history of the whole window, grouped by series. */
export function overviewDisplayHistory(
  store: OverviewHistoryStore,
  window: { from: Date; to: Date },
  maximumPointsPerSeries: number,
  nowMs = Date.now(),
): TelemetrySample[] {
  const fromMs = window.from.getTime();
  const toMs = window.to.getTime();
  // columnsViewportDetail adds a margin of half the span on both sides; the window bounds are
  // applied afterwards, so only points inside the window remain.
  const detail = overviewViewportDetail(store, { fromMs, toMs }, maximumPointsPerSeries, nowMs);
  return groupByChannelKey(
    detail.samples.filter((sample) => {
      const timestampMs = capturedMs(sample);
      return timestampMs >= fromMs && timestampMs <= toMs;
    }),
  );
}

const STATISTICS_CACHE_LIMIT = 500;

/** Exact statistics of one series from its RAW columns, cached per range and column content. */
export function overviewSeriesStatistics(
  store: OverviewHistoryStore,
  cache: Map<string, IntervalStatistics | null>,
  key: string,
  fromMs: number,
  toMs: number,
): IntervalStatistics | null {
  const columns = store.columns[key];
  if (!columns) return null;
  const stamps = columns.validTimestamps;
  const invalid = columns.invalidTimestamps;
  const cacheKey = `${key}|${fromMs}|${toMs}|${stamps.length}:${invalid.length}:${stamps[0] ?? ""}:${
    stamps.at(-1) ?? ""
  }:${invalid.at(-1) ?? ""}`;
  const cached = cache.get(cacheKey);
  if (cached !== undefined) return cached;
  const computed = computeIntervalStatistics(columns, fromMs, toMs);
  if (cache.size >= STATISTICS_CACHE_LIMIT) cache.clear();
  cache.set(cacheKey, computed);
  return computed;
}
