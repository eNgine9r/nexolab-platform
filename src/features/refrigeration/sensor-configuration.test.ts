import { describe, expect, it } from "vitest";

import type { MeasurementChannel } from "@/features/refrigeration/climate-catalog-repository";
import type { AvailableSensor, SensorBinding } from "@/features/refrigeration/equipment-lifecycle-repository";

import {
  addChannelToConfiguration,
  attachPhysicalSensorInventory,
  buildStagedSensorConfiguration,
  defaultMarkerLabel,
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
