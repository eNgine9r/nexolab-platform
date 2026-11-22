/**
 * Exact digital state lanes from RAW measurement columns (#1679).
 *
 * Between two consecutive polls inside the cadence tolerance:
 * - both valid → the state of the earlier poll holds (ON/OFF);
 * - either has no valid state → UNKNOWN (a poll happened, the state cannot be established);
 * Longer silent gaps produce no interval at all = NO DATA. UNKNOWN is never OFF and NO DATA is never
 * OFF. Values a lane cannot represent (decode → null) are UNKNOWN as well — never guessed.
 */

import { CHART_MINIMUM_SOURCE_GAP_MS, CHART_SOURCE_GAP_MULTIPLIER } from "./continuity";
import type { IntervalSampleColumns } from "./interval-statistics";

export type LaneState = "on" | "off" | "unknown";

export interface LaneInterval {
  fromMs: number;
  toMs: number;
  state: LaneState;
}

export interface LaneSummary {
  onMs: number;
  offMs: number;
  unknownMs: number;
  /** Time with an established ON/OFF state (excludes UNKNOWN and NO DATA). */
  coveredMs: number;
  transitions: number;
}

interface Poll {
  at: number;
  value: number | null;
}

function merge(columns: IntervalSampleColumns): Poll[] {
  const polls: Poll[] = columns.validTimestamps.map((at, index) => ({
    at,
    value: columns.validValues[index],
  }));
  for (const at of columns.invalidTimestamps) polls.push({ at, value: null });
  return polls.sort((left, right) => left.at - right.at);
}

function median(sorted: readonly number[]): number {
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[middle - 1] + sorted[middle]) / 2 : sorted[middle];
}

export function buildStateLane(
  columns: IntervalSampleColumns,
  fromMs: number,
  toMs: number,
  decode: (value: number) => "on" | "off" | null,
): LaneInterval[] {
  const polls = merge(columns);
  if (polls.length < 2) return [];
  const spacings = polls
    .slice(1)
    .map((poll, index) => poll.at - polls[index].at)
    .filter((delta) => delta > 0);
  spacings.sort((left, right) => left - right);
  const tolerance = Math.max(
    CHART_MINIMUM_SOURCE_GAP_MS,
    spacings.length >= 2 ? median(spacings) * CHART_SOURCE_GAP_MULTIPLIER : 0,
  );
  const result: LaneInterval[] = [];
  for (let index = 0; index < polls.length - 1; index += 1) {
    const current = polls[index];
    const next = polls[index + 1];
    const duration = next.at - current.at;
    if (duration <= 0 || duration > tolerance) continue;
    const start = Math.max(fromMs, current.at);
    const end = Math.min(toMs, next.at);
    if (end <= start) continue;
    const decoded = current.value !== null && next.value !== null ? decode(current.value) : null;
    const state: LaneState = decoded ?? "unknown";
    const previous = result.at(-1);
    if (previous && previous.toMs === start && previous.state === state) previous.toMs = end;
    else result.push({ fromMs: start, toMs: end, state });
  }
  return result;
}

export function summarizeLane(intervals: readonly LaneInterval[]): LaneSummary {
  const summary: LaneSummary = { onMs: 0, offMs: 0, unknownMs: 0, coveredMs: 0, transitions: 0 };
  let previousKnown: LaneState | null = null;
  for (const interval of intervals) {
    const duration = interval.toMs - interval.fromMs;
    if (interval.state === "on") summary.onMs += duration;
    else if (interval.state === "off") summary.offMs += duration;
    else summary.unknownMs += duration;
    if (interval.state !== "unknown") {
      summary.coveredMs += duration;
      if (previousKnown !== null && previousKnown !== interval.state) summary.transitions += 1;
      previousKnown = interval.state;
    } else {
      previousKnown = null;
    }
  }
  return summary;
}

/** The lane state at the instant, or NO DATA (`null`) when no interval covers it. */
export function laneStateAt(intervals: readonly LaneInterval[], timestampMs: number): LaneState | null {
  const hit = intervals.find((interval) => timestampMs >= interval.fromMs && timestampMs < interval.toMs);
  return hit?.state ?? null;
}
