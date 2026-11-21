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

export interface CadenceProbeOptions {
  now?: number;
  signal?: AbortSignal;
  maxChannels?: number;
  concurrency?: number;
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
  const targets = probeTargets(samples, options.maxChannels ?? CADENCE_PROBE_MAX_CHANNELS);
  const concurrency = Math.max(1, Math.floor(options.concurrency ?? CADENCE_PROBE_CONCURRENCY));
  const from = new Date(now - CADENCE_PROBE_LOOKBACK_MS);
  const to = new Date(now);
  let observations: CadenceObservations = EMPTY_CADENCE_OBSERVATIONS;
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
          .map((item) => Date.parse(item.captured_at));
        observations = seedCadenceObservations(observations, key, timestamps);
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
