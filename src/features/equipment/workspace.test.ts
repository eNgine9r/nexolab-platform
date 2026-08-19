import { describe, expect, it } from "vitest";

import type { RefrigerationEquipment } from "@/data/refrigeration";
import type {
  ClimateChamber,
  ClimateChamberEquipment,
  MeasurementDevice,
  PhysicalSensor,
} from "@/features/refrigeration/climate-catalog-repository";

import { normalizeEquipmentRegistry } from "./asset-registry";
import {
  EQUIPMENT_REGISTRY_PAGE_SIZE,
  filterEquipmentWorkspaceRisk,
  groupEquipmentWorkspace,
  paginateEquipmentWorkspace,
  sortEquipmentWorkspace,
} from "./workspace";
import {
  DEFAULT_EQUIPMENT_WORKSPACE_COLUMNS,
  parseEquipmentWorkspaceColumns,
  serializeEquipmentWorkspaceColumns,
} from "./workspace-preferences";

const chamberOne = chamber({ id: "chamber-1", code: "KK1", name: "Камера 1" });
const controller = device({ id: "controller-1", businessKey: "xjp:1", connectionStatus: "disconnected" });
const catalog: ClimateChamberEquipment = {
  climateChamber: chamberOne,
  temperatureControllers: [controller],
  temperatureChannels: [
    {
      id: "channel-1",
      channelId: "channel-1",
      sourceChannelId: "source-1",
      deviceId: controller.id,
      controllerUnitId: 1,
      channelNumber: 1,
      logicalSensorNumber: 1,
      displayName: "Канал 1",
      physicalSensorCount: 2,
      physicalSensors: [
        sensor({ id: "sensor-due", inventoryNumber: "S-DUE", calibrationStatus: "due" }),
        sensor({ id: "sensor-untracked", inventoryNumber: "S-UNT", calibrationStatus: "untracked" }),
      ],
      metricType: "temperature",
      unit: "degC",
      status: "active",
    },
  ],
  energyMeters: [],
  energyMeterEmptyMessage: null,
};

describe("equipment workspace", () => {
  it("sorts by a requested column with a stable identity tie-breaker", () => {
    const assets = normalizeEquipmentRegistry(
      [
        refrigeration({ id: "2", code: "REF-20", name: "Beta", manufacturer: "Same" }),
        refrigeration({ id: "1", code: "REF-10", name: "Alpha", manufacturer: "Same" }),
      ],
      [chamberOne],
      [],
    );

    expect(
      sortEquipmentWorkspace(assets, "manufacturer", "asc").map((asset) => asset.primaryIdentifier),
    ).toEqual(["REF-10", "REF-20"]);
    expect(
      sortEquipmentWorkspace(assets, "identity", "desc").map((asset) => asset.primaryIdentifier),
    ).toEqual(["REF-20", "REF-10"]);
  });

  it("surfaces offline, attention and calibration risk without fabricating state", () => {
    const assets = normalizeEquipmentRegistry(
      [refrigeration({ id: "warning", code: "REF-WARN", status: "warning" })],
      [chamberOne],
      [catalog],
    );

    expect(filterEquipmentWorkspaceRisk(assets, "offline").map((asset) => asset.primaryIdentifier)).toContain(
      "xjp:1",
    );
    expect(filterEquipmentWorkspaceRisk(assets, "attention").map((asset) => asset.primaryIdentifier)).toEqual(
      ["REF-WARN"],
    );
    expect(
      filterEquipmentWorkspaceRisk(assets, "calibration-risk").map((asset) => asset.primaryIdentifier),
    ).toEqual(["S-DUE"]);
    expect(
      filterEquipmentWorkspaceRisk(assets, "calibration-untracked").map((asset) => asset.primaryIdentifier),
    ).toEqual(["S-UNT"]);
  });

  it("groups deterministically and reports issue counts per group", () => {
    const assets = normalizeEquipmentRegistry(
      [
        refrigeration({ id: "a", code: "REF-A", manufacturer: "Acme", status: "normal" }),
        refrigeration({ id: "b", code: "REF-B", manufacturer: "Acme", status: "warning" }),
      ],
      [chamberOne],
      [catalog],
    );
    const groups = groupEquipmentWorkspace(assets, "manufacturer");
    const acme = groups.find((group) => group.key === "Acme");

    expect(acme).toMatchObject({ count: 2, issueCount: 1 });
    expect(groups.map((group) => group.label)).toEqual(
      [...groups.map((group) => group.label)].sort((a, b) =>
        a.localeCompare(b, "uk", { numeric: true, sensitivity: "base" }),
      ),
    );
  });

  it("bounds large registry DOM pages to the fixed workspace page size", () => {
    const assets = normalizeEquipmentRegistry(
      Array.from({ length: 205 }, (_, index) =>
        refrigeration({ id: `asset-${index}`, code: `REF-${String(index).padStart(3, "0")}` }),
      ),
      [chamberOne],
      [],
    );

    const first = paginateEquipmentWorkspace(assets, 0);
    const last = paginateEquipmentWorkspace(assets, 99);
    expect(first.items).toHaveLength(EQUIPMENT_REGISTRY_PAGE_SIZE);
    expect(first.pageCount).toBe(3);
    expect(last.page).toBe(2);
    expect(last.items).toHaveLength(45);
  });

  it("persists only validated local column selections", () => {
    expect(
      parseEquipmentWorkspaceColumns(serializeEquipmentWorkspaceColumns(["status", "location"])),
    ).toEqual(["status", "location"]);
    expect(parseEquipmentWorkspaceColumns('["status","bogus"]')).toEqual([
      ...DEFAULT_EQUIPMENT_WORKSPACE_COLUMNS,
    ]);
    expect(parseEquipmentWorkspaceColumns("not-json")).toEqual([...DEFAULT_EQUIPMENT_WORKSPACE_COLUMNS]);
  });
});

function chamber(overrides: Partial<ClimateChamber> = {}): ClimateChamber {
  return {
    id: "chamber-default",
    code: "KK0",
    nodeId: "chamber-default",
    transportNodeId: "edge-01",
    busId: "bus-1",
    busKey: "rs485-main",
    name: "Камера",
    displayOrder: 1,
    status: "active",
    version: 1,
    createdAt: "2026-08-01T00:00:00Z",
    updatedAt: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

function device(overrides: Partial<MeasurementDevice> = {}): MeasurementDevice {
  return {
    id: "device-default",
    businessKey: "device:1",
    deviceType: "temperature_controller",
    manufacturer: "Danfoss",
    model: "XJP60D",
    unitId: 1,
    displayName: "Контролер",
    designation: null,
    connectionStatus: "connected",
    status: "active",
    measuredParameters: [{ metric: "temperature", unit: "degC" }],
    ...overrides,
  };
}

function sensor(overrides: Partial<PhysicalSensor> = {}): PhysicalSensor {
  return {
    id: "sensor-default",
    sensorPosition: "A",
    inventoryNumber: "INV-1",
    serialNumber: null,
    calibrationStatus: "current",
    status: "active",
    ...overrides,
  };
}

function refrigeration(overrides: Partial<RefrigerationEquipment> = {}): RefrigerationEquipment {
  return {
    id: "equipment-default",
    code: "REF-00",
    name: "Холодильна вітрина",
    location: "Лабораторія",
    laboratory: "Лабораторія 1",
    zone: "Зона A",
    climateChamberId: chamberOne.id,
    nodeId: chamberOne.id,
    transportNodeId: "edge-01",
    type: "Холодильна вітрина",
    manufacturer: "Danfoss",
    model: "REF-X",
    serialNumber: "REF-SN-1",
    temperatureClass: "M1",
    installedAt: "2026-01-01",
    servicedAt: "2026-07-01",
    lifecycleStatus: "active",
    status: "normal",
    averageTemperatureC: 4,
    minTemperatureC: 2,
    maxTemperatureC: 6,
    onlineSensors: 2,
    totalSensors: 2,
    activeAlarms: 0,
    lastSeenAt: "2026-08-19T10:00:00Z",
    version: 1,
    image: null,
    sensors: [],
    ...overrides,
  };
}
