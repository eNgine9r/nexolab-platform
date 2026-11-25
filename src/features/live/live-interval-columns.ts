import {
  appendIntervalSample,
  computeIntervalStatistics,
  createIntervalSampleColumns,
  pruneIntervalSamplesBefore,
  type IntervalSampleColumns,
  type IntervalStatistics,
} from "@/features/charts/interval-statistics";
import { liveChannelKey } from "@/features/live/live-telemetry";
import type { TelemetrySample } from "@/lib/telemetry/types";

export type LiveIntervalColumns = Record<string, IntervalSampleColumns>;

/**
 * Records RAW persisted/live samples per channel (before any chart reduction) so interval
 * statistics stay exact (#1660). Duplicates by timestamp are ignored by the column store.
 */
export function recordLiveIntervalSamples(
  store: LiveIntervalColumns,
  samples: readonly TelemetrySample[],
): void {
  for (const sample of samples) {
    const key = liveChannelKey(sample);
    const columns = (store[key] ??= createIntervalSampleColumns());
    const valid = sample.quality === "valid" && sample.value !== null && Number.isFinite(sample.value);
    appendIntervalSample(columns, Date.parse(sample.captured_at), valid ? sample.value : null);
  }
}

export function pruneLiveIntervalSamples(store: LiveIntervalColumns, fromMs: number): void {
  for (const columns of Object.values(store)) pruneIntervalSamplesBefore(columns, fromMs);
}

export function liveIntervalStatistics(
  store: LiveIntervalColumns,
  channelKey: string,
  fromMs: number,
  toMs: number,
): IntervalStatistics | null {
  const columns = store[channelKey];
  return columns ? computeIntervalStatistics(columns, fromMs, toMs) : null;
}
