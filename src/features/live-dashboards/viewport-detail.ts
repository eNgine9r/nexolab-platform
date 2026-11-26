import {
  computeIntervalStatistics,
  type IntervalSampleColumns,
  type IntervalStatistics,
} from "@/features/charts/interval-statistics";
import {
  columnsViewportDetail,
  mergeViewportDetail,
  type ViewportDetail,
} from "@/features/live/live-aggregate-history";
import { liveChannelKey } from "@/features/live/live-telemetry";
import type { TelemetrySample } from "@/lib/telemetry/types";

export interface SavedDashboardDetailSource {
  /** Dashboard item identity (the key of the raw display columns). */
  key: string;
  /** Any sample of the series; gives the channel identity of the detail points. */
  identity: TelemetrySample;
  /** Raw columns holding the operator-visible display value of every original measurement. */
  columns: IntervalSampleColumns;
  /** Raw continuity tolerance of the series (undefined: fallback tolerance). */
  sourceGapMs: number | undefined;
}

/**
 * #1821: viewport detail of every Saved Dashboard series from the browser's raw display columns —
 * the original measurements of the visible range (±50 % margin), reduced only above the budget
 * with first/min/max/last per bucket and breaks at invalid samples and silent gaps. No request.
 *
 * Columns hold display values (operator-derived Embraco °C included), so detail points are
 * plotted as they are and never converted a second time.
 */
export function savedDashboardViewportDetail(
  sources: readonly SavedDashboardDetailSource[],
  domain: { fromMs: number; toMs: number },
  maximumPointsPerSeries: number,
  nowMs = Date.now(),
): Record<string, ViewportDetail> {
  const detail: Record<string, ViewportDetail> = {};
  for (const source of sources) {
    const channelKey = liveChannelKey(source.identity);
    const result = columnsViewportDetail(
      [source.identity],
      { [channelKey]: source.columns },
      domain,
      maximumPointsPerSeries,
      () => source.sourceGapMs,
      nowMs,
    );
    if (result.channels.size > 0 && result.samples.length > 0) detail[source.key] = result;
  }
  return detail;
}

/** Display history of one series with its viewport detail merged (live points after it stay). */
export function mergeSavedDashboardDetail(
  history: readonly TelemetrySample[],
  detail: ViewportDetail | undefined,
): TelemetrySample[] {
  return detail ? [...mergeViewportDetail(history, detail)] : [...history];
}

function columnsVersion(columns: IntervalSampleColumns): string {
  // Columns only grow (duplicates are ignored) or are pruned from the front, so the lengths and
  // both ends identify their content.
  const stamps = columns.validTimestamps;
  return `${stamps.length}:${columns.invalidTimestamps.length}:${stamps[0] ?? ""}:${stamps.at(-1) ?? ""}:${
    columns.invalidTimestamps.at(-1) ?? ""
  }`;
}

const STATISTICS_CACHE_LIMIT = 1_000;

/**
 * Exact interval statistics from raw columns, cached per series, range and column version: every
 * zoom, flush and statistics row asks again, and a 24-series day sorts ~200 000 spacings.
 */
export function cachedIntervalStatistics(
  cache: Map<string, IntervalStatistics | null>,
  key: string,
  columns: IntervalSampleColumns | undefined,
  fromMs: number,
  toMs: number,
): IntervalStatistics | null {
  if (!columns) return null;
  const cacheKey = `${key}|${fromMs}|${toMs}|${columnsVersion(columns)}`;
  const cached = cache.get(cacheKey);
  if (cached !== undefined) return cached;
  const computed = computeIntervalStatistics(columns, fromMs, toMs);
  if (cache.size >= STATISTICS_CACHE_LIMIT) cache.clear();
  cache.set(cacheKey, computed);
  return computed;
}
