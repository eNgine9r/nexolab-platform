import type { RefrigerationEquipment } from "@/data/refrigeration";
import type {
  CommissioningRepository,
  CommissioningSession,
  SupportedDeviceProfile,
} from "@/features/equipment/commissioning-repository";
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

export type CommissionedControllerRegistryAsset = EquipmentRegistryCommon & {
  category: "temperature-controller";
  source: CommissioningSession;
  commissioningProfile: SupportedDeviceProfile;
  targetEquipment: RefrigerationEquipment;
  chamber: ClimateChamber | null;
};

export type PhysicalSensorRegistryAsset = EquipmentRegistryCommon & {
  category: "physical-sensor";
  source: PhysicalSensor;
  chamber: ClimateChamber;
  channel: MeasurementChannel;
  controller: MeasurementDevice | null;
};

export type EquipmentRegistryAsset =
  | RefrigerationRegistryAsset
  | MeasurementDeviceRegistryAsset
  | CommissionedControllerRegistryAsset
  | PhysicalSensorRegistryAsset;

export type EquipmentRegistryFailure = {
  chamberId: string;
  chamberLabel: string;
  error: string;
};

export type EquipmentRegistryLoadResult = {
  assets: EquipmentRegistryAsset[];
  failures: EquipmentRegistryFailure[];
};

export type EquipmentRegistryLoadProgress = EquipmentRegistryLoadResult & {
  completedChambers: number;
  totalChambers: number;
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
  commissioningRepository?: CommissioningRepository | null;
  concurrency?: number;
  signal?: AbortSignal;
  onProgress?: (progress: EquipmentRegistryLoadProgress) => void;
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
  commissioningRepository = null,
  concurrency = DEFAULT_CONCURRENCY,
  signal,
  onProgress,
}: LoadEquipmentRegistryOptions): Promise<EquipmentRegistryLoadResult> {
  throwIfAborted(signal);
  const [refrigerationEquipment, chambers, commissioning] = await Promise.all([
    equipmentRepository.list(),
    climateCatalogRepository.listChambers(),
    loadCommissioningInventory(commissioningRepository, signal),
  ]);
  throwIfAborted(signal);

  const sortedChambers = [...chambers].sort(compareChambers);
  const catalogs = new Array<ClimateChamberEquipment | null>(sortedChambers.length).fill(null);
  const failures = new Array<EquipmentRegistryFailure | null>(sortedChambers.length).fill(null);
  const commissioningFailure: EquipmentRegistryFailure | null = commissioning.error
    ? {
        chamberId: "commissioning-inventory",
        chamberLabel: "Комісіоноване обладнання",
        error: commissioning.error,
      }
    : null;
  const workerCount = Math.min(normalizeConcurrency(concurrency), Math.max(1, sortedChambers.length));
  let nextIndex = 0;
  let completedChambers = 0;

  const publishProgress = () => {
    if (!onProgress || signal?.aborted) return;
    onProgress({
      assets: normalizeEquipmentRegistry(
        refrigerationEquipment,
        sortedChambers,
        catalogs.filter((catalog): catalog is ClimateChamberEquipment => catalog !== null),
        commissioning.sessions,
        commissioning.profiles,
      ),
      failures: [
        ...failures.filter((failure): failure is EquipmentRegistryFailure => failure !== null),
        ...(commissioningFailure ? [commissioningFailure] : []),
      ],
      completedChambers,
      totalChambers: sortedChambers.length,
    });
  };

  publishProgress();

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
      completedChambers += 1;
      throwIfAborted(signal);
      publishProgress();
    }
  }

  await Promise.all(Array.from({ length: workerCount }, () => worker()));
  throwIfAborted(signal);

  return {
    assets: normalizeEquipmentRegistry(
      refrigerationEquipment,
      sortedChambers,
      catalogs.filter((catalog): catalog is ClimateChamberEquipment => catalog !== null),
      commissioning.sessions,
      commissioning.profiles,
    ),
    failures: [
      ...failures.filter((failure): failure is EquipmentRegistryFailure => failure !== null),
      ...(commissioningFailure ? [commissioningFailure] : []),
    ],
  };
}

export function normalizeEquipmentRegistry(
  refrigerationEquipment: readonly RefrigerationEquipment[],
  chambers: readonly ClimateChamber[],
  climateCatalogs: readonly ClimateChamberEquipment[],
  commissioningSessions: readonly CommissioningSession[] = [],
  commissioningProfiles: readonly SupportedDeviceProfile[] = [],
): EquipmentRegistryAsset[] {
  const chamberById = new Map(chambers.map((chamber) => [chamber.id, chamber] as const));
  const assets: EquipmentRegistryAsset[] = refrigerationEquipment.map((equipment) =>
    normalizeRefrigerationAsset(equipment, chamberById.get(equipment.climateChamberId ?? "") ?? null),
  );

  const equipmentById = new Map(refrigerationEquipment.map((item) => [item.id, item] as const));
  const profileById = new Map(commissioningProfiles.map((profile) => [profile.id, profile] as const));

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

  for (const session of commissioningSessions) {
    const profile = session.profileId ? (profileById.get(session.profileId) ?? null) : null;
    const target = session.targetEquipmentKey
      ? (equipmentById.get(session.targetEquipmentKey) ?? null)
      : null;
    if (
      session.lifecycle !== "verified" ||
      session.deviceClass !== "temperature-controller" ||
      !profile ||
      profile.activationSupported ||
      !target
    )
      continue;
    assets.push(
      normalizeCommissionedControllerAsset(
        session,
        profile,
        target,
        chamberById.get(target.climateChamberId ?? "") ?? null,
      ),
    );
  }

  return sortEquipmentRegistry(assets);
}

export function isCommissionedControllerAsset(
  asset: EquipmentRegistryAsset,
): asset is CommissionedControllerRegistryAsset {
  return "commissioningProfile" in asset;
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

async function loadCommissioningInventory(
  repository: CommissioningRepository | null,
  signal: AbortSignal | undefined,
): Promise<{
  sessions: CommissioningSession[];
  profiles: SupportedDeviceProfile[];
  error: string | null;
}> {
  if (!repository) return { sessions: [], profiles: [], error: null };
  try {
    const [sessions, profiles] = await Promise.all([
      repository.listSessions(signal),
      repository.listProfiles(signal),
    ]);
    return { sessions, profiles, error: null };
  } catch (error) {
    if (isEquipmentRegistryAbort(error)) throw error;
    return { sessions: [], profiles: [], error: registryErrorMessage(error) };
  }
}

function normalizeCommissionedControllerAsset(
  session: CommissioningSession,
  profile: SupportedDeviceProfile,
  target: RefrigerationEquipment,
  chamber: ClimateChamber | null,
): CommissionedControllerRegistryAsset {
  const chamberLabel = chamber
    ? chamberDisplayLabel(chamber)
    : target.climateChamberId
      ? target.climateChamberId
      : null;
  const unitIdentity = session.unitId === null ? session.id.slice(0, 8) : String(session.unitId);
  const primaryIdentifier = `${profile.deviceFamily}:${unitIdentity}`;
  const targetLabel = `${target.code} · ${target.name}`;
  return {
    key: `commissioning:${session.id}`,
    id: session.id,
    category: "temperature-controller",
    primaryIdentifier,
    displayName: profile.displayName,
    manufacturer: session.manufacturer,
    model: session.model,
    serialNumber: null,
    chamberId: chamber?.id ?? target.climateChamberId,
    chamberLabel,
    locationLabel: targetLabel,
    lifecycleStatus: "verified",
    healthStatus: null,
    connectionStatus: "monitoring_disabled",
    catalogStatus: "discovery_only",
    calibrationStatus: "not-applicable",
    statusKeys: ["verified", "monitoring_disabled", "discovery_only"],
    canonicalHref: `/equipment/onboarding/${encodeURIComponent(session.id)}`,
    searchText: searchable([
      primaryIdentifier,
      profile.displayName,
      profile.id,
      profile.version,
      session.manufacturer,
      session.model,
      session.nodeId,
      session.busId,
      session.stableTransportIdentifier,
      session.unitId === null ? null : String(session.unitId),
      target.code,
      target.name,
      chamberLabel,
    ]),
    source: session,
    commissioningProfile: profile,
    targetEquipment: target,
    chamber,
  };
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
