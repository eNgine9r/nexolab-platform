import { describe, expect, it, vi } from "vitest";

import { LiveDashboardInventoryClient } from "./inventory-client";
import { loadLiveDashboardInventory } from "./inventory";

const INVENTORY_SIZE = 162;
const QUALITIES = ["valid", "sensor_error", "communication_error", "unknown"] as const;

function inventoryItem(index: number) {
  const unit = 101 + Math.floor(index / 6);
  const channel = (index % 6) + 1;
  const channelId = `${unit}-${String(channel).padStart(2, "0")}`;
  const quality = QUALITIES[index % QUALITIES.length];
  const alarm = index % 11 === 0 ? "high" : index % 13 === 0 ? "low" : null;
  const hasLatest = index % 5 !== 0;

  return {
    channel_ref_id: `channel-ref-${index + 1}`,
    node_id: "edge-01",
    equipment_id: `K${unit}`,
    equipment_name: `Dixell XJP60D K${unit}`,
    channel_id: channelId,
    channel_name: `Sensor ${index + 1}`,
    metric: "temperature.probe",
    native_unit: "degC",
    source: "dixell-xjp60d",
    quality: hasLatest ? quality : "unknown",
    alarm: hasLatest ? alarm : null,
    latest: hasLatest
      ? {
          event_id: `event-${index + 1}`,
          node_id: "edge-01",
          equipment_id: `K${unit}`,
          channel_id: channelId,
          captured_at: "2026-08-13T05:00:00Z",
          metric: "temperature.probe",
          value: quality === "valid" ? 4 + index / 10 : null,
          unit: "degC",
          quality,
          source: "dixell-xjp60d",
          alarm,
          raw_value: quality === "valid" ? 40 + index : null,
          raw_status: quality === "valid" ? 4354 : null,
          received_at: "2026-08-13T05:00:01Z",
        }
      : null,
  };
}

describe("Raspberry Pi-sized Live Dashboard inventory", () => {
  it("parses and loads all 162 canonical channels through the dedicated inventory endpoint", async () => {
    const requests: string[] = [];
    const items = Array.from({ length: INVENTORY_SIZE }, (_, index) => inventoryItem(index));
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      requests.push(url);
      return new Response(
        JSON.stringify({
          items,
          total: INVENTORY_SIZE,
          limit: 500,
          offset: 0,
          has_more: false,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });

    const client = new LiveDashboardInventoryClient("http://127.0.0.1:8082", {
      fetch: fetchImpl,
      timeoutMs: 8_000,
    });

    const result = await loadLiveDashboardInventory(client);

    expect(result).toHaveLength(INVENTORY_SIZE);
    expect(new Set(result.map((item) => item.key))).toHaveLength(INVENTORY_SIZE);
    expect(result.some((item) => item.quality === "valid")).toBe(true);
    expect(result.some((item) => item.quality === "sensor_error")).toBe(true);
    expect(result.some((item) => item.quality === "communication_error")).toBe(true);
    expect(result.some((item) => item.quality === "unknown")).toBe(true);
    expect(result.some((item) => item.latest === null)).toBe(true);
    expect(result.some((item) => item.alarm === "high")).toBe(true);
    expect(result.some((item) => item.alarm === "low")).toBe(true);

    expect(requests).toHaveLength(1);
    expect(requests[0]).toContain("/api/v1/live-dashboards/channel-inventory?limit=500&offset=0");
    expect(requests[0]).not.toContain("/api/v1/telemetry/latest");
  });
});
