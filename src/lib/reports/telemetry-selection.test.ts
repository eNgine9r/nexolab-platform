import { describe, expect, it } from "vitest";

import type { LiveDashboardInventoryItem } from "@/features/live-dashboards/types";
import type { SessionBinding } from "@/lib/sessions/types";

import {
  buildReportTelemetrySelectionModel,
  reportBindingIdsForSelection,
} from "./telemetry-selection";

function binding(overrides: Partial<SessionBinding> = {}): SessionBinding {
  return {
    id: "binding-1",
    session_id: "session-1",
    node_id: "edge-01",
    equipment_id: "K106",
    channel_id: "106-03",
    metric: "temperature.probe",
    unit: "degC",
    binding_metadata: {},
    activated_at: "2026-08-17T08:00:00Z",
    released_at: "2026-08-17T10:00:00Z",
    created_at: "2026-08-17T08:00:00Z",
    ...overrides,
  };
}

function inventory(overrides: Partial<LiveDashboardInventoryItem> = {}): LiveDashboardInventoryItem {
  return {
    key: "inventory-1",
    channel_ref_id: "channel-ref-1",
    node_id: "edge-01",
    equipment_id: "K106",
    equipment_name: "Вітрина K106",
    climate_chamber_id: "lab-1",
    climate_chamber_code: "LAB-1",
    climate_chamber_name: "Лабораторія 1",
    equipment_type: "refrigerated_showcase",
    laboratory: "Лабораторія 1",
    zone: "Камера 1",
    channel_id: "106-03",
    channel_name: "Датчик 3",
    metric: "temperature.probe",
    native_unit: "degC",
    source: "modbus",
    quality: "valid",
    alarm: null,
    latest: null,
    ...overrides,
  };
}

describe("report telemetry selection adapter", () => {
  it("uses exact inventory identity for taxonomy while keeping session binding authority", () => {
    const model = buildReportTelemetrySelectionModel({
      bindings: [binding()],
      inventory: [inventory()],
      organizationId: "organization-1",
    });

    expect(model.orderedBindingIds).toEqual(["binding-1"]);
    expect(model.orderedPointKeys).toHaveLength(1);
    const root = model.hierarchy.roots[0]!;
    expect(root.label).toBe("Лабораторія 1");
    expect(reportBindingIdsForSelection(model, model.orderedPointKeys)).toEqual(["binding-1"]);
  });

  it("preserves a persisted binding that is missing from current inventory", () => {
    const model = buildReportTelemetrySelectionModel({
      bindings: [binding({ id: "binding-missing", channel_id: "106-99" })],
      inventory: [],
      organizationId: "organization-1",
    });

    expect(model.orderedBindingIds).toEqual(["binding-missing"]);
    expect(model.hierarchy.roots[0]?.label).toBe("Лабораторія не вказана");
    expect(model.hierarchy.leafCount).toBe(1);
  });

  it("does not enrich taxonomy from an inventory row with a different unit", () => {
    const model = buildReportTelemetrySelectionModel({
      bindings: [binding()],
      inventory: [inventory({ native_unit: "K" })],
      organizationId: "organization-1",
    });

    expect(model.hierarchy.roots[0]?.label).toBe("Лабораторія не вказана");
  });

  it("fails instead of silently collapsing duplicate persisted telemetry identity", () => {
    expect(() =>
      buildReportTelemetrySelectionModel({
        bindings: [binding(), binding({ id: "binding-2" })],
        inventory: [inventory()],
        organizationId: "organization-1",
      }),
    ).toThrow(/duplicate telemetry identity/i);
  });
});
