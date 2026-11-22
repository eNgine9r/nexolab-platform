/**
 * Exact interval statistics from RAW persisted measurements (#1645, WP-B).
 *
 * Chart render points are reduced to a visual budget, so min/max/average/count computed from
 * them would be wrong (spec §6.4). This module keeps a compact, append-only column store of the
 * raw measurements a surface loaded (before reduction) and computes statistics for ANY
 * sub-interval — the full requested window or the zoomed viewport — with explicit coverage
 * semantics:
 *
 * - only valid, finite measurements enter min / max / average / count;
 * - non-valid samples (communication/sensor/unknown quality) are counted separately and are
 *   never treated as zero or as measurements;
 * - the average is withheld (`null`, `averageStatus: "insufficient_coverage"`) when the interval
 *   is not sufficiently covered, because an arithmetic mean over a sparse subset of an interval
 *   is not a faithful interval mean. Min/max stay available: they are real measurements;
 * - nothing is interpolated or invented between samples.
 */

import { CHART_MINIMUM_SOURCE_GAP_MS, CHART_SOURCE_GAP_MULTIPLIER } from "./continuity";

/** Minimum share of the expected samples that must exist before an average is reported. */
export const INTERVAL_MINIMUM_AVERAGE_COVERAGE = 0.8;
/** Fewer valid samples than this never produce an average (cadence cannot be established). */
export const INTERVAL_MINIMUM_AVERAGE_SAMPLES = 3;

export interface IntervalSampleColumns {
  /** Valid measurement timestamps, ascending, unique. */
  validTimestamps: number[];
  /** Values aligned with `validTimestamps`. */
  validValues: number[];
  /** Non-valid sample timestamps, ascending, unique. */
  invalidTimestamps: number[];
}

export type IntervalCoverageStatus = "sufficient" | "insufficient" | "no_data";
export type IntervalAverageStatus = "available" | "insufficient_coverage" | "no_data";

export interface IntervalGapSummary {
  /** Silent gaps: consecutive valid samples further apart than the cadence-aware tolerance. */
  count: number;
  totalMs: number;
  longestMs: number;
}

export interface IntervalStatistics {
  fromMs: number;
  toMs: number;
  min: number | null;
  max: number | null;
  average: number | null;
  averageStatus: IntervalAverageStatus;
  /** Valid measurements in the interval. */
  validCount: number;
  /** Non-valid samples (communication/sensor/unknown quality) in the interval. */
  invalidCount: number;
  firstTimestampMs: number | null;
  lastTimestampMs: number | null;
  /** Estimated acquisition cadence (median spacing) used for coverage, or null if unknown. */
  cadenceMs: number | null;
  /** Expected sample count at that cadence for the interval; null when cadence is unknown. */
  expectedCount: number | null;
  /** validCount / expectedCount, capped to 1; null when not computable. */
  coverageRatio: number | null;
  coverageStatus: IntervalCoverageStatus;
  gaps: IntervalGapSummary;
  /** Always the raw persisted evidence, never reduced render points. */
  basis: "raw_persisted";
}

export function createIntervalSampleColumns(): IntervalSampleColumns {
  return { validTimestamps: [], validValues: [], invalidTimestamps: [] };
}

function lowerBound(values: readonly number[], target: number): number {
  let low = 0;
  let high = values.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (values[middle] < target) low = middle + 1;
    else high = middle;
  }
  return low;
}

function upperBound(values: readonly number[], target: number): number {
  let low = 0;
  let high = values.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (values[middle] <= target) low = middle + 1;
    else high = middle;
  }
  return low;
}

/**
 * Records one raw sample. `value === null` records a non-valid sample. Duplicate timestamps
 * are ignored (history/live copies of the same event). Out-of-order timestamps are inserted in
 * place so the store stays sorted.
 */
export function appendIntervalSample(
  columns: IntervalSampleColumns,
  timestampMs: number,
  value: number | null,
): void {
  if (!Number.isFinite(timestampMs)) return;
  if (value === null || !Number.isFinite(value)) {
    const index = lowerBound(columns.invalidTimestamps, timestampMs);
    if (columns.invalidTimestamps[index] === timestampMs) return;
    columns.invalidTimestamps.splice(index, 0, timestampMs);
    return;
  }
  const stamps = columns.validTimestamps;
  const last = stamps.length - 1;
  if (last < 0 || timestampMs > stamps[last]) {
    stamps.push(timestampMs);
    columns.validValues.push(value);
    return;
  }
  const index = lowerBound(stamps, timestampMs);
  if (stamps[index] === timestampMs) return;
  stamps.splice(index, 0, timestampMs);
  columns.validValues.splice(index, 0, value);
}

/** Drops measurements older than `fromMs` so a rolling window does not grow without bound. */
export function pruneIntervalSamplesBefore(columns: IntervalSampleColumns, fromMs: number): void {
  const validCut = lowerBound(columns.validTimestamps, fromMs);
  if (validCut > 0) {
    columns.validTimestamps.splice(0, validCut);
    columns.validValues.splice(0, validCut);
  }
  const invalidCut = lowerBound(columns.invalidTimestamps, fromMs);
  if (invalidCut > 0) columns.invalidTimestamps.splice(0, invalidCut);
}

function median(sorted: readonly number[]): number {
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[middle - 1] + sorted[middle]) / 2 : sorted[middle];
}

export interface IntervalStatisticsOptions {
  /** Known acquisition cadence (ms); otherwise estimated from the interval's own spacings. */
  cadenceMs?: number | null;
  minimumAverageCoverage?: number;
}

/**
 * Statistics for the closed interval [fromMs, toMs]. Pure and deterministic for the same
 * columns and arguments.
 */
export function computeIntervalStatistics(
  columns: IntervalSampleColumns,
  fromMs: number,
  toMs: number,
  options: IntervalStatisticsOptions = {},
): IntervalStatistics {
  const low = Math.min(fromMs, toMs);
  const high = Math.max(fromMs, toMs);
  const start = lowerBound(columns.validTimestamps, low);
  const end = upperBound(columns.validTimestamps, high);
  const validCount = Math.max(0, end - start);
  const invalidCount = Math.max(
    0,
    upperBound(columns.invalidTimestamps, high) - lowerBound(columns.invalidTimestamps, low),
  );

  const base = {
    fromMs: low,
    toMs: high,
    invalidCount,
    basis: "raw_persisted" as const,
  };

  if (validCount === 0) {
    return {
      ...base,
      min: null,
      max: null,
      average: null,
      averageStatus: "no_data",
      validCount: 0,
      firstTimestampMs: null,
      lastTimestampMs: null,
      cadenceMs: null,
      expectedCount: null,
      coverageRatio: null,
      coverageStatus: "no_data",
      gaps: { count: 0, totalMs: 0, longestMs: 0 },
    };
  }

  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  let sum = 0;
  for (let index = start; index < end; index += 1) {
    const value = columns.validValues[index];
    if (value < min) min = value;
    if (value > max) max = value;
    sum += value;
  }

  const spacings: number[] = [];
  for (let index = start + 1; index < end; index += 1) {
    const delta = columns.validTimestamps[index] - columns.validTimestamps[index - 1];
    if (delta > 0) spacings.push(delta);
  }
  spacings.sort((a, b) => a - b);

  const explicitCadence =
    options.cadenceMs !== undefined && options.cadenceMs !== null && options.cadenceMs > 0
      ? options.cadenceMs
      : null;
  const cadenceMs = explicitCadence ?? (spacings.length >= 2 ? median(spacings) : null);

  const gapToleranceMs =
    cadenceMs === null
      ? CHART_MINIMUM_SOURCE_GAP_MS
      : Math.max(CHART_MINIMUM_SOURCE_GAP_MS, cadenceMs * CHART_SOURCE_GAP_MULTIPLIER);
  const gaps: IntervalGapSummary = { count: 0, totalMs: 0, longestMs: 0 };
  for (const delta of spacings) {
    if (delta > gapToleranceMs) {
      gaps.count += 1;
      gaps.totalMs += delta;
      if (delta > gaps.longestMs) gaps.longestMs = delta;
    }
  }

  const expectedCount = cadenceMs === null ? null : Math.max(1, Math.floor((high - low) / cadenceMs) + 1);
  const coverageRatio = expectedCount === null ? null : Math.min(1, validCount / expectedCount);
  const minimumCoverage = options.minimumAverageCoverage ?? INTERVAL_MINIMUM_AVERAGE_COVERAGE;
  const sufficient =
    coverageRatio !== null &&
    coverageRatio >= minimumCoverage &&
    validCount >= INTERVAL_MINIMUM_AVERAGE_SAMPLES;

  return {
    ...base,
    min,
    max,
    average: sufficient ? sum / validCount : null,
    averageStatus: sufficient ? "available" : "insufficient_coverage",
    validCount,
    firstTimestampMs: columns.validTimestamps[start],
    lastTimestampMs: columns.validTimestamps[end - 1],
    cadenceMs,
    expectedCount,
    coverageRatio,
    coverageStatus: sufficient ? "sufficient" : "insufficient",
    gaps,
  };
}
