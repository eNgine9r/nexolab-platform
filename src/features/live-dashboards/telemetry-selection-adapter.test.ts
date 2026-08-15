import { describe, expect, it } from "vitest";

import { telemetryPointSelectionKey } from "@/features/telemetry-selection/hierarchy";

import { createEmptyLiveDashboardDraft } from "./model";
import {
  buildLiveDashboardTelemetrySelectionModel,
  liveDashboardInventoryToTelemetryPointDescriptor,
  reconcileLiveDashboardTelemetrySelection,
} from "./telemetry-selection-adapter";
import type { LiveDashboardDraftItem, LiveDashboardInventoryItem } from "./types";

const organizationId = "organization-1";

function inventoryItem(
  channelId: string,
  overrides: Partial<LiveDashboardInventoryItem> = {},
): LiveDashboardInventoryItem {
  return {
    key: `${channelId}|temperature`,
    channel_ref_id: `ref-${channelId}`,
    node_id: "edge-01",
    equipment_id: "controller-1",
    equipment_name: "Controller 1",
    climate_chamber_id: "chamber-1",
    climate_chamber_code: "KK1",
    climate_chamber_name: "Кліматична камера 1",
    equipment_type: "temperature_controller",
    laboratory: "Лабораторія А",
    zone: "Зона 1",
    channel_id: channelId,
    channel_name: `Канал ${channelId}`,
    metric: "temperature",
    native_unit: "°C",
    source: "temperature_controller",
    quality: "valid",
    alarm: null,
    latest: null,
    ...overrides,
  };
}

function draftItem(
  channelId: string,
  overrides: Partial<LiveDashboardDraftItem> = {},
): LiveDashboardDraftItem {
  return {
    channel_id: channelId,
    metric: "temperature",
    visualization: "area",
    color: "#00C6E0",
    display_unit: "°C",
    native_unit: "°C",
    node_id: null,
    equipment_id: null,
    source: null,
    ...overrides,
  };
}

describe("Live Dashboard TelemetryPointSelector adapter", () => {
  it("maps canonical inventory identity without drifting the selector leaf key", () => {
    const item = inventoryItem("106-03");
    const descriptor = liveDashboardInventoryToTelemetryPointDescriptor(item, organizationId);

    expect(descriptor).toMatchObject({
      organizationId,
      laboratory: { id: "Лабораторія А", label: "Лабораторія А" },
      zone: { id: "Зона 1", label: "Зона 1" },
      equipmentType: { id: "temperature_controller", label: "Температурний контролер" },
      equipment: { id: "controller-1", label: "Controller 1" },
      nodeId: "edge-01",
      channelId: "106-03",
      metric: "temperature",
      unit: "°C",
    });
    expect(telemetryPointSelectionKey(descriptor)).toBe(
      ["edge-01", "controller-1", "106-03", "temperature", "°C"].map(encodeURIComponent).join("|"),
    );
  });

  it("represents missing taxonomy explicitly instead of inventing a laboratory or zone", () => {
    const model = buildLiveDashboardTelemetrySelectionModel(
      organizationId,
      [inventoryItem("106-03", { laboratory: null, zone: null })],
      [],
    );

    expect(model.hierarchy.roots[0]?.label).toBe("Лабораторія не вказана");
    expect(model.hierarchy.roots[0]?.children[0]?.label).toBe("Зона не вказана · KK1 · Кліматична камера 1");
  });

  it("preserves unresolved items and retained metadata while appending new selected points deterministically", () => {
    const first = inventoryItem("106-03");
    const second = inventoryItem("106-04");
    const unresolved = draftItem("retired-99", { color: "#AA0000" });
    const retained = draftItem("106-03", { visualization: "gauge", color: "#123456" });
    const draft = {
      ...createEmptyLiveDashboardDraft(),
      name: "Selection reconciliation",
      items: [unresolved, retained],
    };
    const model = buildLiveDashboardTelemetrySelectionModel(organizationId, [second, first], draft.items);
    const secondKey = telemetryPointSelectionKey(
      liveDashboardInventoryToTelemetryPointDescriptor(second, organizationId),
    );

    const reconciled = reconcileLiveDashboardTelemetrySelection(
      draft,
      [...model.selectedKeys, secondKey],
      organizationId,
      [second, first],
    );

    expect(reconciled.items.map((item) => item.channel_id)).toEqual(["retired-99", "106-03", "106-04"]);
    expect(reconciled.items[1]).toMatchObject({ visualization: "gauge", color: "#123456" });
    expect(reconciled.items[2]).toMatchObject({
      visualization: "line",
      native_unit: "°C",
      node_id: "edge-01",
      equipment_id: "controller-1",
    });
  });

  it("removes only explicitly deselected available points and never removes unresolved saved items", () => {
    const first = inventoryItem("106-03");
    const unresolved = draftItem("missing-01");
    const draft = {
      ...createEmptyLiveDashboardDraft(),
      items: [draftItem("106-03"), unresolved],
    };

    const reconciled = reconcileLiveDashboardTelemetrySelection(draft, [], organizationId, [first]);

    expect(reconciled.items.map((item) => item.channel_id)).toEqual(["missing-01"]);
  });
});
