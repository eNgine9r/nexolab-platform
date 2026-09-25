import { describe, expect, it, vi } from "vitest";

import type { RefrigerationEquipment } from "@/data/refrigeration";
import type {
  CommissioningSession,
  SupportedDeviceProfile,
} from "@/features/equipment/commissioning-repository";
import type {
  ClimateCatalogRepository,
  ClimateChamber,
  ClimateChamberEquipment,
  MeasurementDevice,
  PhysicalSensor,
} from "@/features/refrigeration/climate-catalog-repository";
import type { RefrigerationEquipmentRepository } from "@/features/refrigeration/equipment-repository";

import {
  collectEquipmentRegistryOptions,
  type EquipmentRegistryAsset,
  defaultEquipmentRegistryFilters,
  filterEquipmentRegistry,
  isEquipmentRegistryAbort,
  loadEquipmentRegistry,
  normalizeEquipmentRegistry,
  summarizeEquipmentRegistry,
} from "./asset-registry";

const chamberOne = chamber({ id: "chamber-1", code: "KK1", name: "Кліматична камера №1", displayOrder: 1 });
const chamberTwo = chamber({ id: "chamber-2", code: "KK2", name: "Кліматична камера №2", displayOrder: 2 });

const controller = device({
  id: "device-controller-1",
  businessKey: "xjp60d:01",
  deviceType: "temperature_controller",
  displayName: "Контролер 01",
  designation: null,
  connectionStatus: "connected",
});
const energyMeter = device({
  id: "device-energy-1",
  businessKey: "le01mp:1",
  deviceType: "energy_meter",
  displayName: "Лічильник 1",
  designation: "В1",
  connectionStatus: "disconnected",
  manufacturer: "TOMZN",
  model: "LE-01MP",
});
const sensorCurrent = physicalSensor({
  id: "sensor-current",
  inventoryNumber: "106-03",
  calibrationStatus: "current",
  sensorPosition: "A",
});
const sensorExpired = physicalSensor({
  id: "sensor-expired",
  inventoryNumber: "106-04",
  calibrationStatus: "expired",
  sensorPosition: "B",
  serialNumber: "SN-106-04",
});

const chamberOneCatalog: ClimateChamberEquipment = {
  climateChamber: chamberOne,
  temperatureControllers: [controller],
  temperatureChannels: [
    {
      id: "channel-row-1",
      channelId: "xjp60d:01:ch1",
      sourceChannelId: "xjp60d:01:ch1",
      deviceId: controller.id,
      controllerUnitId: 1,
      channelNumber: 1,
      logicalSensorNumber: 1,
      displayName: "Канал 1",
      physicalSensorCount: 2,
      physicalSensors: [sensorCurrent, sensorExpired],
      metricType: "temperature",
      unit: "degC",
      status: "active",
    },
  ],
  energyMeters: [energyMeter],
  energyMeterEmptyMessage: null,
};

const refrigeration = refrigerationEquipment({
  id: "equipment-1",
  code: "REF-01",
  name: "Холодильна вітрина 1",
  lifecycleStatus: "maintenance",
  status: "warning",
  climateChamberId: chamberOne.id,
  nodeId: chamberOne.id,
});

describe("equipment asset registry", () => {
  it("normalizes all supported asset classes without fabricating metrology fields", () => {
    const assets = normalizeEquipmentRegistry([refrigeration], [chamberOne], [chamberOneCatalog]);

    expect(assets.map((asset) => asset.category)).toEqual([
      "refrigeration-equipment",
      "temperature-controller",
      "energy-meter",
      "physical-sensor",
      "physical-sensor",
    ]);
    expect(assets[0]).toMatchObject({
      primaryIdentifier: "REF-01",
      chamberLabel: "KK1 · Кліматична камера №1",
      lifecycleStatus: "maintenance",
      healthStatus: "warning",
      calibrationStatus: "not-applicable",
      canonicalHref: "/refrigeration/equipment-1",
    });
    expect(assets.find((asset) => asset.primaryIdentifier === "106-04")).toMatchObject({
      serialNumber: "SN-106-04",
      calibrationStatus: "expired",
      connectionStatus: "connected",
      canonicalHref: null,
    });
    expect(assets.find((asset) => asset.primaryIdentifier === "le01mp:1")).toMatchObject({
      category: "energy-meter",
      connectionStatus: "disconnected",
      manufacturer: "TOMZN",
    });
  });

  it("projects only verified discovery-only controller sessions into the equipment registry", () => {
    const profile = discoveryOnlyProfile();
    const verified = commissioningSession({
      id: "commissioning-danfoss-35",
      lifecycle: "verified",
      targetEquipmentKey: refrigeration.id,
      profileId: profile.id,
      profileVersion: profile.version,
      unitId: 35,
      nodeId: "nexolab-edge-01",
      busId: "rs485-commissioning-a10q2si7",
      stableTransportIdentifier: "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A10Q2SI7-if00-port0",
    });
    const draft = commissioningSession({
      id: "commissioning-draft",
      lifecycle: "ready_for_preflight",
      targetEquipmentKey: refrigeration.id,
      profileId: profile.id,
    });
    const activatableProfile = { ...profile, id: "embraco-sync-v1", activationSupported: true };
    const activatable = commissioningSession({
      id: "commissioning-embraco",
      lifecycle: "verified",
      targetEquipmentKey: refrigeration.id,
      profileId: activatableProfile.id,
    });

    const assets = normalizeEquipmentRegistry(
      [refrigeration],
      [chamberOne],
      [chamberOneCatalog],
      [verified, draft, activatable],
      [profile, activatableProfile],
    );

    const commissioned = assets.find((asset) => asset.key === "commissioning:commissioning-danfoss-35");
    expect(commissioned).toMatchObject({
      category: "temperature-controller",
      primaryIdentifier: "akcc25:35",
      displayName: "Danfoss AK-CC25 Pro",
      manufacturer: "Danfoss",
      model: "AK-CC25 Pro",
      chamberId: chamberOne.id,
      chamberLabel: "KK1 · Кліматична камера №1",
      locationLabel: "REF-01 · Холодильна вітрина 1",
      lifecycleStatus: "verified",
      connectionStatus: "monitoring_disabled",
      catalogStatus: "discovery_only",
      canonicalHref: "/equipment/onboarding/commissioning-danfoss-35",
    });
    expect(assets.some((asset) => asset.key === "commissioning:commissioning-draft")).toBe(false);
    expect(assets.some((asset) => asset.key === "commissioning:commissioning-embraco")).toBe(false);
    expect(summarizeEquipmentRegistry(assets).measurementDevices).toBe(3);
  });

  it("derives summary counters and deterministic filter options from the same assets", () => {
    const assets = normalizeEquipmentRegistry([refrigeration], [chamberOne], [chamberOneCatalog]);

    expect(summarizeEquipmentRegistry(assets)).toEqual({
      total: 5,
      refrigerationEquipment: 1,
      measurementDevices: 2,
      physicalSensors: 2,
      calibrationRisk: 1,
      calibrationUntracked: 0,
    });
    expect(collectEquipmentRegistryOptions(assets)).toEqual({
      chambers: [{ value: "chamber-1", label: "KK1 · Кліматична камера №1" }],
      manufacturers: ["Danfoss", "TOMZN"],
      statuses: ["active", "connected", "disconnected", "maintenance", "warning"],
    });
  });

  it("combines search, category, chamber, manufacturer, status and calibration filters", () => {
    const assets = normalizeEquipmentRegistry([refrigeration], [chamberOne], [chamberOneCatalog]);
    const filtered = filterEquipmentRegistry(assets, {
      ...defaultEquipmentRegistryFilters(),
      search: "106-04",
      category: "physical-sensor",
      chamber: chamberOne.id,
      status: "connected",
      calibration: "expired",
    });

    expect(filtered).toHaveLength(1);
    expect(filtered[0].primaryIdentifier).toBe("106-04");

    expect(
      filterEquipmentRegistry(assets, {
        ...defaultEquipmentRegistryFilters(),
        category: "energy-meter",
        manufacturer: "TOMZN",
        status: "disconnected",
      }).map((asset) => asset.primaryIdentifier),
    ).toEqual(["le01mp:1"]);
  });

  it("loads chamber catalogs with bounded concurrency and preserves partial failures", async () => {
    const chambers = Array.from({ length: 6 }, (_, index) =>
      chamber({
        id: `chamber-${index + 1}`,
        code: `KK${index + 1}`,
        name: `Камера ${index + 1}`,
        displayOrder: index + 1,
      }),
    );
    let active = 0;
    let maxActive = 0;
    const getEquipment = vi.fn(async (chamberId: string) => {
      active += 1;
      maxActive = Math.max(maxActive, active);
      await new Promise((resolve) => setTimeout(resolve, 2));
      active -= 1;
      if (chamberId === "chamber-4") throw new Error("Камера тимчасово недоступна");
      const current = chambers.find((candidate) => candidate.id === chamberId) ?? chambers[0];
      return emptyCatalog(current);
    });

    const result = await loadEquipmentRegistry({
      equipmentRepository: {
        list: vi.fn(async () => [refrigeration]),
      } as unknown as RefrigerationEquipmentRepository,
      climateCatalogRepository: {
        listChambers: vi.fn(async () => chambers),
        getEquipment,
        updateMeasurementDevice: vi.fn(),
        updatePhysicalSensor: vi.fn(),
      } as unknown as ClimateCatalogRepository,
      concurrency: 2,
    });

    expect(maxActive).toBeLessThanOrEqual(2);
    expect(getEquipment).toHaveBeenCalledTimes(6);
    expect(result.assets).toHaveLength(1);
    expect(result.failures).toEqual([
      {
        chamberId: "chamber-4",
        chamberLabel: "KK4 · Камера 4",
        error: "Камера тимчасово недоступна",
      },
    ]);
  });

  it("publishes useful progressive results before the slowest chamber completes", async () => {
    let resolveFirst!: (value: ClimateChamberEquipment) => void;
    let resolveSecond!: (value: ClimateChamberEquipment) => void;
    const first = new Promise<ClimateChamberEquipment>((resolve) => {
      resolveFirst = resolve;
    });
    const second = new Promise<ClimateChamberEquipment>((resolve) => {
      resolveSecond = resolve;
    });
    const progress = vi.fn();

    const loading = loadEquipmentRegistry({
      equipmentRepository: {
        list: vi.fn(async () => [refrigeration]),
      } as unknown as RefrigerationEquipmentRepository,
      climateCatalogRepository: {
        listChambers: vi.fn(async () => [chamberOne, chamberTwo]),
        getEquipment: vi.fn((chamberId: string) => (chamberId === chamberOne.id ? first : second)),
        updateMeasurementDevice: vi.fn(),
        updatePhysicalSensor: vi.fn(),
      },
      concurrency: 2,
      onProgress: progress,
    });

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(progress).toHaveBeenCalled();
    expect(progress.mock.calls[0][0]).toMatchObject({ completedChambers: 0, totalChambers: 2 });
    expect(
      progress.mock.calls[0][0].assets.map((asset: EquipmentRegistryAsset) => asset.primaryIdentifier),
    ).toContain("REF-01");

    resolveFirst(chamberOneCatalog);
    await new Promise((resolve) => setTimeout(resolve, 0));
    const partial = progress.mock.calls.at(-1)?.[0];
    expect(partial).toMatchObject({ completedChambers: 1, totalChambers: 2 });
    expect(partial.assets.map((asset: EquipmentRegistryAsset) => asset.primaryIdentifier)).toContain(
      "106-04",
    );

    resolveSecond(emptyCatalog(chamberTwo));
    const result = await loading;
    expect(result.assets.map((asset) => asset.primaryIdentifier)).toContain("106-04");
    expect(progress.mock.calls.at(-1)?.[0]).toMatchObject({ completedChambers: 2, totalChambers: 2 });
  });

  it("suppresses stale results after orchestration cancellation", async () => {
    let resolveCatalog!: (value: ClimateChamberEquipment) => void;
    const pendingCatalog = new Promise<ClimateChamberEquipment>((resolve) => {
      resolveCatalog = resolve;
    });
    const controllerAbort = new AbortController();
    const loading = loadEquipmentRegistry({
      equipmentRepository: {
        list: vi.fn(async () => []),
      } as unknown as RefrigerationEquipmentRepository,
      climateCatalogRepository: {
        listChambers: vi.fn(async () => [chamberTwo]),
        getEquipment: vi.fn(() => pendingCatalog),
        updateMeasurementDevice: vi.fn(),
        updatePhysicalSensor: vi.fn(),
      },
      signal: controllerAbort.signal,
    });

    await Promise.resolve();
    controllerAbort.abort();
    resolveCatalog(emptyCatalog(chamberTwo));

    await expect(loading).rejects.toSatisfy(isEquipmentRegistryAbort);
  });
});

function chamber(overrides: Partial<ClimateChamber> = {}): ClimateChamber {
  return {
    id: "chamber-default",
    code: "KK0",
    nodeId: "chamber-default",
    transportNodeId: "edge-01",
    busId: "bus-1",
    busKey: "rs485-main-01",
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
    connectionStatus: "unknown",
    status: "active",
    measuredParameters: [{ metric: "temperature", unit: "degC" }],
    ...overrides,
    version: overrides.version ?? 1,
  };
}

function physicalSensor(overrides: Partial<PhysicalSensor> = {}): PhysicalSensor {
  return {
    id: "sensor-default",
    sensorPosition: "A",
    inventoryNumber: "INV-001",
    serialNumber: null,
    calibrationStatus: "untracked",
    status: "active",
    ...overrides,
    version: overrides.version ?? 1,
  };
}

function emptyCatalog(currentChamber: ClimateChamber): ClimateChamberEquipment {
  return {
    climateChamber: currentChamber,
    temperatureControllers: [],
    temperatureChannels: [],
    energyMeters: [],
    energyMeterEmptyMessage: null,
  };
}

function refrigerationEquipment(overrides: Partial<RefrigerationEquipment> = {}): RefrigerationEquipment {
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
    lastSeenAt: "2026-08-04T10:00:00Z",
    version: 1,
    image: null,
    sensors: [],
    ...overrides,
  };
}

function discoveryOnlyProfile(overrides: Partial<SupportedDeviceProfile> = {}): SupportedDeviceProfile {
  return {
    id: "danfoss-ak-cc25-pro",
    version: "danfoss-ak-cc25-pro-sw1.3x-fc03-v1",
    deviceFamily: "akcc25",
    deviceClass: "temperature-controller",
    manufacturer: "Danfoss",
    models: ["AK-CC25 Pro"],
    displayName: "Danfoss AK-CC25 Pro",
    transportKind: "modbus_rtu",
    capabilityStatus: "repository_supported_hardware_evidenced",
    evidenceNote: "Read-only Unit 35 evidence",
    readOnly: true,
    activationSupported: false,
    ...overrides,
  };
}

function commissioningSession(overrides: Partial<CommissioningSession> = {}): CommissioningSession {
  return {
    id: "commissioning-default",
    lifecycle: "verified",
    deviceClass: "temperature-controller",
    manufacturer: "Danfoss",
    model: "AK-CC25 Pro",
    profileId: "danfoss-ak-cc25-pro",
    profileVersion: "danfoss-ak-cc25-pro-sw1.3x-fc03-v1",
    transportKind: "modbus_rtu",
    nodeId: "nexolab-edge-01",
    busId: "rs485-commissioning",
    stableTransportIdentifier: "/dev/serial/by-id/usb-FTDI_TEST-if00-port0",
    unitId: 35,
    ipAddress: null,
    targetEquipmentKey: refrigeration.id,
    blockedReason: null,
    unsupportedReason: null,
    version: 2,
    createdBy: "operator",
    updatedBy: "operator",
    createdAt: "2026-09-24T10:00:00Z",
    updatedAt: "2026-09-24T10:05:00Z",
    cancelledAt: null,
    ...overrides,
  };
}
