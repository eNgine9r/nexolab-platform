import { describe, expect, it } from "vitest";

import type { MeasurementChannel } from "@/features/refrigeration/climate-catalog-repository";
import type { AvailableSensor, SensorBinding } from "@/features/refrigeration/equipment-lifecycle-repository";

import {
  addChannelToConfiguration,
  attachPhysicalSensorInventory,
  availableSensorSnapPoints,
  buildStagedSensorConfiguration,
  channelTelemetryLabel,
  defaultMarkerLabel,
  refreshStagedSensorChannelMetadata,
  sensorSlotCapacity,
} from "./sensor-configuration";

function available(channelId: string, inventoryNumber?: string | null): AvailableSensor {
  return {
    channelId,
    inventoryNumber,
    metric: "temperature",
    unit: "degC",
    latestValue: 4.2,
    quality: "valid",
    capturedAt: "2026-09-10T07:00:00.000Z",
    isBound: false,
    boundEquipmentId: null,
    boundSlotKey: null,
  };
}
function catalogChannel(channelId: string, inventoryNumber: string): MeasurementChannel {
  return {
    id: `catalog-${channelId}`,
    channelId,
    sourceChannelId: channelId,
    deviceId: "dixell-106",
    controllerUnitId: 106,
    channelNumber: 3,
    logicalSensorNumber: 1,
    displayName: `K${channelId}`,
    physicalSensorCount: 1,
    physicalSensors: [
      {
        id: `physical-${inventoryNumber}`,
        sensorPosition: "A",
        inventoryNumber,
        serialNumber: null,
        calibrationStatus: "current",
        status: "active",
        version: 1,
      },
    ],
    metricType: "temperature",
    unit: "degC",
    status: "active",
  };
}
describe("sensor configuration marker identity", () => {
  it("uses physical inventory number as the deterministic default marker label", () => {
    const channel = available("106-03", "441");
    const next = addChannelToConfiguration([], channel, 48, "showcase-kk2");

    expect(defaultMarkerLabel(channel)).toBe("441");
    expect(next).toHaveLength(1);
    expect(next[0]).toMatchObject({
      id: "106-03",
      label: "441",
      slotKey: "front-01",
      side: "front",
      shelf: 1,
      position: 1,
    });
  });

  it("classifies communication errors as Offline before generic error quality", () => {
    const channel = {
      ...available("106-03", "441"),
      latestValue: null,
      quality: "communication_error",
    };

    expect(channelTelemetryLabel(channel)).toBe("Offline");
  });

  it("recovers legacy zero capacity consistently for actual placement", () => {
    expect(sensorSlotCapacity(0)).toBe(48);
    expect(sensorSlotCapacity(72)).toBe(48);

    const next = addChannelToConfiguration([], available("106-03", "441"), 0, "showcase-kk2");
    expect(next[0]).toMatchObject({ slotKey: "front-01", side: "front", shelf: 1, position: 1 });
  });

  it("offers only free deterministic snap points for newly placed sensors", () => {
    const [existing] = addChannelToConfiguration([], available("106-03", "441"), 48, "showcase-kk2");
    if (!existing) throw new Error("Expected configured sensor");

    const movedOntoNextSlot = { ...existing, x: 0.268, y: 0.21 };
    const points = availableSensorSnapPoints([movedOntoNextSlot], 0);

    expect(points).toHaveLength(46);
    expect(points).not.toContainEqual({ x: 0.138, y: 0.21 });
    expect(points).not.toContainEqual({ x: 0.268, y: 0.21 });
    expect(points[0]).toEqual({ x: 0.398, y: 0.21 });
  });

  it("refreshes channel metadata without overwriting staged layout edits", () => {
    const [existing] = addChannelToConfiguration([], available("106-03", "441"), 48, "showcase-kk2");
    if (!existing) throw new Error("Expected configured sensor");
    const staged = { ...existing, label: "Operator label", x: 0.77, y: 0.66, shelf: 3, position: 4 };
    const refreshedChannel = {
      ...available("106-03", "441"),
      latestValue: 7.5,
      capturedAt: "2026-09-10T16:45:00.000Z",
      metric: "temperature",
      unit: "degC",
    };

    const [refreshed] = refreshStagedSensorChannelMetadata([staged], [refreshedChannel]);
    expect(refreshed).toMatchObject({
      id: "106-03",
      label: "Operator label",
      x: 0.77,
      y: 0.66,
      shelf: 3,
      position: 4,
      temperatureC: 7.5,
      updatedAt: "2026-09-10T16:45:00.000Z",
    });
  });

  it("falls back to canonical channel ID when physical inventory metadata is unavailable", () => {
    const channel = available("106-04", null);
    const next = addChannelToConfiguration([], channel, 48, "showcase-kk2");

    expect(defaultMarkerLabel(channel)).toBe("106-04");
    expect(next[0]?.label).toBe("106-04");
  });

  it("enriches current-chamber channels without changing their canonical IDs", () => {
    const channels = [available("106-03"), available("106-04", "legacy")];
    const enriched = attachPhysicalSensorInventory(channels, [catalogChannel("106-03", "441")]);

    expect(enriched).toEqual([
      expect.objectContaining({ channelId: "106-03", inventoryNumber: "441" }),
      expect.objectContaining({ channelId: "106-04", inventoryNumber: "legacy" }),
    ]);
  });

  it("preserves an existing persisted marker label during load", () => {
    const binding: SensorBinding = {
      id: "binding-106-03",
      equipmentId: "showcase-kk2",
      nodeId: "edge-01",
      channelId: "106-03",
      slotKey: "front-01",
      label: "Мій маркер",
      side: "front",
      shelf: 1,
      position: 1,
      version: 1,
      boundBy: "operator",
      boundAt: "2026-09-10T07:00:00.000Z",
      unboundBy: null,
      unboundAt: null,
    };
    const loaded = buildStagedSensorConfiguration([binding], [available("106-03", "441")], []);
    expect(loaded[0]).toMatchObject({
      id: "106-03",
      label: "Мій маркер",
      slotKey: "front-01",
    });
  });
});
