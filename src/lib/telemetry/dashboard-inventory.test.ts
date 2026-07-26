import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "./types";
import { deriveTelemetryInventory } from "./dashboard-inventory";

function sample(
  eventId: string,
  nodeId: string,
  equipmentId: string,
  channelId: string,
  quality: TelemetrySample["quality"] = "valid",
): TelemetrySample {
  return {
    event_id: eventId,
    node_id: nodeId,
    captured_at: `2026-07-26T07:00:0${eventId.at(-1) ?? "0"}Z`,
    metric: "temperature.probe",
    value: quality === "valid" ? 4.2 : null,
    unit: "degC",
    quality,
    source: "test",
    equipment_id: equipmentId,
    channel_id: channelId,
    alarm: null,
    raw_value: null,
    raw_status: null,
  };
}

describe("deriveTelemetryInventory", () => {
  it("groups API records by real nodes, equipment and channels", () => {
    const inventory = deriveTelemetryInventory(
      [
        sample("event-1", "edge-01", "K106", "106-03"),
        sample("event-2", "edge-01", "K106", "106-04", "sensor_error"),
        sample("event-3", "edge-02", "M200", "voltage"),
      ],
      "live",
    );

    expect(inventory.nodes).toEqual([
      expect.objectContaining({
        nodeId: "edge-01",
        state: "warning",
        equipmentCount: 1,
        channelCount: 2,
        validCount: 1,
        issueCount: 1,
      }),
      expect.objectContaining({
        nodeId: "edge-02",
        state: "online",
        equipmentCount: 1,
        channelCount: 1,
      }),
    ]);
    expect(inventory.equipment).toEqual([
      expect.objectContaining({ equipmentId: "K106", nodeId: "edge-01", channelCount: 2 }),
      expect.objectContaining({ equipmentId: "M200", nodeId: "edge-02", channelCount: 1 }),
    ]);
  });

  it("marks all discovered nodes offline when the transport is offline", () => {
    const inventory = deriveTelemetryInventory([sample("event-1", "edge-01", "K106", "106-03")], "offline");
    expect(inventory.nodes[0]?.state).toBe("offline");
  });
});
