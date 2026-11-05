import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import { reconcileEnergyLiveHistory, seedEnergyLiveHistoryState } from "./energy-live-history";
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

const meterKey = JSON.stringify(["edge-01", "LE01MP-200"]);

describe("energy live history reconciliation", () => {
  it("does not let a different node clear an outage on the same meter ID", () => {
    const outage = reconcileEnergyLiveHistory([sample(5, "communication_error")]);
    const other = reconcileEnergyLiveHistory(
      [{ ...sample(10), node_id: "edge-02" }],
      outage.pendingMeterKeys,
      outage.newestCapturedAtByMeterKey,
    );
    expect(other.pendingMeterKeys.has(meterKey)).toBe(true);
    expect(isEnergyHistorySegmentStart(other.samples[0].event_id)).toBe(false);
    const recovered = reconcileEnergyLiveHistory(
      [sample(15)],
      other.pendingMeterKeys,
      other.newestCapturedAtByMeterKey,
    );
    expect(isEnergyHistorySegmentStart(recovered.samples[0].event_id)).toBe(true);
  });
  it("retains a startup error without a prior renderable point", () => {
    const errorBatch = reconcileEnergyLiveHistory([sample(5, "communication_error")]);

    expect(errorBatch.pendingMeterKeys.has(meterKey)).toBe(true);
    expect(errorBatch.samples).toHaveLength(1);

    const recoveryBatch = reconcileEnergyLiveHistory(
      [sample(10)],
      errorBatch.pendingMeterKeys,
      errorBatch.newestCapturedAtByMeterKey,
    );

    expect(recoveryBatch.pendingMeterKeys.size).toBe(0);
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
    expect(result.pendingMeterKeys.size).toBe(0);
  });

  it("does not let a delayed valid replay resolve a newer outage", () => {
    const outage = reconcileEnergyLiveHistory([sample(20, "communication_error")]);
    const delayed = reconcileEnergyLiveHistory(
      [sample(10)],
      outage.pendingMeterKeys,
      outage.newestCapturedAtByMeterKey,
    );

    expect(delayed.pendingMeterKeys.has(meterKey)).toBe(true);
    expect(isEnergyHistorySegmentStart(delayed.samples[0].event_id)).toBe(false);

    const recovery = reconcileEnergyLiveHistory(
      [sample(25)],
      delayed.pendingMeterKeys,
      delayed.newestCapturedAtByMeterKey,
    );

    expect(recovery.pendingMeterKeys.size).toBe(0);
    expect(isEnergyHistorySegmentStart(recovery.samples[0].event_id)).toBe(true);
  });

  it("does not let a delayed error create a break behind the newest sample", () => {
    const current = reconcileEnergyLiveHistory([sample(25)]);
    const delayed = reconcileEnergyLiveHistory(
      [sample(10, "communication_error")],
      current.pendingMeterKeys,
      current.newestCapturedAtByMeterKey,
    );

    expect(delayed.pendingMeterKeys.size).toBe(0);
  });

  it("seeds a metric switch from retained samples before delayed replay", () => {
    const seed = seedEnergyLiveHistoryState([sample(25)]);
    const delayed = reconcileEnergyLiveHistory(
      [sample(10, "communication_error")],
      seed.pendingMeterKeys,
      seed.newestCapturedAtByMeterKey,
    );

    expect(seed.newestCapturedAtByMeterKey.get(meterKey)).toBe(Date.parse(sample(25).captured_at));
    expect(delayed.pendingMeterKeys.size).toBe(0);
  });

  it("preserves a retained latest communication error as pending", () => {
    const seed = seedEnergyLiveHistoryState([sample(10), sample(20, "communication_error")]);

    expect(seed.newestCapturedAtByMeterKey.get(meterKey)).toBe(Date.parse(sample(20).captured_at));
    expect(seed.pendingMeterKeys.has(meterKey)).toBe(true);
  });
});
