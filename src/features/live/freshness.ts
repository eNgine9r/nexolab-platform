import type { TelemetrySample } from "@/lib/telemetry/types";

/**
 * Cadence-aware Live/Stale freshness (#1522).
 *
 * A fixed 30 s threshold falsely flips slower channels (for example a 60 s
 * Waveshare 8AI poll) to "stale" between two perfectly on-time reads. The
 * threshold is therefore resolved per channel, in priority order:
 *
 * 1. `server_contract` — a positive `stale_after_seconds` delivered with the
 *    persisted sample by the Telemetry Service (authoritative when present);
 * 2. `observed_cadence` — the acquisition spacing actually observed for this
 *    exact channel identity in the live stream during this browser session;
 * 3. `default` — the historical conservative 30 s threshold.
 *
 * Observed cadence only ever relaxes the threshold for a channel that has
 * proven a slower regular cadence. It never changes `quality`, never infers an
 * attached sensor, never touches acquisition and never polls hardware.
 */

export const DEFAULT_LIVE_STALE_AFTER_MS = 30_000;
/** Scheduler jitter + MQTT/outbox + API/WebSocket propagation allowance. */
export const CADENCE_PROPAGATION_GRACE_MS = 15_000;
/** Half an interval of tolerance; one fully missed poll always becomes stale. */
export const CADENCE_TOLERANCE_FACTOR = 1.5;
/** Mirrors Device Agent `CADENCE_MAX_SECONDS`; longer gaps are outages, not cadence. */
export const MAX_ACQUISITION_CADENCE_MS = 3_600_000;
/** Spacings below this are duplicates/bursts, not a polling cadence. */
export const MIN_CADENCE_SPACING_MS = 1_000;
/** Bounded per-channel memory of distinct `captured_at` timestamps. */
export const CADENCE_OBSERVATION_LIMIT = 6;
/** Two independent spacings are required before a cadence is trusted. */
export const MIN_CADENCE_SPACINGS = 2;

export type LiveFreshnessBasis = "server_contract" | "observed_cadence" | "default";

export interface LiveFreshness {
  staleAfterMs: number;
  basis: LiveFreshnessBasis;
  cadenceMs: number | null;
}

/** Distinct captured_at epoch milliseconds per live channel key, ascending. */
export type CadenceObservations = Readonly<Record<string, readonly number[]>>;

export const EMPTY_CADENCE_OBSERVATIONS: CadenceObservations = Object.freeze({});

function finitePositive(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

/**
 * Records one acquisition timestamp for a channel. Returns the same object
 * when nothing changed so React state updates stay referentially stable.
 */
export function recordCadenceObservation(
  observations: CadenceObservations,
  key: string,
  capturedAtMs: number,
  limit = CADENCE_OBSERVATION_LIMIT,
): CadenceObservations {
  if (!Number.isFinite(capturedAtMs)) return observations;
  const current = observations[key] ?? [];
  if (current.includes(capturedAtMs)) return observations;
  if (current.length >= limit && capturedAtMs < current[0]) return observations;

  const next = [...current, capturedAtMs].sort((left, right) => left - right);
  while (next.length > limit) next.shift();
  return { ...observations, [key]: next };
}

/**
 * Conservative cadence estimate: the shortest plausible spacing between
 * recently observed distinct acquisitions. Using the minimum (not the mean)
 * means a communication gap can never stretch the threshold and hide a
 * genuinely stale channel; at worst a recent cadence increase is reported as
 * stale for a few cycles until older short spacings age out.
 */
export function observedCadenceMs(timestamps: readonly number[] | undefined): number | null {
  if (!timestamps || timestamps.length < MIN_CADENCE_SPACINGS + 1) return null;
  const spacings: number[] = [];
  for (let index = 1; index < timestamps.length; index += 1) {
    const spacing = timestamps[index] - timestamps[index - 1];
    if (spacing >= MIN_CADENCE_SPACING_MS && spacing <= MAX_ACQUISITION_CADENCE_MS) spacings.push(spacing);
  }
  if (spacings.length < MIN_CADENCE_SPACINGS) return null;
  return Math.min(...spacings);
}

export function staleAfterForCadenceMs(cadenceMs: number): number {
  const bounded = Math.min(Math.max(cadenceMs, 0), MAX_ACQUISITION_CADENCE_MS);
  return Math.max(
    DEFAULT_LIVE_STALE_AFTER_MS,
    Math.ceil(bounded * CADENCE_TOLERANCE_FACTOR + CADENCE_PROPAGATION_GRACE_MS),
  );
}

export function resolveLiveFreshness(
  sample: Pick<TelemetrySample, "stale_after_seconds">,
  observedCadence: number | null = null,
): LiveFreshness {
  const serverSeconds = finitePositive(sample.stale_after_seconds);
  if (serverSeconds !== null) {
    return {
      staleAfterMs: Math.min(serverSeconds * 1_000, MAX_ACQUISITION_CADENCE_MS * CADENCE_TOLERANCE_FACTOR),
      basis: "server_contract",
      cadenceMs: null,
    };
  }
  const cadence = finitePositive(observedCadence);
  if (cadence !== null) {
    return { staleAfterMs: staleAfterForCadenceMs(cadence), basis: "observed_cadence", cadenceMs: cadence };
  }
  return { staleAfterMs: DEFAULT_LIVE_STALE_AFTER_MS, basis: "default", cadenceMs: null };
}

export function liveFreshnessFor(
  sample: TelemetrySample,
  key: string,
  observations: CadenceObservations = EMPTY_CADENCE_OBSERVATIONS,
): LiveFreshness {
  return resolveLiveFreshness(sample, observedCadenceMs(observations[key]));
}

export function isLiveSampleFresh(sample: TelemetrySample, now: number, freshness: LiveFreshness): boolean {
  const capturedAt = Date.parse(sample.captured_at);
  return Number.isFinite(capturedAt) && now - capturedAt <= freshness.staleAfterMs;
}

export function formatFreshnessBasis(freshness: LiveFreshness): string {
  const seconds = Math.round(freshness.staleAfterMs / 1_000);
  if (freshness.basis === "server_contract") return `Поріг свіжості ${seconds} с · з контракту сервера`;
  if (freshness.basis === "observed_cadence" && freshness.cadenceMs !== null) {
    return `Поріг свіжості ${seconds} с · спостережений інтервал опитування ≈${Math.round(
      freshness.cadenceMs / 1_000,
    )} с`;
  }
  return `Поріг свіжості ${seconds} с · інтервал опитування ще не визначено`;
}

/** Records several acquisition timestamps for one channel (bounded, idempotent). */
export function seedCadenceObservations(
  observations: CadenceObservations,
  key: string,
  capturedAtMs: Iterable<number>,
): CadenceObservations {
  let next = observations;
  for (const value of capturedAtMs) next = recordCadenceObservation(next, key, value);
  return next;
}

/**
 * Seeds cadence from persisted samples the page has *already* loaded (no extra
 * API requests). Only the newest `limit` distinct timestamps per channel are
 * used; channels without history are simply left to learn from the live stream.
 */
export function seedCadenceFromSamples(
  observations: CadenceObservations,
  samples: readonly TelemetrySample[],
  keyOf: (sample: TelemetrySample) => string,
  limit = CADENCE_OBSERVATION_LIMIT,
): CadenceObservations {
  const byKey = new Map<string, number[]>();
  for (const sample of samples) {
    const capturedAt = Date.parse(sample.captured_at);
    if (!Number.isFinite(capturedAt)) continue;
    const key = keyOf(sample);
    const timestamps = byKey.get(key);
    if (timestamps) timestamps.push(capturedAt);
    else byKey.set(key, [capturedAt]);
  }
  let next = observations;
  for (const [key, timestamps] of byKey) {
    const newest = [...new Set(timestamps)].sort((left, right) => left - right).slice(-limit);
    next = seedCadenceObservations(next, key, newest);
  }
  return next;
}
