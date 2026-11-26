import { digitalLanesForMetric } from "@/features/charts/digital-channels";
import type { IntervalStatistics } from "@/features/charts/interval-statistics";
import { fetchAggregatedSeries, wireToIntervalStatistics } from "@/features/live/live-aggregate-history";
import type { HistorySeriesKey } from "@/lib/telemetry/history-aggregate";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

import { isOperatorEmbracoTemperature } from "./embraco-series";
import { dashboardItemIdentity } from "./model";
import type { LiveDashboardItem } from "./types";

/**
 * Saved Dashboard items that may use the aggregated history API (P0 charts). Operator-derived
 * Embraco temperatures are converted in the browser from raw counts, and digital state lanes need
 * every raw state change, so both keep the raw history path.
 */
export function aggregateEligible(item: LiveDashboardItem): boolean {
  return !isOperatorEmbracoTemperature(item) && digitalLanesForMetric(item.metric).length === 0;
}

function seriesQuery(item: LiveDashboardItem) {
  return {
    channel_id: item.channel_id,
    metric: item.metric,
    ...(item.channel_ref_id === null
      ? { node_id: item.node_id ?? "", equipment_id: item.equipment_id ?? "" }
      : {}),
  };
}

/**
 * The real series identity (node, equipment, channel, metric, unit) of each item, from its newest
 * persisted sample: catalogue-bound items do not carry node/equipment. Items without any sample
 * are left out (they keep the raw path).
 */
export async function resolveDashboardIdentities(
  adapter: TelemetryAdapter,
  items: readonly LiveDashboardItem[],
  signal: AbortSignal,
): Promise<Map<string, TelemetrySample>> {
  const resolved = await Promise.all(
    items.map(async (item) => {
      const response = await adapter.latest({ ...seriesQuery(item), limit: 1, offset: 0 }, signal);
      const sample = response.items.find(
        (candidate) =>
          candidate.channel_id === item.channel_id &&
          candidate.metric === item.metric &&
          (item.channel_ref_id !== null ||
            (candidate.node_id === item.node_id && candidate.equipment_id === item.equipment_id)),
      );
      return sample ? ([dashboardItemIdentity(item), sample] as const) : null;
    }),
  );
  return new Map(resolved.filter((entry): entry is readonly [string, TelemetrySample] => entry !== null));
}

export function seriesKeyOf(identity: TelemetrySample): HistorySeriesKey {
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

/** A sliding live window may reuse statistics this much older before it is refreshed. */
export const SERVER_STATISTICS_REUSE_MS = 30_000;
const SERVER_STATISTICS_BATCH_MS = 400;
const SERVER_STATISTICS_RETRY_MS = 10_000;
const SERVER_STATISTICS_LIMIT = 400;

/**
 * Exact statistics of aggregated Saved Dashboard series from the server (original rows, P0 charts).
 *
 * - Exact ranges are answered from the cache; a sliding window of the same length up to 30 s older
 *   is reused (its statistics state their own range) and refreshed after 15 s, so the numbers
 *   never disappear while the window moves.
 * - Requests are batched (400 ms, never postponed), one at a time, superseded ones aborted.
 * - A failed range is retried after 10 s; until then the row shows no statistics, never a guess.
 */
export class DashboardServerStatistics {
  private adapter: TelemetryAdapter | null = null;
  private identities = new Map<string, TelemetrySample>();
  private readonly exact = new Map<string, IntervalStatistics>();
  private fetched: Array<{ fromMs: number; toMs: number; at: number }> = [];
  private readonly failedAt = new Map<string, number>();
  private pending: [number, number] | null = null;
  private inFlight: [number, number] | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private controller: AbortController | null = null;

  constructor(
    private readonly onChange: () => void,
    private readonly now: () => number = () => Date.now(),
  ) {}

  /** New aggregated series, seeded with the exact statistics of the loaded window. */
  reset(
    adapter: TelemetryAdapter | null,
    identities: ReadonlyMap<string, TelemetrySample>,
    windowStatistics: ReadonlyMap<string, IntervalStatistics> = new Map(),
    window?: { fromMs: number; toMs: number },
  ): void {
    this.dispose();
    this.adapter = adapter;
    this.identities = new Map(identities);
    this.exact.clear();
    this.fetched = [];
    this.failedAt.clear();
    if (window && windowStatistics.size > 0) {
      for (const [item, statistics] of windowStatistics)
        this.exact.set(this.key(item, window.fromMs, window.toMs), statistics);
      this.fetched.push({ ...window, at: this.now() });
    }
  }

  has(itemIdentity: string): boolean {
    return this.identities.has(itemIdentity);
  }

  /**
   * The one range every statistics row of a request uses, so a table never mixes intervals: the
   * requested range when its server statistics exist (or there are no aggregated series), else
   * the newest compatible fetched range (same length, at most 30 s older) while a fresh one loads.
   */
  effectiveRange(fromMs: number, toMs: number): [number, number] {
    if (this.identities.size === 0) return [fromMs, toMs];
    const fetchedExact = this.fetched.some((range) => range.fromMs === fromMs && range.toMs === toMs);
    if (fetchedExact) return [fromMs, toMs];
    const reusable = [...this.fetched]
      .reverse()
      .find((range) => this.compatible([range.fromMs, range.toMs], [fromMs, toMs]));
    if (reusable) {
      // Refreshed halfway through the reuse period, so a moving window never runs out of numbers.
      if (this.now() - reusable.at > SERVER_STATISTICS_REUSE_MS / 2) this.schedule(fromMs, toMs);
      return [reusable.fromMs, reusable.toMs];
    }
    this.schedule(fromMs, toMs);
    return [fromMs, toMs];
  }

  /** Exact server statistics of an aggregated series for a range from `effectiveRange`. */
  exactFor(itemIdentity: string, fromMs: number, toMs: number): IntervalStatistics | null {
    return this.exact.get(this.key(itemIdentity, fromMs, toMs)) ?? null;
  }

  get(itemIdentity: string, fromMs: number, toMs: number): IntervalStatistics | null {
    const [effectiveFrom, effectiveTo] = this.effectiveRange(fromMs, toMs);
    return this.exactFor(itemIdentity, effectiveFrom, effectiveTo);
  }

  private compatible(left: [number, number], right: [number, number]): boolean {
    return (
      left[1] - left[0] === right[1] - right[0] && Math.abs(left[0] - right[0]) <= SERVER_STATISTICS_REUSE_MS
    );
  }

  dispose(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    this.pending = null;
    this.inFlight = null;
    this.controller?.abort();
    this.controller = null;
  }

  private key(itemIdentity: string, fromMs: number, toMs: number): string {
    return `${itemIdentity}|${fromMs}|${toMs}`;
  }

  private schedule(fromMs: number, toMs: number): void {
    if (!this.adapter || this.identities.size === 0) return;
    const failed = this.failedAt.get(`${fromMs}|${toMs}`);
    if (failed !== undefined && this.now() - failed < SERVER_STATISTICS_RETRY_MS) return;
    // A compatible request already in flight answers this one; repeated reads never cancel it.
    if (this.inFlight && this.compatible(this.inFlight, [fromMs, toMs])) return;
    this.pending = [fromMs, toMs];
    if (this.timer !== null) return;
    this.timer = setTimeout(() => void this.flush(), SERVER_STATISTICS_BATCH_MS);
  }

  private async flush(): Promise<void> {
    this.timer = null;
    const range = this.pending;
    this.pending = null;
    const adapter = this.adapter;
    if (!range || !adapter || !(range[1] > range[0])) return;
    const [fromMs, toMs] = range;
    if (this.inFlight && this.compatible(this.inFlight, range)) return;
    // Only a genuinely different range (a new zoom) supersedes the request in flight.
    this.controller?.abort();
    const controller = new AbortController();
    this.controller = controller;
    this.inFlight = range;
    const identities = [...this.identities];
    try {
      const response = await fetchAggregatedSeries(
        adapter,
        identities.map(([, identity]) => seriesKeyOf(identity)),
        { from: new Date(fromMs), to: new Date(toMs) },
        1,
        { signal: controller.signal, statistics: true },
      );
      if (controller.signal.aborted) return;
      for (const [item, identity] of identities) {
        const series = response.series.find((candidate) => sameSeries(candidate, seriesKeyOf(identity)));
        if (series?.statistics) {
          this.exact.set(
            this.key(item, fromMs, toMs),
            wireToIntervalStatistics(series.statistics, fromMs, toMs),
          );
        }
      }
      this.fetched.push({ fromMs, toMs, at: this.now() });
      if (this.fetched.length > 20) this.fetched.splice(0, this.fetched.length - 20);
      if (this.exact.size > SERVER_STATISTICS_LIMIT) {
        const keep = new Set(
          this.fetched.flatMap((entry) =>
            identities.map(([item]) => this.key(item, entry.fromMs, entry.toMs)),
          ),
        );
        for (const key of [...this.exact.keys()]) if (!keep.has(key)) this.exact.delete(key);
      }
      this.onChange();
    } catch {
      if (controller.signal.aborted) return;
      this.failedAt.set(`${fromMs}|${toMs}`, this.now());
    } finally {
      if (this.controller === controller) {
        this.controller = null;
        this.inFlight = null;
      }
    }
  }
}
