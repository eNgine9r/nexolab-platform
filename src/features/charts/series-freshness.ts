/**
 * Per-series freshness helpers (#1643 follow-up, WP-F).
 *
 * Freshness is a property of each SERIES (its own newest sample), never of the page. Heavy
 * scene building (reduction, segmentation) must not re-run on every clock tick just to flip a
 * silent series to stale, so builders record `freshUntilMs` on a series that is currently
 * `live`; `applyFreshnessClock` then derives the state at `now` cheaply and returns the SAME
 * object references when nothing changed (no renderer update, no re-render).
 */

import type { ChartFreshnessState, ChartSeries } from "./domain";
import type { ChartRendererScene } from "./renderer-adapter";

export interface SeriesFreshnessInput {
  /** Page/connection-level state; connecting/reconnecting/offline always wins. */
  page: ChartFreshnessState;
  /** The series' own newest sample (any quality), or null when it has none. */
  latest: { timestampMs: number; valid: boolean } | null;
  /** Cadence-aware stale threshold for this series. */
  staleAfterMs: number;
  now: number;
}

export interface SeriesFreshness {
  freshness: ChartFreshnessState;
  /** Set only while `freshness === "live"`: the instant the series turns stale. */
  freshUntilMs?: number;
}

export function resolveSeriesFreshness(input: SeriesFreshnessInput): SeriesFreshness {
  const { page, latest, staleAfterMs, now } = input;
  if (page !== "live" && page !== "stale") return { freshness: page };
  if (!latest || !Number.isFinite(latest.timestampMs)) return { freshness: "stale" };
  if (!latest.valid) return { freshness: "invalid" };
  const freshUntilMs = latest.timestampMs + staleAfterMs;
  return now <= freshUntilMs ? { freshness: "live", freshUntilMs } : { freshness: "stale" };
}

/** Flips series whose `freshUntilMs` has passed to `stale`; returns the same array when nothing changed. */
export function flipExpiredSeries(series: readonly ChartSeries[], now: number): readonly ChartSeries[] {
  let changed = false;
  const next = series.map((entry): ChartSeries => {
    if (
      entry.freshness === "live" &&
      entry.freshUntilMs !== undefined &&
      Number.isFinite(entry.freshUntilMs) &&
      now > entry.freshUntilMs
    ) {
      changed = true;
      return { ...entry, freshness: "stale" };
    }
    return entry;
  });
  return changed ? next : series;
}

/** Flips series whose `freshUntilMs` has passed to `stale`; identity-stable when unchanged. */
export function applyFreshnessClock<T extends { scene: ChartRendererScene }>(
  groups: readonly T[],
  now: number,
): readonly T[] {
  let changed = false;
  const next = groups.map((group) => {
    const series = flipExpiredSeries(group.scene.series, now);
    if (series === group.scene.series) return group;
    changed = true;
    return { ...group, scene: { ...group.scene, series } };
  });
  return changed ? next : groups;
}

/**
 * For surfaces whose stale threshold is owned elsewhere (Energy cadence authority, controller
 * online flag): never show a series as live/stale when its OWN newest sample has no valid
 * measurement — report `invalid` instead. Page connectivity states pass through unchanged.
 */
export function withInvalidNewestSample(
  page: ChartFreshnessState,
  latest: { valid: boolean } | null,
): ChartFreshnessState {
  if ((page === "live" || page === "stale") && latest && !latest.valid) return "invalid";
  return page;
}

/** Validity of the newest (by `captured_at`) sample in a series, or null when empty. */
export function newestSampleValidity(
  samples: readonly { captured_at: string; quality: string; value: number | null }[],
): { valid: boolean } | null {
  let newest: (typeof samples)[number] | null = null;
  for (const sample of samples) {
    if (newest === null || Date.parse(sample.captured_at) >= Date.parse(newest.captured_at)) newest = sample;
  }
  return newest
    ? { valid: newest.quality === "valid" && newest.value !== null && Number.isFinite(newest.value) }
    : null;
}
