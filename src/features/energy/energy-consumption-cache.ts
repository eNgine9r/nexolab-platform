import {
  ENERGY_CONSUMPTION_ANCHOR_TOLERANCE_MS,
  ENERGY_CONSUMPTION_METRIC,
} from "@/features/energy/energy-consumption";
import { resolveEnergyMeter, type EnergyMeter } from "@/features/energy/energy-telemetry";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

const DEFAULT_BUCKET_MS = 5 * 60 * 1000;
const DEFAULT_TTL_MS = 5 * 60 * 1000;
const DEFAULT_LIMIT = 1000;
const DEFAULT_MAX_ENTRIES = 24;

type CacheEntry = {
  expiresAt: number;
  promise: Promise<readonly TelemetrySample[]>;
};

export interface EnergyBoundaryHistoryCache {
  load: (options: {
    adapter: TelemetryAdapter;
    scopeKey: string;
    nodeId: string;
    boundary: Date;
    toleranceMs?: number;
  }) => Promise<readonly TelemetrySample[]>;
  clear: () => void;
}

function validBoundaryTimestamp(sample: TelemetrySample, boundary: Date, toleranceMs: number): number | null {
  const capturedAt = Date.parse(sample.captured_at);
  const boundaryAt = boundary.getTime();
  if (!Number.isFinite(capturedAt) || capturedAt > boundaryAt) return null;
  if (boundaryAt - capturedAt > toleranceMs) return null;
  return capturedAt;
}

export function selectEnergyBoundarySample(
  samples: readonly TelemetrySample[],
  meter: EnergyMeter,
  boundary: Date,
  toleranceMs = ENERGY_CONSUMPTION_ANCHOR_TOLERANCE_MS,
): TelemetrySample | null {
  let selected: TelemetrySample | null = null;
  let selectedAt = Number.NEGATIVE_INFINITY;

  for (const sample of samples) {
    if (
      sample.metric !== ENERGY_CONSUMPTION_METRIC ||
      sample.quality !== "valid" ||
      sample.value === null ||
      !Number.isFinite(sample.value) ||
      resolveEnergyMeter(sample)?.unitId !== meter.unitId
    ) {
      continue;
    }
    const capturedAt = validBoundaryTimestamp(sample, boundary, toleranceMs);
    if (capturedAt !== null && capturedAt > selectedAt) {
      selected = sample;
      selectedAt = capturedAt;
    }
  }

  return selected;
}

export function createEnergyBoundaryHistoryCache({
  bucketMs = DEFAULT_BUCKET_MS,
  ttlMs = DEFAULT_TTL_MS,
  limit = DEFAULT_LIMIT,
  maxEntries = DEFAULT_MAX_ENTRIES,
}: {
  bucketMs?: number;
  ttlMs?: number;
  limit?: number;
  maxEntries?: number;
} = {}): EnergyBoundaryHistoryCache {
  const entries = new Map<string, CacheEntry>();

  const clear = () => entries.clear();

  const load: EnergyBoundaryHistoryCache["load"] = ({
    adapter,
    scopeKey,
    nodeId,
    boundary,
    toleranceMs = ENERGY_CONSUMPTION_ANCHOR_TOLERANCE_MS,
  }) => {
    const boundaryAt = boundary.getTime();
    if (!Number.isFinite(boundaryAt)) return Promise.resolve([]);

    const bucketStart = Math.floor(boundaryAt / bucketMs) * bucketMs;
    const key = `${scopeKey}:${nodeId}:${bucketStart}:${toleranceMs}`;
    const now = Date.now();
    const existing = entries.get(key);
    if (existing && existing.expiresAt > now) return existing.promise;
    if (existing) entries.delete(key);

    if (entries.size >= maxEntries) {
      for (const [entryKey, entry] of entries) {
        if (entry.expiresAt <= now || entries.size >= maxEntries) entries.delete(entryKey);
        if (entries.size < maxEntries) break;
      }
    }

    const promise = adapter
      .history({
        node_id: nodeId,
        metric: ENERGY_CONSUMPTION_METRIC,
        quality: "valid",
        from: new Date(bucketStart - toleranceMs),
        to: new Date(bucketStart + bucketMs),
        limit,
        offset: 0,
      })
      .then((response) => response.items)
      .catch((error: unknown) => {
        const current = entries.get(key);
        if (current?.promise === promise) entries.delete(key);
        throw error;
      });

    entries.set(key, { expiresAt: now + ttlMs, promise });
    return promise;
  };

  return { load, clear };
}
