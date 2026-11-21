import {
  CADENCE_OBSERVATION_LIMIT,
  EMPTY_CADENCE_OBSERVATIONS,
  MAX_ACQUISITION_CADENCE_MS,
  seedCadenceObservations,
  type CadenceObservations,
} from "@/features/live/freshness";
import { liveChannelKey } from "@/features/live/live-telemetry";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

/**
 * Initial cadence bootstrap for #1522.
 *
 * Without it a slow channel only learns its cadence after three live samples,
 * so a 60 s channel still flips to stale during the first minutes after the
 * page opens. The probe reads the newest few *persisted* samples of each
 * channel through the existing authorized read-only history API (descending
 * `captured_at`, tiny `limit`). It never polls Modbus, never contacts the
 * Device Agent and never changes acquisition. Failures are silent: the
 * conservative default threshold simply stays in effect.
 */

/** Enough look-back to contain three samples at the slowest allowed cadence. */
export const CADENCE_PROBE_LOOKBACK_MS = 2 * MAX_ACQUISITION_CADENCE_MS + 15 * 60_000;
export const CADENCE_PROBE_MAX_CHANNELS = 120;
export const CADENCE_PROBE_CONCURRENCY = 3;
/** Reopening Live within this window reuses earlier probe results instead of re-reading history. */
export const CADENCE_PROBE_CACHE_TTL_MS = 10 * 60_000;
export const CADENCE_PROBE_CACHE_MAX_ENTRIES = 500;

export interface CadenceProbeCacheEntry {
  fetchedAt: number;
  timestamps: readonly number[];
}

/**
 * Bounded in-memory (per browser tab) probe cache. Entries are keyed by the
 * caller's authorization scope *and* the channel identity, so results never
 * leak between organizations. An empty history is cached too, so channels
 * without persisted samples are not re-requested on every page open; failed
 * requests are never cached.
 */
export class CadenceProbeCache {
  private readonly entries = new Map<string, CadenceProbeCacheEntry>();

  constructor(
    private readonly ttlMs = CADENCE_PROBE_CACHE_TTL_MS,
    private readonly maxEntries = CADENCE_PROBE_CACHE_MAX_ENTRIES,
  ) {}

  get size(): number {
    return this.entries.size;
  }

  get(scope: string, key: string, now: number): CadenceProbeCacheEntry | undefined {
    const id = `${scope}\u0000${key}`;
    const entry = this.entries.get(id);
    if (!entry) return undefined;
    if (now - entry.fetchedAt > this.ttlMs || entry.fetchedAt > now) {
      this.entries.delete(id);
      return undefined;
    }
    return entry;
  }

  set(scope: string, key: string, entry: CadenceProbeCacheEntry): void {
    const id = `${scope}\u0000${key}`;
    this.entries.delete(id);
    this.entries.set(id, entry);
    while (this.entries.size > this.maxEntries) {
      const oldest = this.entries.keys().next().value;
      if (oldest === undefined) break;
      this.entries.delete(oldest);
    }
  }

  clear(): void {
    this.entries.clear();
  }
}

export interface CadenceProbeOptions {
  now?: number;
  signal?: AbortSignal;
  maxChannels?: number;
  concurrency?: number;
  /** Optional cache; requires `cacheScope` (the organization/authorization scope). */
  cache?: CadenceProbeCache;
  cacheScope?: string;
}

function probeTargets(samples: readonly TelemetrySample[], maxChannels: number): TelemetrySample[] {
  const byKey = new Map<string, TelemetrySample>();
  for (const sample of samples) {
    // A server freshness contract is already authoritative for this channel.
    if (typeof sample.stale_after_seconds === "number" && sample.stale_after_seconds > 0) continue;
    const key = liveChannelKey(sample);
    if (!byKey.has(key)) byKey.set(key, sample);
  }
  return [...byKey.values()].slice(0, Math.max(0, maxChannels));
}

export async function probeLiveChannelCadence(
  adapter: Pick<TelemetryAdapter, "history">,
  samples: readonly TelemetrySample[],
  options: CadenceProbeOptions = {},
): Promise<CadenceObservations> {
  const now = options.now ?? Date.now();
  const cache = options.cache && options.cacheScope !== undefined ? options.cache : undefined;
  const cacheScope = options.cacheScope ?? "";
  let observations: CadenceObservations = EMPTY_CADENCE_OBSERVATIONS;
  const targets = probeTargets(samples, options.maxChannels ?? CADENCE_PROBE_MAX_CHANNELS).filter(
    (target) => {
      const key = liveChannelKey(target);
      const cached = cache?.get(cacheScope, key, now);
      if (!cached) return true;
      observations = seedCadenceObservations(observations, key, cached.timestamps);
      return false;
    },
  );
  const concurrency = Math.max(1, Math.floor(options.concurrency ?? CADENCE_PROBE_CONCURRENCY));
  const from = new Date(now - CADENCE_PROBE_LOOKBACK_MS);
  const to = new Date(now);
  let cursor = 0;
  let denied = false;

  const worker = async () => {
    while (!denied && !options.signal?.aborted && cursor < targets.length) {
      const target = targets[cursor];
      cursor += 1;
      const key = liveChannelKey(target);
      try {
        const response = await adapter.history(
          {
            node_id: target.node_id,
            equipment_id: target.equipment_id,
            channel_id: target.channel_id,
            metric: target.metric,
            from,
            to,
            limit: CADENCE_OBSERVATION_LIMIT,
            offset: 0,
          },
          options.signal,
        );
        const timestamps = response.items
          .filter((item) => liveChannelKey(item) === key)
          .map((item) => Date.parse(item.captured_at))
          .filter((value) => Number.isFinite(value));
        if (options.signal?.aborted) return;
        observations = seedCadenceObservations(observations, key, timestamps);
        cache?.set(cacheScope, key, { fetchedAt: now, timestamps });
      } catch (error) {
        if (options.signal?.aborted) return;
        const status = (error as { status?: unknown } | null)?.status;
        // Authorization failures will not improve for other channels.
        if (status === 401 || status === 403) denied = true;
      }
    }
  };

  await Promise.all(Array.from({ length: Math.min(concurrency, targets.length) }, worker));
  return observations;
}
