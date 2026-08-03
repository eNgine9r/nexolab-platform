import { describe, expect, it, vi } from "vitest";

import type { TelemetryAdapter, TelemetryCollectionResponse, TelemetrySample } from "@/lib/telemetry/types";

import { downsampleEnergyHistory, loadCompleteEnergyHistory } from "./energy-history";

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
  it("loads every production-node page before returning the selected window", async () => {
    const adapter = adapterWithPages([
      {
        items: [sample(3), sample(2), sample(99, 200, "edge-02")],
        count: 3,
        limit: 3,
        offset: 0,
        next_offset: 3,
      },
      {
        items: [sample(1), sample(0)],
        count: 2,
        limit: 2,
        offset: 3,
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
      2,
      expect.objectContaining({ node_id: "edge-01", offset: 3, limit: 1000 }),
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

    expect(w1).toHaveLength(4);
    expect(w2).toHaveLength(4);
    expect(w1[0].event_id).toBe("energy-edge-01-200-0");
    expect(w1.at(-1)?.event_id).toBe("energy-edge-01-200-9");
    expect(w2[0].event_id).toBe("energy-edge-01-201-0");
    expect(w2.at(-1)?.event_id).toBe("energy-edge-01-201-9");
  });

  it("rejects non-advancing pagination", async () => {
    const adapter = adapterWithPages([
      {
        items: [sample(1)],
        count: 1,
        limit: 1000,
        offset: 0,
        next_offset: 0,
      },
    ]);

    await expect(
      loadCompleteEnergyHistory(adapter, {
        nodeId: "edge-01",
        metric: "electrical.power.active",
        from: new Date("2026-08-03T09:00:00Z"),
        to: new Date("2026-08-03T11:00:00Z"),
      }),
    ).rejects.toThrow("pagination did not advance");
  });
});
