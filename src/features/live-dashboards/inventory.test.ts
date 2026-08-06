import { describe, expect, it, vi } from "vitest";

import { loadLiveDashboardInventory } from "./inventory";
import type { LiveDashboardInventoryClient } from "./inventory-client";
import type { LiveDashboardInventoryItem } from "./types";

function item(
  channelId: string,
  overrides: Partial<LiveDashboardInventoryItem> = {},
): LiveDashboardInventoryItem {
  return {
    key: `${channelId}|temperature`,
    channel_ref_id: `ref-${channelId}`,
    node_id: "edge-01",
    equipment_id: "controller-1",
    equipment_name: "Controller 1",
    channel_id: channelId,
    channel_name: channelId,
    metric: "temperature",
    native_unit: "°C",
    source: "temperature_controller",
    quality: "unknown",
    alarm: null,
    latest: null,
    ...overrides,
  };
}

describe("loadLiveDashboardInventory", () => {
  it("pages the bounded catalog without using telemetry latest/history", async () => {
    const list = vi
      .fn()
      .mockResolvedValueOnce({
        items: [item("106-04")],
        total: 2,
        limit: 500,
        offset: 0,
        has_more: true,
      })
      .mockResolvedValueOnce({
        items: [item("106-03")],
        total: 2,
        limit: 500,
        offset: 1,
        has_more: false,
      });
    const client = { list } as unknown as LiveDashboardInventoryClient;

    const result = await loadLiveDashboardInventory(client);

    expect(list).toHaveBeenNthCalledWith(
      1,
      { limit: 500, offset: 0 },
      undefined,
    );
    expect(list).toHaveBeenNthCalledWith(
      2,
      { limit: 500, offset: 1 },
      undefined,
    );
    expect(result.map((entry) => entry.channel_id)).toEqual([
      "106-03",
      "106-04",
    ]);
  });

  it("fails closed when catalog pagination does not advance", async () => {
    const client = {
      list: vi.fn().mockResolvedValue({
        items: [],
        total: 1,
        limit: 500,
        offset: 0,
        has_more: true,
      }),
    } as unknown as LiveDashboardInventoryClient;

    await expect(loadLiveDashboardInventory(client)).rejects.toThrow(
      "pagination did not advance",
    );
  });
});
