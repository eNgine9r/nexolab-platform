/**
 * Exact Energy interval statistics from authoritative RAW measurements (#1675, WP-N).
 *
 * Energy chart history is reduced before it reaches the chart, so statistics must never be computed
 * from it. The history loader hands the raw page-assembled samples (before reduction) to this store,
 * which keeps compact timestamp/value columns per series and answers any sub-interval exactly.
 *
 * Coverage rule: statistics are only offered when the store provably holds the window from its
 * start. A history seeded from the in-memory retention cache plus a delta load does NOT, so the
 * provider answers `null` and the UI says the statistics are unavailable until the history is
 * refreshed — never a number computed from partial data.
 */

import {
  appendIntervalSample,
  computeIntervalStatistics,
  createIntervalSampleColumns,
  pruneIntervalSamplesBefore,
  type IntervalSampleColumns,
  type IntervalStatistics,
} from "@/features/charts/interval-statistics";
import { resolveEnergyMeter } from "@/features/energy/energy-telemetry";
import type { TelemetrySample } from "@/lib/telemetry/types";

interface Entry {
  columns: Map<string, IntervalSampleColumns>;
  /** Metrics the base load actually covered; statistics for any other metric are unavailable. */
  metrics: Set<string>;
  /** Start of the window the raw columns are complete from. */
  coveredFromMs: number;
}

/** Same identity as the Energy chart series (node, meter equipment, channel, metric, native unit). */
export function energyStatisticsKey(sample: TelemetrySample): string | null {
  const meter = resolveEnergyMeter(sample);
  if (!meter) return null;
  return [sample.node_id, meter.equipmentId, sample.channel_id, sample.metric, sample.unit]
    .map((part) => encodeURIComponent(part))
    .join("|");
}

export function energySeriesStatisticsKey(identity: {
  nodeId: string;
  equipmentId: string;
  channelId: string;
  metric: string;
  nativeUnit: string;
}): string {
  return [identity.nodeId, identity.equipmentId, identity.channelId, identity.metric, identity.nativeUnit]
    .map((part) => encodeURIComponent(part))
    .join("|");
}

export class EnergyRawStatistics {
  private readonly entries = new Map<string, Entry>();

  /** A full (non-delta) load: the store now holds the whole window starting at `coveredFromMs`. */
  replace(
    rangeKey: string,
    coveredFromMs: number,
    samples: readonly TelemetrySample[],
    metrics: readonly string[],
  ): void {
    const entry: Entry = { columns: new Map(), metrics: new Set(metrics), coveredFromMs };
    this.entries.set(rangeKey, entry);
    this.append(rangeKey, samples);
  }

  /** Delta or live samples; ignored when no complete base exists for the range. */
  append(rangeKey: string, samples: readonly TelemetrySample[]): void {
    const entry = this.entries.get(rangeKey);
    if (!entry) return;
    for (const sample of samples) {
      const key = energyStatisticsKey(sample);
      if (!key || !entry.metrics.has(sample.metric)) continue;
      const columns = entry.columns.get(key) ?? createIntervalSampleColumns();
      entry.columns.set(key, columns);
      const valid = sample.quality === "valid" && sample.value !== null && Number.isFinite(sample.value);
      appendIntervalSample(columns, Date.parse(sample.captured_at), valid ? sample.value : null);
    }
  }

  prune(rangeKey: string, fromMs: number): void {
    const entry = this.entries.get(rangeKey);
    if (!entry) return;
    for (const columns of entry.columns.values()) pruneIntervalSamplesBefore(columns, fromMs);
    entry.coveredFromMs = Math.max(entry.coveredFromMs, fromMs);
  }

  hasBase(rangeKey: string): boolean {
    return this.entries.has(rangeKey);
  }

  /** `null` when the store cannot guarantee the interval (no base, or the interval starts before it). */
  statistics(
    rangeKey: string,
    seriesKey: string,
    metric: string,
    fromMs: number,
    toMs: number,
  ): IntervalStatistics | null {
    const entry = this.entries.get(rangeKey);
    if (!entry || fromMs < entry.coveredFromMs || !entry.metrics.has(metric)) return null;
    const columns = entry.columns.get(seriesKey);
    return columns
      ? computeIntervalStatistics(columns, fromMs, toMs)
      : computeIntervalStatistics(createIntervalSampleColumns(), fromMs, toMs);
  }

  clear(): void {
    this.entries.clear();
  }
}
