import type { EnergyCadenceAuthority } from "./energy-cadence-authority";
import { loadCompleteEnergyHistory, mergeEnergyHistoryTail } from "./energy-history";
import {
  invalidateRetainedEnergyHistory,
  readRetainedEnergyHistory,
  retainEnergyHistory,
  type EnergyHistoryRetentionKey,
  type RetainedEnergyHistory,
} from "./energy-history-retention";
import { ENERGY_METRICS, type EnergyMetricId } from "./energy-telemetry";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

export interface EnergyComparisonWindow {
  nodeId: string;
  from: Date;
  to: Date;
}

export interface EnergyComparisonHistory {
  samples: TelemetrySample[];
  errors: Partial<Record<EnergyMetricId, string>>;
}

export function normalizeEnergyMetrics(metrics: readonly EnergyMetricId[]): EnergyMetricId[] {
  const selected = new Set(metrics);
  return ENERGY_METRICS.filter((metric) => selected.has(metric.id)).map((metric) => metric.id);
}

export function readEnergyComparisonHistory(
  key: EnergyHistoryRetentionKey,
  metrics: readonly EnergyMetricId[],
): RetainedEnergyHistory | null {
  if (metrics.length === 0) return null;
  const entries = metrics.map((metric) => readRetainedEnergyHistory({ ...key, metric }));
  if (entries.some((entry) => entry === null)) return null;
  const retained = entries as RetainedEnergyHistory[];
  if (
    retained.some((entry) => entry.cadenceAuthorityFingerprint !== retained[0].cadenceAuthorityFingerprint)
  ) {
    return null;
  }
  return {
    window: {
      from: new Date(Math.max(...retained.map((entry) => Date.parse(entry.window.from)))).toISOString(),
      to: new Date(Math.min(...retained.map((entry) => Date.parse(entry.window.to)))).toISOString(),
    },
    loadedThrough: new Date(
      Math.min(...retained.map((entry) => Date.parse(entry.loadedThrough))),
    ).toISOString(),
    cadenceAuthorityFingerprint: retained[0].cadenceAuthorityFingerprint,
    samples: retained.flatMap((entry) => entry.samples),
  };
}

export function invalidateEnergyComparisonHistory(
  key: EnergyHistoryRetentionKey,
  metrics: readonly EnergyMetricId[],
): void {
  for (const metric of metrics) invalidateRetainedEnergyHistory({ ...key, metric });
}

export function retainEnergyComparisonHistory(
  key: EnergyHistoryRetentionKey,
  metrics: readonly EnergyMetricId[],
  value: RetainedEnergyHistory,
  errors: EnergyComparisonHistory["errors"] = {},
): void {
  for (const metric of metrics) {
    if (errors[metric]) continue;
    retainEnergyHistory(
      { ...key, metric },
      { ...value, samples: value.samples.filter((sample) => sample.metric === metric) },
    );
  }
}

export function mergeEnergyComparisonHistory(
  existing: readonly TelemetrySample[],
  incoming: readonly TelemetrySample[],
  window: EnergyComparisonWindow,
  metrics: readonly EnergyMetricId[],
  cadenceAuthority: EnergyCadenceAuthority | null,
): TelemetrySample[] {
  return metrics.flatMap((metric) =>
    mergeEnergyHistoryTail(existing, incoming, { ...window, metric }, cadenceAuthority),
  );
}

/** At most two REST history reads in flight; every selected metric shares one ingestion watermark. */
export async function loadEnergyComparisonHistory(
  adapter: TelemetryAdapter,
  window: EnergyComparisonWindow,
  metrics: readonly EnergyMetricId[],
  signal?: AbortSignal,
  cadenceAuthority: EnergyCadenceAuthority | null = null,
): Promise<EnergyComparisonHistory> {
  const selected = normalizeEnergyMetrics(metrics);
  if (selected.length === 0) return { samples: [], errors: {} };
  if (selected.length === 1) {
    return {
      samples: await loadCompleteEnergyHistory(
        adapter,
        { ...window, metric: selected[0] },
        signal,
        cadenceAuthority,
      ),
      errors: {},
    };
  }

  let resolveSnapshot!: (snapshot: string) => void;
  let rejectSnapshot!: (error: unknown) => void;
  const snapshotReady = new Promise<string>((resolve, reject) => {
    resolveSnapshot = resolve;
    rejectSnapshot = reject;
  });
  // The first read can fail synchronously, before the second worker awaits it.
  void snapshotReady.catch(() => undefined);
  const firstAdapter: TelemetryAdapter = {
    ...adapter,
    history: async (filters, abortSignal) => {
      const response = await adapter.history(filters, abortSignal);
      if (!response.snapshot_at || !Number.isFinite(Date.parse(response.snapshot_at))) {
        throw new Error("Telemetry history page did not provide an ingestion snapshot watermark");
      }
      resolveSnapshot(response.snapshot_at);
      return response;
    },
  };
  const results = new Map<EnergyMetricId, TelemetrySample[]>();
  const errors: EnergyComparisonHistory["errors"] = {};
  let nextIndex = 0;
  const worker = async () => {
    while (nextIndex < selected.length && !signal?.aborted) {
      const index = nextIndex++;
      const metric = selected[index];
      try {
        const snapshot = index === 0 ? undefined : await snapshotReady;
        const samples = await loadCompleteEnergyHistory(
          index === 0 ? firstAdapter : adapter,
          { ...window, metric },
          signal,
          cadenceAuthority,
          snapshot,
        );
        results.set(metric, samples);
      } catch (error) {
        if (index === 0) rejectSnapshot(error);
        errors[metric] = error instanceof Error ? error.message : "Не вдалося завантажити історію.";
      }
    }
  };
  await Promise.all([worker(), worker()]);
  return { samples: selected.flatMap((metric) => results.get(metric) ?? []), errors };
}
