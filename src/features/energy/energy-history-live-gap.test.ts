import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import { downsampleEnergyHistory, mergeEnergyHistoryTail } from "./energy-history";
import {
  energyHistorySourceEventId,
  isEnergyHistoryInferredSegmentStart,
  isEnergyHistorySegmentStart,
} from "./energy-history-segment";

function sampleAtOffsetMs(offsetMs: number): TelemetrySample {
  return {
    event_id: `energy-edge-01-200-${offsetMs}`,
    node_id: "edge-01",
    captured_at: new Date(Date.UTC(2026, 7, 3, 10, 0, 0, offsetMs)).toISOString(),
    metric: "electrical.power.active",
    value: offsetMs,
    unit: "W",
    quality: "valid",
    source: "f-and-f-le-01mp",
    equipment_id: "LE01MP-200",
    channel_id: "200-active-power",
    alarm: null,
    raw_value: offsetMs,
    raw_status: null,
  };
}

const window = {
  nodeId: "edge-01",
  metric: "electrical.power.active" as const,
  from: new Date("2026-08-03T10:00:00Z"),
  to: new Date("2026-08-03T10:10:00Z"),
};

const rawHistory = [
  sampleAtOffsetMs(0),
  sampleAtOffsetMs(30_000),
  sampleAtOffsetMs(60_250),
  sampleAtOffsetMs(90_500),
  sampleAtOffsetMs(120_900),
];

function findByOffset(samples: readonly TelemetrySample[], offsetMs: number): TelemetrySample {
  const expectedId = `energy-edge-01-200-${offsetMs}`;
  const found = samples.find((sample) => energyHistorySourceEventId(sample.event_id) === expectedId);
  if (!found) throw new Error(`Expected ${expectedId}`);
  return found;
}

describe("energy live-tail source cadence", () => {
  it("detects a silent outage on the first recovery sample after reduced history", () => {
    const reduced = downsampleEnergyHistory(rawHistory, 3, window);
    const merged = mergeEnergyHistoryTail(reduced, [sampleAtOffsetMs(250_000)], window);
    const recovery = findByOffset(merged, 250_000);

    expect(isEnergyHistorySegmentStart(recovery.event_id)).toBe(true);
    expect(isEnergyHistoryInferredSegmentStart(recovery.event_id)).toBe(true);
  });

  it("carries the learned cadence through consecutive single-sample websocket merges", () => {
    const reduced = downsampleEnergyHistory(rawHistory, 3, window);
    const normalTail = mergeEnergyHistoryTail(reduced, [sampleAtOffsetMs(151_200)], window);
    const normalSample = findByOffset(normalTail, 151_200);

    expect(isEnergyHistorySegmentStart(normalSample.event_id)).toBe(false);

    const recovered = mergeEnergyHistoryTail(normalTail, [sampleAtOffsetMs(300_000)], window);
    const recovery = findByOffset(recovered, 300_000);

    expect(isEnergyHistorySegmentStart(recovery.event_id)).toBe(true);
  });

  it("relearns a faster runtime cadence from raw live deltas", () => {
    const slowHistory = [
      sampleAtOffsetMs(0),
      sampleAtOffsetMs(60_000),
      sampleAtOffsetMs(120_000),
      sampleAtOffsetMs(180_000),
      sampleAtOffsetMs(240_000),
    ];
    let live = downsampleEnergyHistory(slowHistory, 3, window);

    live = mergeEnergyHistoryTail(live, [sampleAtOffsetMs(250_000)], window);
    live = mergeEnergyHistoryTail(live, [sampleAtOffsetMs(260_000)], window);
    const recovered = mergeEnergyHistoryTail(live, [sampleAtOffsetMs(380_000)], window);
    const recovery = findByOffset(recovered, 380_000);

    expect(isEnergyHistorySegmentStart(recovery.event_id)).toBe(true);
  });

  it("uses the newer local cadence regime for retained history gaps", () => {
    const mixedCadence = [
      sampleAtOffsetMs(0),
      sampleAtOffsetMs(60_000),
      sampleAtOffsetMs(120_000),
      sampleAtOffsetMs(180_000),
      sampleAtOffsetMs(240_000),
      sampleAtOffsetMs(250_000),
      sampleAtOffsetMs(260_000),
      sampleAtOffsetMs(270_000),
      sampleAtOffsetMs(390_000),
      sampleAtOffsetMs(400_000),
      sampleAtOffsetMs(410_000),
    ];

    const reduced = downsampleEnergyHistory(mixedCadence, 240, window);
    const recovery = findByOffset(reduced, 390_000);

    expect(isEnergyHistorySegmentStart(recovery.event_id)).toBe(true);
    expect(isEnergyHistoryInferredSegmentStart(recovery.event_id)).toBe(false);
  });

  it("does not create retained-history gaps when cadence deliberately increases", () => {
    const increasedCadence = [
      sampleAtOffsetMs(0),
      sampleAtOffsetMs(10_000),
      sampleAtOffsetMs(20_000),
      sampleAtOffsetMs(30_000),
      sampleAtOffsetMs(40_000),
      sampleAtOffsetMs(100_000),
      sampleAtOffsetMs(160_000),
      sampleAtOffsetMs(220_000),
    ];

    const reduced = downsampleEnergyHistory(increasedCadence, 240, window);

    expect(reduced.some((sample) => isEnergyHistorySegmentStart(sample.event_id))).toBe(false);
  });

  it("reconciles tentative live gaps after a deliberate cadence increase", () => {
    const fastHistory = [
      sampleAtOffsetMs(0),
      sampleAtOffsetMs(10_000),
      sampleAtOffsetMs(20_000),
      sampleAtOffsetMs(30_000),
      sampleAtOffsetMs(40_000),
    ];
    const reduced = downsampleEnergyHistory(fastHistory, 240, window);
    const firstSlow = mergeEnergyHistoryTail(reduced, [sampleAtOffsetMs(100_000)], window);

    expect(isEnergyHistoryInferredSegmentStart(findByOffset(firstSlow, 100_000).event_id)).toBe(true);

    const reconciled = mergeEnergyHistoryTail(firstSlow, [sampleAtOffsetMs(160_000)], window);

    expect(isEnergyHistorySegmentStart(findByOffset(reconciled, 100_000).event_id)).toBe(false);
    expect(isEnergyHistorySegmentStart(findByOffset(reconciled, 160_000).event_id)).toBe(false);
  });

  it("keeps a genuine live outage after the next normal-cadence sample", () => {
    const fastHistory = [
      sampleAtOffsetMs(0),
      sampleAtOffsetMs(10_000),
      sampleAtOffsetMs(20_000),
      sampleAtOffsetMs(30_000),
      sampleAtOffsetMs(40_000),
    ];
    const reduced = downsampleEnergyHistory(fastHistory, 240, window);
    const recovered = mergeEnergyHistoryTail(reduced, [sampleAtOffsetMs(160_000)], window);
    const continued = mergeEnergyHistoryTail(recovered, [sampleAtOffsetMs(170_000)], window);

    expect(isEnergyHistorySegmentStart(findByOffset(continued, 160_000).event_id)).toBe(true);
    expect(isEnergyHistorySegmentStart(findByOffset(continued, 170_000).event_id)).toBe(false);
  });
});
