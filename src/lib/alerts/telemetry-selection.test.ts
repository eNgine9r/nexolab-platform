import { describe, expect, it } from "vitest";

import type { LiveDashboardInventoryItem } from "@/features/live-dashboards/types";

import {
  ALERT_TELEMETRY_SCOPE_MAX_POINTS,
  buildAlertTelemetrySelectionModel,
  commitAlertTelemetryScope,
} from "./telemetry-selection";

function inventoryItem(overrides: Partial<LiveDashboardInventoryItem> = {}): LiveDashboardInventoryItem {
  return {
    key: "edge-01|K106|106-03|temperature.probe|degC",
    channel_ref_id: "channel-106-03",
    node_id: "edge-01",
    equipment_id: "K106",
    equipment_name: "Dixell K106",
    climate_chamber_id: "chamber-a",
    climate_chamber_code: "A",
    climate_chamber_name: "Chamber A",
    equipment_type: "temperature_controller",
    laboratory: null,
    zone: null,
    channel_id: "106-03",
    channel_name: "Probe 3",
    metric: "temperature.probe",
    native_unit: "degC",
    source: "modbus",
    quality: "good",
    alarm: null,
    latest: null,
    ...overrides,
  };
}

describe("alert telemetry selection", () => {
  it("builds truthful unclassified taxonomy from canonical inventory", () => {
    const model = buildAlertTelemetrySelectionModel([inventoryItem()]);
    expect(model.hierarchy.leafCount).toBe(1);
    expect(model.hierarchy.roots[0]?.label).toBe("Лабораторія не вказана");
    expect(model.allPointKeys[0]).toContain("edge-01");
    expect(model.allPointKeys[0]).toContain("temperature.probe");
  });

  it("omits server scope when every canonical point is selected", () => {
    const model = buildAlertTelemetrySelectionModel([
      inventoryItem(),
      inventoryItem({
        key: "edge-02|M200|200-01|energy.active_power|W",
        channel_ref_id: "channel-200-01",
        node_id: "edge-02",
        equipment_id: "M200",
        equipment_name: "Energy M200",
        equipment_type: "energy_meter",
        channel_id: "200-01",
        channel_name: "Active power",
        metric: "energy.active_power",
        native_unit: "W",
      }),
    ]);
    const result = commitAlertTelemetryScope(model.hierarchy, model.allPointKeys);
    expect(result).toEqual({ ok: true, telemetryPoints: undefined, selectedKeys: model.allPointKeys });
  });

  it("commits a deterministic narrowed exact selection", () => {
    const model = buildAlertTelemetrySelectionModel([
      inventoryItem(),
      inventoryItem({
        key: "edge-02|M200|200-01|energy.active_power|W",
        channel_ref_id: "channel-200-01",
        node_id: "edge-02",
        equipment_id: "M200",
        equipment_name: "Energy M200",
        equipment_type: "energy_meter",
        channel_id: "200-01",
        channel_name: "Active power",
        metric: "energy.active_power",
        native_unit: "W",
      }),
    ]);
    const requested = [model.allPointKeys[1]!, model.allPointKeys[0]!];
    const result = commitAlertTelemetryScope(model.hierarchy, [requested[0]]);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.telemetryPoints).toEqual([requested[0]]);
    expect(result.selectedKeys).toEqual([requested[0]]);
  });

  it("fails closed for empty or oversized narrowed selection", () => {
    const emptyModel = buildAlertTelemetrySelectionModel([inventoryItem()]);
    expect(commitAlertTelemetryScope(emptyModel.hierarchy, [])).toMatchObject({ ok: false });

    const inventory = Array.from({ length: ALERT_TELEMETRY_SCOPE_MAX_POINTS + 2 }, (_, index) =>
      inventoryItem({
        key: `edge-01|K${index}|${index}|temperature.probe|degC`,
        channel_ref_id: `channel-${index}`,
        equipment_id: `K${index}`,
        equipment_name: `Equipment ${index}`,
        channel_id: `${index}`,
        channel_name: `Channel ${index}`,
      }),
    );
    const model = buildAlertTelemetrySelectionModel(inventory);
    const narrowed = model.allPointKeys.slice(0, ALERT_TELEMETRY_SCOPE_MAX_POINTS + 1);
    expect(commitAlertTelemetryScope(model.hierarchy, narrowed)).toMatchObject({ ok: false });
  });
});
