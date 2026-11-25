import { deriveChartSourceGapMs } from "@/features/charts/continuity";
import type { TelemetrySample } from "@/lib/telemetry/types";

import { decodeRelayBits } from "./controller-monitoring";

export type TimelineInterval = {
  fromMs: number;
  toMs: number;
  label: string;
  active: boolean;
  /**
   * `unknown`: the controller WAS polled but the state cannot be established (non-valid sample at
   * either end). Distinct from NO DATA, which is the absence of any interval (silent gap).
   * Unknown intervals never count as ON, OFF or covered time.
   */
  kind?: "state" | "unknown";
};

export type RelayTransition = {
  relayIndex: number;
  fromState: boolean;
  toState: boolean;
  previousObservedAtMs: number;
  observedAtMs: number;
  previousEventId: string;
  eventId: string;
};

const STATE_LABELS: Record<number, string> = {
  0: "Idle",
  1: "Cooling",
  2: "Prepare defrost",
  3: "Defrost",
  4: "Post-defrost",
  5: "Pulldown",
};

const DEFROST_STATE_CODE = 3;

const DEFAULT_TIMELINE_SOURCE_GAP_MS = 90_000;

type OrderedSample = TelemetrySample & { capturedAtMs: number; usable: boolean };

function orderedEvidence(samples: readonly TelemetrySample[]): OrderedSample[] {
  const byTimestamp = new Map<number, OrderedSample>();
  for (const sample of samples) {
    const capturedAtMs = Date.parse(sample.captured_at);
    if (!Number.isFinite(capturedAtMs)) continue;
    byTimestamp.set(capturedAtMs, {
      ...sample,
      capturedAtMs,
      usable: sample.quality === "valid" && sample.value !== null && Number.isFinite(sample.value),
    });
  }
  return [...byTimestamp.values()].sort((left, right) => left.capturedAtMs - right.capturedAtMs);
}

function sourceGapMs(samples: readonly OrderedSample[]): number {
  return deriveChartSourceGapMs(
    samples.map((sample) => ({ id: sample.event_id, timestampMs: sample.capturedAtMs })),
    DEFAULT_TIMELINE_SOURCE_GAP_MS,
  );
}

function intervals<T>(
  samples: readonly TelemetrySample[],
  range: { from: Date; to: Date },
  decode: (value: number) => T,
  project: (value: T) => { label: string; active: boolean } | null,
): TimelineInterval[] {
  const ordered = orderedEvidence(samples);
  const threshold = sourceGapMs(ordered);
  const fromBound = range.from.getTime();
  const toBound = range.to.getTime();
  const result: TimelineInterval[] = [];
  for (let index = 0; index < ordered.length - 1; index += 1) {
    const current = ordered[index];
    const next = ordered[index + 1];
    if (!current || !next || !current.usable || !next.usable || current.value === null) continue;
    const sourceDurationMs = next.capturedAtMs - current.capturedAtMs;
    if (sourceDurationMs <= 0 || sourceDurationMs > threshold) continue;
    const fromMs = Math.max(fromBound, current.capturedAtMs);
    const toMs = Math.min(toBound, next.capturedAtMs);
    if (toMs <= fromMs) continue;
    const projected = project(decode(Math.trunc(current.value)));
    if (projected) result.push({ fromMs, toMs, ...projected });
  }
  return result;
}

export function buildControlStateTimeline(
  samples: readonly TelemetrySample[],
  range: { from: Date; to: Date },
): TimelineInterval[] {
  return intervals(
    samples,
    range,
    (value) => STATE_LABELS[value] ?? `State ${value}`,
    (label) => ({ label, active: label !== "Idle" }),
  );
}

/**
 * Compressor ON/OFF derived from the measured compressor speed: ON when a valid speed is above
 * 0 rpm, OFF when it is exactly 0 (the same definition as the runtime-duty and start counters).
 * It is a derived lane, not a controller relay state.
 */
export function buildCompressorTimeline(
  samples: readonly TelemetrySample[],
  range: { from: Date; to: Date },
): TimelineInterval[] {
  return intervals(
    samples,
    range,
    (value) => value,
    (rpm) => (rpm < 0 ? null : { label: rpm > 0 ? "ON" : "OFF", active: rpm > 0 }),
  );
}

export function buildDefrostTimeline(
  samples: readonly TelemetrySample[],
  range: { from: Date; to: Date },
): TimelineInterval[] {
  return intervals(
    samples,
    range,
    (value) => value,
    (state) => {
      if (!Object.hasOwn(STATE_LABELS, state)) return null;
      const active = state === DEFROST_STATE_CODE;
      return { label: active ? "ON" : "OFF", active };
    },
  );
}

/**
 * Intervals between consecutive polls (within the cadence tolerance) where at least one endpoint
 * has no valid state: communication/sensor error or unknown quality. The state is UNKNOWN there —
 * never inferred as OFF. Silent gaps beyond the tolerance stay empty (NO DATA).
 */
export function buildUnknownTimeline(
  samples: readonly TelemetrySample[],
  range: { from: Date; to: Date },
): TimelineInterval[] {
  const ordered = orderedEvidence(samples);
  const threshold = sourceGapMs(ordered);
  const fromBound = range.from.getTime();
  const toBound = range.to.getTime();
  const result: TimelineInterval[] = [];
  for (let index = 0; index < ordered.length - 1; index += 1) {
    const current = ordered[index];
    const next = ordered[index + 1];
    if (!current || !next || (current.usable && next.usable)) continue;
    const sourceDurationMs = next.capturedAtMs - current.capturedAtMs;
    if (sourceDurationMs <= 0 || sourceDurationMs > threshold) continue;
    const fromMs = Math.max(fromBound, current.capturedAtMs);
    const toMs = Math.min(toBound, next.capturedAtMs);
    if (toMs > fromMs) result.push({ fromMs, toMs, label: "Невідомо", active: false, kind: "unknown" });
  }
  return result;
}

export function summarizeActiveTimeline(
  timeline: readonly TimelineInterval[],
  range: { from: Date; to: Date },
): { activeMs: number; coveredMs: number } {
  const fromMs = range.from.getTime();
  const toMs = range.to.getTime();
  let activeMs = 0;
  let coveredMs = 0;
  for (const interval of timeline) {
    if (interval.kind === "unknown") continue;
    const durationMs = Math.max(0, Math.min(toMs, interval.toMs) - Math.max(fromMs, interval.fromMs));
    coveredMs += durationMs;
    if (interval.active) activeMs += durationMs;
  }
  return { activeMs, coveredMs };
}

export function buildRelayTimeline(
  samples: readonly TelemetrySample[],
  relayIndex: number,
  range: { from: Date; to: Date },
): TimelineInterval[] {
  assertRelayIndex(relayIndex);
  return intervals(samples, range, decodeRelayBits, (states) => ({
    label: states[relayIndex] ? "ON" : "OFF",
    active: states[relayIndex] ?? false,
  }));
}

export function buildRelayTransitions(
  samples: readonly TelemetrySample[],
  relayIndex: number,
  range: { from: Date; to: Date },
): RelayTransition[] {
  assertRelayIndex(relayIndex);
  const ordered = orderedEvidence(samples);
  const threshold = sourceGapMs(ordered);
  const fromBound = range.from.getTime();
  const toBound = range.to.getTime();
  const result: RelayTransition[] = [];

  for (let index = 1; index < ordered.length; index += 1) {
    const previous = ordered[index - 1];
    const current = ordered[index];
    if (!previous || !current || !previous.usable || !current.usable) continue;
    if (previous.value === null || current.value === null) continue;
    const durationMs = current.capturedAtMs - previous.capturedAtMs;
    if (durationMs <= 0 || durationMs > threshold) continue;
    if (current.capturedAtMs < fromBound || current.capturedAtMs > toBound) continue;

    const previousState = decodeRelayBits(Math.trunc(previous.value))[relayIndex] ?? false;
    const currentState = decodeRelayBits(Math.trunc(current.value))[relayIndex] ?? false;
    if (previousState === currentState) continue;
    result.push({
      relayIndex,
      fromState: previousState,
      toState: currentState,
      previousObservedAtMs: previous.capturedAtMs,
      observedAtMs: current.capturedAtMs,
      previousEventId: previous.event_id,
      eventId: current.event_id,
    });
  }
  return result;
}

function assertRelayIndex(relayIndex: number): void {
  if (!Number.isInteger(relayIndex) || relayIndex < 0 || relayIndex > 3) {
    throw new Error("relayIndex must be 0..3");
  }
}
