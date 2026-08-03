import { describe, expect, it, vi } from "vitest";

import type { TelemetryAdapter, TelemetryCollectionResponse, TelemetrySample } from "@/lib/telemetry/types";

import {
  downsampleEnergyHistory,
  loadCompleteEnergyHistory,
  mergeEnergyHistoryTail,
  selectEnergyHistoryTail,
} from "./energy-history";
import { isEnergyHistorySegmentStart } from "./energy-history-segment";

function sample(index: number, unitId = 200, nodeId = "edge-01"): TelemetrySample {
  return {
    event_id: `energy-${nodeId}-${unitId}-${index}`,
    node_id: nodeId,
    captured_at: new Date(Date.UTC(2026, 7, 3, 10, 0, index)).toISOString(),
    metric: "electrical.power.active",
    value: index,
    unit: "W",
    quality: "valid",
    source: "f-and-f-le-01mp",
    equipment_id: `LE01MP-${unitId}`,
    channel_id: `${unitId}-active-power`,
    alarm: null,
    raw_value: index,
    raw_status: null,
  };
}

function adapterWithPages(pages: TelemetryCollectionResponse[]): TelemetryAdapter {
  const history = vi.fn();
  for (const page of pages) history.mockResolvedValueOnce(page);

  return {
    readiness: vi.fn(),
    latest: vi.fn(),
    history,
    subscribe: vi.fn(),
  } as unknown as TelemetryAdapter;
}

describe("energy history", () => {
  it("uses an overlapping captured-at cursor instead of mutable offsets", async () => {
    const adapter = adapterWithPages([
      {
        items: [sample(3), sample(2), sample(99, 200, "edge-02")],
        count: 3,
        limit: 3,
        offset: 0,
        next_offset: 3,
      },
      {
        items: [sample(2), sample(1), sample(0)],
        count: 3,
        limit: 3,
        offset: 0,
        next_offset: null,
      },
    ]);

    const result = await loadCompleteEnergyHistory(adapter, {
      nodeId: "edge-01",
      metric: "electrical.power.active",
      from: new Date("2026-08-03T09:00:00Z"),
      to: new Date("2026-08-03T11:00:00Z"),
    });

    expect(adapter.history).toHaveBeenCalledTimes(2);
    expect(adapter.history).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ node_id: "edge-01", offset: 0, limit: 1000 }),
      undefined,
    );
    expect(adapter.history).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        node_id: "edge-01",
        offset: 0,
        limit: 1000,
        to: new Date("2026-08-03T10:00:02.001Z"),
      }),
      undefined,
    );
    expect(result.map((item) => item.event_id)).toEqual([
      "energy-edge-01-200-0",
      "energy-edge-01-200-1",
      "energy-edge-01-200-2",
      "energy-edge-01-200-3",
    ]);
  });

  it("downsamples each meter across the complete time span", () => {
    const source = [
      ...Array.from({ length: 10 }, (_, index) => sample(index, 200)),
      ...Array.from({ length: 10 }, (_, index) => sample(index, 201)),
    ];

    const result = downsampleEnergyHistory(source, 4);
    const w1 = result.filter((item) => item.equipment_id === "LE01MP-200");
    const w2 = result.filter((item) => item.equipment_id === "LE01MP-201");

    expect(w1.length).toBeLessThanOrEqual(4);
    expect(w2.length).toBeLessThanOrEqual(4);
    expect(w1[0].event_id).toBe("energy-edge-01-200-0");
    expect(w1.at(-1)?.event_id).toBe("energy-edge-01-200-9");
    expect(w2[0].event_id).toBe("energy-edge-01-201-0");
    expect(w2.at(-1)?.event_id).toBe("energy-edge-01-201-9");
  });

  it("does not let communication errors displace renderable history", () => {
    const source = [
      ...Array.from({ length: 10 }, (_, index) => ({
        ...sample(index),
        quality: "communication_error" as const,
        value: null,
      })),
      sample(20),
      sample(21),
    ];

    const result = downsampleEnergyHistory(source, 2);

    expect(result.map((item) => item.event_id)).toEqual(["energy-edge-01-200-20", "energy-edge-01-200-21"]);
  });

  it("preserves a communication-error boundary without spending a chart point on the error", () => {
    const source = [
      sample(0),
      sample(5),
      { ...sample(10), quality: "communication_error" as const, value: null },
      sample(15),
      sample(20),
    ];

    const result = downsampleEnergyHistory(source, 4);

    expect(result).toHaveLength(4);
    expect(result.some((item) => item.quality !== "valid")).toBe(false);
    expect(isEnergyHistorySegmentStart(result[2].event_id)).toBe(true);
  });

  it("carries a raw source-cadence gap through bounded downsampling", () => {
    const source = [sample(0), sample(5), sample(10), sample(50), sample(55)];

    const result = downsampleEnergyHistory(source, 4);

    expect(result.length).toBeLessThanOrEqual(4);
    expect(result.some((item) => isEnergyHistorySegmentStart(item.event_id))).toBe(true);
  });

  it("keeps absolute time buckets stable while appending the newest tail", () => {
    const window = {
      nodeId: "edge-01",
      metric: "electrical.power.active" as const,
      from: new Date("2026-08-03T10:00:00Z"),
      to: new Date("2026-08-04T10:00:00Z"),
    };
    const source = Array.from({ length: 1_440 }, (_, minute) => sample(minute * 60));
    const initial = downsampleEnergyHistory(source, 240, window);
    const merged = mergeEnergyHistoryTail(initial, [sample(86_395)], window);

    expect(initial.length).toBeLessThanOrEqual(240);
    expect(merged.length).toBeLessThanOrEqual(240);
    expect(merged.slice(0, -1).map((item) => item.event_id)).toEqual(initial.map((item) => item.event_id));
    expect(merged.at(-1)?.event_id).toBe("energy-edge-01-200-86395");
  });

  it("rejects future-skewed samples before they can advance the rolling window", () => {
    const now = Date.parse("2026-08-03T10:00:00Z");
    const accepted = selectEnergyHistoryTail(
      [
        { ...sample(0), captured_at: "2026-08-03T10:00:20Z" },
        { ...sample(1), captured_at: "2026-08-03T10:00:31Z" },
        sample(2, 200, "edge-02"),
      ],
      "edge-01",
      "electrical.power.active",
      now,
    );

    expect(accepted.map((item) => item.event_id)).toEqual(["energy-edge-01-200-0"]);
  });

  it("merges the websocket tail without retaining records outside the rolling window", () => {
    const result = mergeEnergyHistoryTail(
      [sample(0), sample(10)],
      [
        { ...sample(10), value: 999 },
        sample(11, 201),
        sample(12, 200, "edge-02"),
        { ...sample(13), metric: "electrical.voltage", unit: "V" },
      ],
      {
        nodeId: "edge-01",
        metric: "electrical.power.active",
        from: new Date("2026-08-03T10:00:05Z"),
        to: new Date("2026-08-03T10:00:15Z"),
      },
    );

    expect(result.map((item) => item.event_id)).toEqual(["energy-edge-01-200-10", "energy-edge-01-201-11"]);
    expect(result[0].value).toBe(999);
  });

  it("rejects a page that cannot provide a stable cursor", async () => {
    const invalid = { ...sample(1), captured_at: "not-a-timestamp" };
    const adapter = adapterWithPages([
      {
        items: [invalid],
        count: 1,
        limit: 1000,
        offset: 0,
        next_offset: 1,
      },
    ]);

    await expect(
      loadCompleteEnergyHistory(adapter, {
        nodeId: "edge-01",
        metric: "electrical.power.active",
        from: new Date("2026-08-03T09:00:00Z"),
        to: new Date("2026-08-03T11:00:00Z"),
      }),
    ).rejects.toThrow("stable cursor");
  });
});
