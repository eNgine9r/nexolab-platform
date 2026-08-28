import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import { buildEnergyCadenceAuthority } from "./energy-cadence-authority";
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

function communicationErrorAtOffsetMs(offsetMs: number): TelemetrySample {
  return {
    ...sampleAtOffsetMs(offsetMs),
    value: null,
    quality: "communication_error",
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

function cadenceAuthority(initialSeconds: number, currentSeconds: number, changedAtOffsetMs: number | null) {
  const baseMs = Date.parse("2026-08-03T10:00:00Z");
  const hasChange = changedAtOffsetMs !== null && initialSeconds !== currentSeconds;
  return buildEnergyCadenceAuthority({
    schema_version: 2,
    revision: hasChange ? 2 : 1,
    updated_at: new Date(baseMs + (changedAtOffsetMs ?? 0)).toISOString(),
    devices: [{ device_id: "le01mp-200", bus_id: "rs485-main", device_family: "le01mp", unit_id: 200 }],
    cadence: {
      family_defaults: [{ bus_id: "rs485-main", device_family: "le01mp", interval_seconds: currentSeconds }],
      device_overrides: [],
    },
    recent_audit: [
      ...(hasChange
        ? [
            {
              revision: 2,
              actor: "operator",
              reason: "cadence change",
              changed_at: new Date(baseMs + changedAtOffsetMs).toISOString(),
              changes: [
                {
                  entity: "cadence_family_default",
                  id: "rs485-main/le01mp",
                  from: String(initialSeconds),
                  to: String(currentSeconds),
                },
              ],
            },
          ]
        : []),
      {
        revision: 1,
        actor: "system:migration",
        reason: "bootstrap",
        changed_at: new Date(baseMs).toISOString(),
        changes: [
          {
            entity: "cadence_family_default",
            id: "rs485-main/le01mp",
            from: "legacy_priority_policy",
            to: String(initialSeconds),
          },
        ],
      },
    ],
  });
}

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

  it("applies faster cadence to time after a persisted reduction boundary", () => {
    const authority = cadenceAuthority(60, 10, 5_000);
    const reduced = downsampleEnergyHistory(
      [sampleAtOffsetMs(0), sampleAtOffsetMs(125_000)],
      240,
      window,
      authority,
    );
    const recovery = findByOffset(reduced, 125_000);

    expect(isEnergyHistorySegmentStart(recovery.event_id)).toBe(true);
    expect(isEnergyHistoryInferredSegmentStart(recovery.event_id)).toBe(false);
  });

  it("uses persisted faster cadence after a runtime cadence reduction", () => {
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
    const authority = cadenceAuthority(60, 10, 245_000);
    const reduced = downsampleEnergyHistory(mixedCadence, 240, window, authority);
    const recovery = findByOffset(reduced, 390_000);

    expect(isEnergyHistorySegmentStart(recovery.event_id)).toBe(true);
    expect(isEnergyHistoryInferredSegmentStart(recovery.event_id)).toBe(false);
  });

  it("uses accepted communication-error timestamps when learning acquisition cadence", () => {
    const withErrors = [
      sampleAtOffsetMs(0),
      communicationErrorAtOffsetMs(30_000),
      sampleAtOffsetMs(60_000),
      communicationErrorAtOffsetMs(90_000),
      sampleAtOffsetMs(120_000),
      sampleAtOffsetMs(240_000),
    ];

    const reduced = downsampleEnergyHistory(withErrors, 240, window);
    const recovery = findByOffset(reduced, 240_000);

    expect(isEnergyHistorySegmentStart(recovery.event_id)).toBe(true);
  });

  it("resets the source-gap budget when a persisted cadence increase reconciles scheduler deadlines", () => {
    const beforeChange = [
      sampleAtOffsetMs(0),
      sampleAtOffsetMs(10_000),
      sampleAtOffsetMs(20_000),
      sampleAtOffsetMs(30_000),
      sampleAtOffsetMs(40_000),
    ];
    const authority = cadenceAuthority(10, 60, 50_000);
    const reduced = downsampleEnergyHistory(beforeChange, 240, window, authority);
    const recovered = mergeEnergyHistoryTail(reduced, [sampleAtOffsetMs(220_000)], window, authority);

    expect(isEnergyHistorySegmentStart(findByOffset(recovered, 220_000).event_id)).toBe(false);
  });

  it("does not create retained-history gaps across a persisted cadence increase", () => {
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
    const authority = cadenceAuthority(10, 60, 50_000);
    const reduced = downsampleEnergyHistory(increasedCadence, 240, window, authority);

    expect(reduced.some((sample) => isEnergyHistorySegmentStart(sample.event_id))).toBe(false);
  });

  it("never erases tentative fallback gaps from ambiguous slower timestamps", () => {
    const unsettledHistory = [
      sampleAtOffsetMs(0),
      sampleAtOffsetMs(10_000),
      sampleAtOffsetMs(20_000),
      sampleAtOffsetMs(80_000),
    ];
    let live = downsampleEnergyHistory(unsettledHistory, 240, window);
    expect(isEnergyHistoryInferredSegmentStart(findByOffset(live, 80_000).event_id)).toBe(true);

    live = mergeEnergyHistoryTail(live, [sampleAtOffsetMs(140_000)], window);
    const continued = mergeEnergyHistoryTail(live, [sampleAtOffsetMs(200_000)], window);

    expect(isEnergyHistoryInferredSegmentStart(findByOffset(continued, 80_000).event_id)).toBe(true);
    expect(isEnergyHistoryInferredSegmentStart(findByOffset(continued, 140_000).event_id)).toBe(true);
  });

  it("uses persisted slower cadence instead of clearing fallback markers heuristically", () => {
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
    const authority = cadenceAuthority(10, 60, 50_000);
    const reconciled = downsampleEnergyHistory(increasedCadence, 240, window, authority);

    expect(isEnergyHistorySegmentStart(findByOffset(reconciled, 100_000).event_id)).toBe(false);
    expect(isEnergyHistorySegmentStart(findByOffset(reconciled, 160_000).event_id)).toBe(false);
    expect(isEnergyHistorySegmentStart(findByOffset(reconciled, 220_000).event_id)).toBe(false);
  });

  it("keeps intermittent outages when normal fast cadence resumes", () => {
    const fastHistory = [
      sampleAtOffsetMs(0),
      sampleAtOffsetMs(10_000),
      sampleAtOffsetMs(20_000),
      sampleAtOffsetMs(30_000),
      sampleAtOffsetMs(40_000),
    ];
    let live = downsampleEnergyHistory(fastHistory, 240, window);
    live = mergeEnergyHistoryTail(live, [sampleAtOffsetMs(100_000)], window);
    live = mergeEnergyHistoryTail(live, [sampleAtOffsetMs(160_000)], window);
    live = mergeEnergyHistoryTail(live, [sampleAtOffsetMs(170_000)], window);
    const resumed = mergeEnergyHistoryTail(live, [sampleAtOffsetMs(180_000)], window);

    expect(isEnergyHistoryInferredSegmentStart(findByOffset(resumed, 100_000).event_id)).toBe(true);
    expect(isEnergyHistoryInferredSegmentStart(findByOffset(resumed, 160_000).event_id)).toBe(true);
    expect(isEnergyHistorySegmentStart(findByOffset(resumed, 170_000).event_id)).toBe(false);
    expect(isEnergyHistorySegmentStart(findByOffset(resumed, 180_000).event_id)).toBe(false);
  });

  it("keeps repeated 60-second outages when 10-second cadence resumes", () => {
    const intermittent = [
      sampleAtOffsetMs(0),
      sampleAtOffsetMs(10_000),
      sampleAtOffsetMs(20_000),
      sampleAtOffsetMs(30_000),
      sampleAtOffsetMs(40_000),
      sampleAtOffsetMs(100_000),
      sampleAtOffsetMs(160_000),
      sampleAtOffsetMs(220_000),
      sampleAtOffsetMs(230_000),
      sampleAtOffsetMs(240_000),
    ];
    const reduced = downsampleEnergyHistory(intermittent, 240, window);

    expect(isEnergyHistoryInferredSegmentStart(findByOffset(reduced, 100_000).event_id)).toBe(true);
    expect(isEnergyHistoryInferredSegmentStart(findByOffset(reduced, 160_000).event_id)).toBe(true);
    expect(isEnergyHistoryInferredSegmentStart(findByOffset(reduced, 220_000).event_id)).toBe(true);
    expect(isEnergyHistorySegmentStart(findByOffset(reduced, 230_000).event_id)).toBe(false);
    expect(isEnergyHistorySegmentStart(findByOffset(reduced, 240_000).event_id)).toBe(false);
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
