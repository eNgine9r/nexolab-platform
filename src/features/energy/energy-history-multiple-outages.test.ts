import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import { mergeEnergyHistoryTail } from "./energy-history";
import {
  energyHistorySourceEventId,
  isEnergyHistoryBreakPending,
  isEnergyHistorySegmentStart,
} from "./energy-history-segment";

function sample(second: number, quality: TelemetrySample["quality"] = "valid"): TelemetrySample {
  return {
    event_id: `energy-${second}`,
    node_id: "edge-01",
    captured_at: new Date(Date.UTC(2026, 7, 3, 10, 0, second)).toISOString(),
    metric: "electrical.power.active",
    value: quality === "valid" ? second : null,
    unit: "W",
    quality,
    source: "f-and-f-le-01mp",
    equipment_id: "LE01MP-200",
    channel_id: "200-active-power",
    alarm: null,
    raw_value: second,
    raw_status: null,
  };
}

const window = {
  nodeId: "edge-01",
  metric: "electrical.power.active" as const,
  from: new Date("2026-08-03T10:00:00Z"),
  to: new Date("2026-08-03T10:00:30Z"),
};

function findSample(samples: readonly TelemetrySample[], eventId: string): TelemetrySample {
  const result = samples.find((item) => energyHistorySourceEventId(item.event_id) === eventId);
  if (!result) throw new Error(`Missing history sample ${eventId}`);
  return result;
}

describe("energy history repeated outages", () => {
  it("preserves an existing segment marker while queuing the next break", () => {
    const afterFirstError = mergeEnergyHistoryTail([sample(0)], [sample(5, "communication_error")], window);
    const afterFirstRecovery = mergeEnergyHistoryTail(afterFirstError, [sample(10)], window);

    expect(isEnergyHistorySegmentStart(findSample(afterFirstRecovery, "energy-10").event_id)).toBe(true);

    const afterSecondError = mergeEnergyHistoryTail(
      afterFirstRecovery,
      [sample(15, "communication_error")],
      window,
    );
    const intermediateRecovery = findSample(afterSecondError, "energy-10");

    expect(isEnergyHistorySegmentStart(intermediateRecovery.event_id)).toBe(true);
    expect(isEnergyHistoryBreakPending(intermediateRecovery.event_id)).toBe(true);

    const afterSecondRecovery = mergeEnergyHistoryTail(afterSecondError, [sample(20)], window);

    expect(isEnergyHistorySegmentStart(findSample(afterSecondRecovery, "energy-10").event_id)).toBe(true);
    expect(isEnergyHistorySegmentStart(findSample(afterSecondRecovery, "energy-20").event_id)).toBe(true);
    expect(afterSecondRecovery.some((item) => isEnergyHistoryBreakPending(item.event_id))).toBe(false);
  });
});
