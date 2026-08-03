import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import { reconcileEnergyLiveHistory } from "./energy-live-history";
import { energyHistorySourceEventId, isEnergyHistorySegmentStart } from "./energy-history-segment";

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

describe("energy live history reconciliation", () => {
  it("retains a startup error without a prior renderable point", () => {
    const errorBatch = reconcileEnergyLiveHistory([sample(5, "communication_error")]);

    expect(errorBatch.pendingUnitIds.has(200)).toBe(true);
    expect(errorBatch.samples).toHaveLength(1);

    const recoveryBatch = reconcileEnergyLiveHistory([sample(10)], errorBatch.pendingUnitIds);

    expect(recoveryBatch.pendingUnitIds.size).toBe(0);
    expect(isEnergyHistorySegmentStart(recoveryBatch.samples[0].event_id)).toBe(true);
  });

  it("orders buffered snapshot-window events and preserves the outage boundary", () => {
    const result = reconcileEnergyLiveHistory([sample(15), sample(5), sample(10, "communication_error")]);

    expect(result.samples.map((item) => energyHistorySourceEventId(item.event_id))).toEqual([
      "energy-5",
      "energy-10",
      "energy-15",
    ]);
    expect(isEnergyHistorySegmentStart(result.samples[2].event_id)).toBe(true);
    expect(result.pendingUnitIds.size).toBe(0);
  });
});
