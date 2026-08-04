import type { RefrigerationEquipment } from "@/data/refrigeration";
import type {
  ClimateCatalogRepository,
  ClimateChamber,
  ClimateChamberEquipment,
  MeasurementChannel,
  MeasurementDevice,
  PhysicalSensor,
} from "@/features/refrigeration/climate-catalog-repository";
import type { RefrigerationEquipmentRepository } from "@/features/refrigeration/equipment-repository";

export type EquipmentAssetCategory =
  "refrigeration-equipment" | "temperature-controller" | "energy-meter" | "physical-sensor";

export type EquipmentCalibrationStatus = "not-applicable" | "untracked" | "current" | "due" | "expired";

export type EquipmentRegistryFilters = {
  search: string;
  category: EquipmentAssetCategory | "all";
  chamber: string;
  manufacturer: string;
  status: string;
  calibration: EquipmentCalibrationStatus | "all";
};

export type EquipmentRegistryCommon = {
  key: string;
  id: string;
  category: EquipmentAssetCategory;
  primaryIdentifier: string;
  displayName: string;
  manufacturer: string | null;
  model: string | null;
  serialNumber: string | null;
  chamberId: string | null;
  chamberLabel: string | null;
  locationLabel: string | null;
  lifecycleStatus: string | null;
  healthStatus: string | null;
  connectionStatus: string | null;
  catalogStatus: string | null;
  calibrationStatus: EquipmentCalibrationStatus;
  statusKeys: string[];
  canonicalHref: string | null;
  searchText: string;
};

export type RefrigerationRegistryAsset = EquipmentRegistryCommon & {
  category: "refrigeration-equipment";
  source: RefrigerationEquipment;
};

export type MeasurementDeviceRegistryAsset = EquipmentRegistryCommon & {
  category: "temperature-controller" | "energy-meter";
  source: MeasurementDevice;
  chamber: ClimateChamber;
};

export type PhysicalSensorRegistryAsset = EquipmentRegistryCommon & {
  category: "physical-sensor";
  source: PhysicalSensor;
  chamber: ClimateChamber;
  channel: MeasurementChannel;
  controller: MeasurementDevice | null;
};

export type EquipmentRegistryAsset =
  RefrigerationRegistryAsset | MeasurementDeviceRegistryAsset | PhysicalSensorRegistryAsset;

export type EquipmentRegistryFailure = {
  chamberId: string;
  chamberLabel: string;
  error: string;
};

export type EquipmentRegistryLoadResult = {
  assets: EquipmentRegistryAsset[];
  failures: EquipmentRegistryFailure[];
};

export type EquipmentRegistryOptions = {
  chambers: Array<{ value: string; label: string }>;
  manufacturers: string[];
  statuses: string[];
};

export type EquipmentRegistrySummary = {
  total: number;
  refrigerationEquipment: number;
  measurementDevices: number;
  physicalSensors: number;
  calibrationRisk: number;
  calibrationUntracked: number;
};

export type LoadEquipmentRegistryOptions = {
  equipmentRepository: RefrigerationEquipmentRepository;
  climateCatalogRepository: ClimateCatalogRepository;
  concurrency?: number;
  signal?: AbortSignal;
};

const DEFAULT_CONCURRENCY = 4;
const MAX_CONCURRENCY = 8;
const categoryOrder: Record<EquipmentAssetCategory, number> = {
  "refrigeration-equipment": 0,
  "temperature-controller": 1,
  "energy-meter": 2,
  "physical-sensor": 3,
};

export function defaultEquipmentRegistryFilters(): EquipmentRegistryFilters {
  return {
    search: "",
    category: "all",
    chamber: "all",
    manufacturer: "all",
    status: "all",
    calibration: "all",
  };
}

export async function loadEquipmentRegistry({
  equipmentRepository,
  climateCatalogRepository,
  concurrency = DEFAULT_CONCURRENCY,
  signal,
}: LoadEquipmentRegistryOptions): Promise<EquipmentRegistryLoadResult> {
  throwIfAborted(signal);
  const [refrigerationEquipment, chambers] = await Promise.all([
    equipmentRepository.list(),
    climateCatalogRepository.listChambers(),
  ]);
  throwIfAborted(signal);

  const sortedChambers = [...chambers].sort(compareChambers);
  const catalogs = new Array<ClimateChamberEquipment | null>(sortedChambers.length).fill(null);
  const failures = new Array<EquipmentRegistryFailure | null>(sortedChambers.length).fill(null);
  const workerCount = Math.min(normalizeConcurrency(concurrency), Math.max(1, sortedChambers.length));
  let nextIndex = 0;

  async function worker(): Promise<void> {
    while (true) {
      throwIfAborted(signal);
      const index = nextIndex;
      nextIndex += 1;
      if (index >= sortedChambers.length) return;

      const chamber = sortedChambers[index];
      try {
        catalogs[index] = await climateCatalogRepository.getEquipment(chamber.id);
      } catch (error) {
        failures[index] = {
          chamberId: chamber.id,
          chamberLabel: chamberDisplayLabel(chamber),
          error: registryErrorMessage(error),
        };
      }
      throwIfAborted(signal);
    }
  }

  await Promise.all(Array.from({ length: workerCount }, () => worker()));
  throwIfAborted(signal);

  return {
    assets: normalizeEquipmentRegistry(
      refrigerationEquipment,
      sortedChambers,
      catalogs.filter((catalog): catalog is ClimateChamberEquipment => catalog !== null),
    ),
    failures: failures.filter((failure): failure is EquipmentRegistryFailure => failure !== null),
  };
}

export function normalizeEquipmentRegistry(
  refrigerationEquipment: readonly RefrigerationEquipment[],
  chambers: readonly ClimateChamber[],
  climateCatalogs: readonly ClimateChamberEquipment[],
): EquipmentRegistryAsset[] {
  const chamberById = new Map(chambers.map((chamber) => [chamber.id, chamber] as const));
  const assets: EquipmentRegistryAsset[] = refrigerationEquipment.map((equipment) =>
    normalizeRefrigerationAsset(equipment, chamberById.get(equipment.climateChamberId ?? "") ?? null),
  );

  for (const catalog of climateCatalogs) {
    const chamber = catalog.climateChamber;
    const deviceById = new Map(
      [...catalog.temperatureControllers, ...catalog.energyMeters].map(
        (device) => [device.id, device] as const,
      ),
    );

    for (const device of catalog.temperatureControllers) {
      assets.push(normalizeDeviceAsset(device, chamber, "temperature-controller"));
    }
    for (const device of catalog.energyMeters) {
      assets.push(normalizeDeviceAsset(device, chamber, "energy-meter"));
    }
    for (const channel of catalog.temperatureChannels) {
      for (const sensor of channel.physicalSensors) {
        assets.push(
          normalizePhysicalSensorAsset(sensor, channel, chamber, deviceById.get(channel.deviceId) ?? null),
        );
      }
    }
  }

  return sortEquipmentRegistry(assets);
}

export function sortEquipmentRegistry(assets: readonly EquipmentRegistryAsset[]): EquipmentRegistryAsset[] {
  return [...assets].sort((left, right) => {
    const category = categoryOrder[left.category] - categoryOrder[right.category];
    if (category !== 0) return category;
    const identifier = compareText(left.primaryIdentifier, right.primaryIdentifier);
    return identifier === 0 ? compareText(left.displayName, right.displayName) : identifier;
  });
}

export function filterEquipmentRegistry(
  assets: readonly EquipmentRegistryAsset[],
  filters: EquipmentRegistryFilters,
): EquipmentRegistryAsset[] {
  const search = normalizeSearch(filters.search);
  return sortEquipmentRegistry(
    assets.filter((asset) => {
      return (
        (!search || asset.searchText.includes(search)) &&
        (filters.category === "all" || asset.category === filters.category) &&
        (filters.chamber === "all" || asset.chamberId === filters.chamber) &&
        (filters.manufacturer === "all" || asset.manufacturer === filters.manufacturer) &&
        (filters.status === "all" || asset.statusKeys.includes(filters.status)) &&
        (filters.calibration === "all" || asset.calibrationStatus === filters.calibration)
      );
    }),
  );
}

export function collectEquipmentRegistryOptions(
  assets: readonly EquipmentRegistryAsset[],
): EquipmentRegistryOptions {
  const chamberLabels = new Map<string, string>();
  for (const asset of assets) {
    if (asset.chamberId && asset.chamberLabel) chamberLabels.set(asset.chamberId, asset.chamberLabel);
  }
  return {
    chambers: [...chamberLabels.entries()]
      .map(([value, label]) => ({ value, label }))
      .sort((left, right) => compareText(left.label, right.label)),
    manufacturers: uniqueSorted(assets.map((asset) => asset.manufacturer)),
    statuses: uniqueSorted(assets.flatMap((asset) => asset.statusKeys)),
  };
}

export function summarizeEquipmentRegistry(
  assets: readonly EquipmentRegistryAsset[],
): EquipmentRegistrySummary {
  return {
    total: assets.length,
    refrigerationEquipment: assets.filter((asset) => asset.category === "refrigeration-equipment").length,
    measurementDevices: assets.filter(
      (asset) => asset.category === "temperature-controller" || asset.category === "energy-meter",
    ).length,
    physicalSensors: assets.filter((asset) => asset.category === "physical-sensor").length,
    calibrationRisk: assets.filter(
      (asset) => asset.calibrationStatus === "due" || asset.calibrationStatus === "expired",
    ).length,
    calibrationUntracked: assets.filter((asset) => asset.calibrationStatus === "untracked").length,
  };
}

export function isEquipmentRegistryAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function chamberDisplayLabel(chamber: ClimateChamber): string {
  return `${chamber.code} · ${chamber.name}`;
}

function normalizeRefrigerationAsset(
  equipment: RefrigerationEquipment,
  chamber: ClimateChamber | null,
): RefrigerationRegistryAsset {
  const chamberLabel = chamber ? chamberDisplayLabel(chamber) : equipment.climateChamberId;
  const locationLabel = joinDefined([equipment.laboratory, equipment.zone, equipment.location]);
  const searchText = searchable([
    equipment.code,
    equipment.name,
    equipment.location,
    equipment.laboratory,
    equipment.zone,
    equipment.type,
    equipment.manufacturer,
    equipment.model,
    equipment.serialNumber,
    equipment.temperatureClass,
    chamberLabel,
  ]);
  return {
    key: `refrigeration:${equipment.id}`,
    id: equipment.id,
    category: "refrigeration-equipment",
    primaryIdentifier: equipment.code,
    displayName: equipment.name,
    manufacturer: equipment.manufacturer,
    model: equipment.model,
    serialNumber: equipment.serialNumber,
    chamberId: equipment.climateChamberId,
    chamberLabel,
    locationLabel,
    lifecycleStatus: equipment.lifecycleStatus,
    healthStatus: equipment.status,
    connectionStatus: null,
    catalogStatus: null,
    calibrationStatus: "not-applicable",
    statusKeys: uniqueValues([equipment.lifecycleStatus, equipment.status]),
    canonicalHref: `/refrigeration/${encodeURIComponent(equipment.id)}`,
    searchText,
    source: equipment,
  };
}

function normalizeDeviceAsset(
  device: MeasurementDevice,
  chamber: ClimateChamber,
  category: "temperature-controller" | "energy-meter",
): MeasurementDeviceRegistryAsset {
  const chamberLabel = chamberDisplayLabel(chamber);
  const measuredParameters = device.measuredParameters
    .map((parameter) => `${parameter.metric} ${parameter.unit}`)
    .join(" ");
  return {
    key: `device:${device.id}`,
    id: device.id,
    category,
    primaryIdentifier: device.businessKey,
    displayName: device.displayName,
    manufacturer: device.manufacturer,
    model: device.model,
    serialNumber: null,
    chamberId: chamber.id,
    chamberLabel,
    locationLabel: chamberLabel,
    lifecycleStatus: null,
    healthStatus: null,
    connectionStatus: device.connectionStatus,
    catalogStatus: device.status,
    calibrationStatus: "not-applicable",
    statusKeys: uniqueValues([device.status, device.connectionStatus]),
    canonicalHref: null,
    searchText: searchable([
      device.businessKey,
      device.displayName,
      device.designation,
      device.manufacturer,
      device.model,
      String(device.unitId),
      measuredParameters,
      chamberLabel,
    ]),
    source: device,
    chamber,
  };
}

function normalizePhysicalSensorAsset(
  sensor: PhysicalSensor,
  channel: MeasurementChannel,
  chamber: ClimateChamber,
  controller: MeasurementDevice | null,
): PhysicalSensorRegistryAsset {
  const chamberLabel = chamberDisplayLabel(chamber);
  return {
    key: `sensor:${sensor.id}`,
    id: sensor.id,
    category: "physical-sensor",
    primaryIdentifier: sensor.inventoryNumber,
    displayName: `${channel.displayName} · ${sensor.sensorPosition}`,
    manufacturer: null,
    model: null,
    serialNumber: sensor.serialNumber,
    chamberId: chamber.id,
    chamberLabel,
    locationLabel: `${chamberLabel} · ${channel.displayName}`,
    lifecycleStatus: null,
    healthStatus: null,
    connectionStatus: controller?.connectionStatus ?? null,
    catalogStatus: sensor.status,
    calibrationStatus: sensor.calibrationStatus,
    statusKeys: uniqueValues([sensor.status, controller?.connectionStatus]),
    canonicalHref: null,
    searchText: searchable([
      sensor.inventoryNumber,
      sensor.serialNumber,
      sensor.sensorPosition,
      channel.channelId,
      channel.sourceChannelId,
      channel.displayName,
      channel.metricType,
      channel.unit,
      controller?.businessKey,
      controller?.displayName,
      chamberLabel,
    ]),
    source: sensor,
    chamber,
    channel,
    controller,
  };
}

function normalizeConcurrency(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_CONCURRENCY;
  return Math.min(MAX_CONCURRENCY, Math.max(1, Math.floor(value)));
}

function throwIfAborted(signal: AbortSignal | undefined): void {
  if (signal?.aborted) throw new DOMException("Equipment registry load aborted", "AbortError");
}

function compareChambers(left: ClimateChamber, right: ClimateChamber): number {
  return left.displayOrder - right.displayOrder || compareText(left.code, right.code);
}

function registryErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Каталог обладнання камери недоступний.";
}

function uniqueSorted(values: readonly (string | null)[]): string[] {
  return uniqueValues(values).sort(compareText);
}

function uniqueValues(values: readonly (string | null | undefined)[]): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value?.trim())))];
}

function joinDefined(values: readonly (string | null | undefined)[]): string | null {
  const normalized = values.filter((value): value is string => Boolean(value?.trim()));
  return normalized.length > 0 ? normalized.join(" · ") : null;
}

function searchable(values: readonly (string | null | undefined)[]): string {
  return normalizeSearch(values.filter(Boolean).join(" "));
}

function compareText(left: string, right: string): number {
  return left.localeCompare(right, "uk", { numeric: true, sensitivity: "base" });
}

function normalizeSearch(value: string): string {
  return value.trim().toLocaleLowerCase("uk");
}
