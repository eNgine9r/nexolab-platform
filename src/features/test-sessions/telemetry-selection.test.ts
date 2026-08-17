import { describe, expect, it } from "vitest";

import type { LiveDashboardInventoryItem } from "@/features/live-dashboards/types";
import type { SessionBindingOption } from "@/lib/sessions/types";

import {
  buildSessionTelemetrySelectionModel,
  resolveSelectedSessionBindings,
} from "./telemetry-selection";

function inventoryItem(
  channelId: string,
  overrides: Partial<LiveDashboardInventoryItem> = {},
): LiveDashboardInventoryItem {
  return {
    key: `${channelId}|temperature.probe`,
    channel_ref_id: `ref-${channelId}`,
    node_id: "edge-01",
    equipment_id: "K106",
    equipment_name: "K106",
    climate_chamber_id: "chamber-1",
    climate_chamber_code: "LAB-1",
    climate_chamber_name: "Laboratory 1",
    equipment_type: "temperature_controller",
    laboratory: "Laboratory 1",
    zone: "Test zone",
    channel_id: channelId,
    channel_name: `Probe ${channelId}`,
    metric: "temperature.probe",
    native_unit: "degC",
    source: "xjp",
    quality: "valid",
    alarm: null,
    latest: null,
    ...overrides,
  };
}

function bindingOption(channelId: string): SessionBindingOption {
  return {
    node_id: "edge-01",
    equipment_id: "K106",
    channel_id: channelId,
    metric: "temperature.probe",
    unit: "degC",
    device_type: "xjp",
    profile_version: "1",
    register_key: `probe-${channelId}`,
    register_address: Number(channelId.split("-")[1] ?? 0),
  };
}

describe("Test Sessions telemetry selection", () => {
  it("exposes only real inventory points that are server-authorized binding options", () => {
    const model = buildSessionTelemetrySelectionModel(
      "organization-1",
      [inventoryItem("106-03"), inventoryItem("106-99")],
      [bindingOption("106-03"), bindingOption("106-04")],
    );

    expect(model.eligibleInventoryCount).toBe(1);
    expect(model.hierarchy.orderedLeafKeys).toHaveLength(1);
    expect([...model.bindingsByPointKey.values()].map((item) => item.channel_id)).toEqual(["106-03"]);
  });

  it("requires unit identity to match the server contract", () => {
    const model = buildSessionTelemetrySelectionModel(
      "organization-1",
      [inventoryItem("106-03", { native_unit: "C" })],
      [bindingOption("106-03")],
    );

    expect(model.eligibleInventoryCount).toBe(0);
    expect(model.hierarchy.orderedLeafKeys).toEqual([]);
  });

  it("resolves selected bindings in canonical hierarchy order and ignores unknown keys", () => {
    const model = buildSessionTelemetrySelectionModel(
      "organization-1",
      [inventoryItem("106-04"), inventoryItem("106-03")],
      [bindingOption("106-04"), bindingOption("106-03")],
    );
    const selectedKeys = [...model.hierarchy.orderedLeafKeys].reverse();

    const bindings = resolveSelectedSessionBindings(model, [...selectedKeys, "unknown"]);

    expect(bindings.map((item) => item.channel_id)).toEqual(
      model.hierarchy.orderedLeafKeys.map((key) => model.bindingsByPointKey.get(key)?.channel_id),
    );
  });
});
