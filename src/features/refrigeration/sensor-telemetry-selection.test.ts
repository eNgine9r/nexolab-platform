import { describe, expect, it } from "vitest";

import { refrigerationEquipment } from "@/data/refrigeration";
import type { AvailableSensor } from "@/features/refrigeration/equipment-lifecycle-repository";

import { buildSensorTelemetrySelectionModel, selectedSensorChannelId } from "./sensor-telemetry-selection";

const channels: AvailableSensor[] = [
  {
    channelId: "106-03",
    metric: "temperature",
    unit: "degC",
    latestValue: 2.4,
    quality: "valid",
    capturedAt: "2026-08-18T03:00:00.000Z",
    isBound: false,
    boundEquipmentId: null,
    boundSlotKey: null,
  },
  {
    channelId: "106-04",
    metric: "temperature",
    unit: "degC",
    latestValue: null,
    quality: "planned",
    capturedAt: "2026-08-18T03:00:00.000Z",
    isBound: false,
    boundEquipmentId: null,
    boundSlotKey: null,
  },
];

const equipment = refrigerationEquipment[0];

if (!equipment) throw new Error("Refrigeration fixture is required.");

describe("equipment map telemetry selection", () => {
  it("builds canonical points from the authoritative channel set regardless of telemetry freshness", () => {
    const model = buildSensorTelemetrySelectionModel({
      equipment,
      channels,
      organizationId: "org-equipment-map",
    });

    expect(model.hierarchy.leafCount).toBe(2);
    expect(model.orderedPointKeys).toHaveLength(2);
    expect(model.pointKeyByChannelId.get("106-03")).toContain("106-03");
    expect(model.pointKeyByChannelId.get("106-04")).toContain("106-04");
    expect(selectedSensorChannelId(model, [model.pointKeyByChannelId.get("106-04") ?? ""])).toBe("106-04");
  });

  it("keeps missing layout taxonomy explicit instead of inventing metadata", () => {
    const model = buildSensorTelemetrySelectionModel({
      equipment: { ...equipment, laboratory: null, zone: null, type: "" },
      channels: [channels[0]],
      organizationId: "org-equipment-map",
    });

    expect(model.hierarchy.roots[0]?.label).toBe("Лабораторія не вказана");
    expect(model.hierarchy.roots[0]?.children[0]?.label).toBe("Зона не вказана");
    expect(model.hierarchy.orderedLeafKeys).toHaveLength(1);
  });

  it("fails closed when authoritative organization or physical transport identity is missing", () => {
    expect(() => buildSensorTelemetrySelectionModel({ equipment, channels, organizationId: "" })).toThrow(
      "organization scope",
    );

    expect(() =>
      buildSensorTelemetrySelectionModel({
        equipment: { ...equipment, transportNodeId: null },
        channels,
        organizationId: "org-equipment-map",
      }),
    ).toThrow("physical transport node");
  });

  it("rejects ambiguous duplicate channel identities before a staged map mutation can occur", () => {
    expect(() =>
      buildSensorTelemetrySelectionModel({
        equipment,
        channels: [channels[0], { ...channels[0], metric: "temperature.secondary" }],
        organizationId: "org-equipment-map",
      }),
    ).toThrow("duplicate channel identity 106-03");
  });

  it("requires exactly one canonical point for a single-placement choice", () => {
    const model = buildSensorTelemetrySelectionModel({
      equipment,
      channels,
      organizationId: "org-equipment-map",
    });

    expect(selectedSensorChannelId(model, [])).toBeNull();
    expect(selectedSensorChannelId(model, model.orderedPointKeys)).toBeNull();
    expect(selectedSensorChannelId(model, ["unknown"])).toBeNull();
  });
});
