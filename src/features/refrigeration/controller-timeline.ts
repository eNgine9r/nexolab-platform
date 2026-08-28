import { deriveChartSourceGapMs } from "@/features/charts/continuity";
import type { TelemetrySample } from "@/lib/telemetry/types";

import { decodeRelayBits } from "./controller-monitoring";

export type TimelineInterval = {
  fromMs: number;
  toMs: number;
  label: string;
  active: boolean;
};

const STATE_LABELS: Record<number, string> = {
  0: "Idle",
  1: "Cooling",
  2: "Prepare defrost",
  3: "Defrost",
  4: "Post-defrost",
  5: "Pulldown",
};

function orderedValid(samples: readonly TelemetrySample[]): TelemetrySample[] {
  return [...samples]
    .filter(
      (sample) =>
        sample.quality === "valid" &&
        sample.value !== null &&
        Number.isFinite(sample.value) &&
        Number.isFinite(Date.parse(sample.captured_at)),
    )
    .sort((left, right) => Date.parse(left.captured_at) - Date.parse(right.captured_at));
}

function intervals<T>(
  samples: readonly TelemetrySample[],
  range: { from: Date; to: Date },
  decode: (value: number) => T,
  project: (value: T) => { label: string; active: boolean },
): TimelineInterval[] {
  const ordered = orderedValid(samples);
  const threshold = deriveChartSourceGapMs(
    ordered.map((sample) => ({ id: sample.event_id, timestampMs: Date.parse(sample.captured_at) })),
    90_000,
  );
  const fromBound = range.from.getTime();
  const toBound = range.to.getTime();
  const result: TimelineInterval[] = [];
  for (let index = 0; index < ordered.length - 1; index += 1) {
    const current = ordered[index];
    const next = ordered[index + 1];
    if (!current || !next || current.value === null) continue;
    const fromMs = Math.max(fromBound, Date.parse(current.captured_at));
    const toMs = Math.min(toBound, Date.parse(next.captured_at));
    if (toMs <= fromMs || toMs - fromMs > threshold) continue;
    const projected = project(decode(Math.trunc(current.value)));
    result.push({ fromMs, toMs, ...projected });
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

export function buildRelayTimeline(
  samples: readonly TelemetrySample[],
  relayIndex: number,
  range: { from: Date; to: Date },
): TimelineInterval[] {
  if (!Number.isInteger(relayIndex) || relayIndex < 0 || relayIndex > 3) {
    throw new Error("relayIndex must be 0..3");
  }
  return intervals(samples, range, decodeRelayBits, (states) => ({
    label: states[relayIndex] ? "ON" : "OFF",
    active: states[relayIndex] ?? false,
  }));
}
