import type { EquipmentRegistryAsset } from "./asset-registry";

export type EquipmentRegistrySortKey =
  "identity" | "category" | "manufacturer" | "location" | "status" | "calibration";
export type EquipmentRegistrySortDirection = "asc" | "desc";
export type EquipmentRegistryGroupMode = "none" | "chamber" | "category" | "manufacturer" | "state";
export type EquipmentRegistryRiskFilter =
  "all" | "offline" | "attention" | "calibration-risk" | "calibration-untracked";
export type EquipmentRegistryColumn = "category" | "manufacturer" | "location" | "status" | "calibration";

export type EquipmentRegistryGroup = {
  key: string;
  label: string;
  count: number;
  issueCount: number;
  assets: EquipmentRegistryAsset[];
};

export type EquipmentRegistryPage = {
  page: number;
  pageCount: number;
  pageSize: number;
  start: number;
  end: number;
  items: EquipmentRegistryAsset[];
};

export const EQUIPMENT_REGISTRY_PAGE_SIZE = 80;
export const EQUIPMENT_REGISTRY_COLUMNS: readonly EquipmentRegistryColumn[] = [
  "category",
  "manufacturer",
  "location",
  "status",
  "calibration",
];

const categoryOrder: Record<EquipmentRegistryAsset["category"], number> = {
  "refrigeration-equipment": 0,
  "temperature-controller": 1,
  "energy-meter": 2,
  "physical-sensor": 3,
};

const calibrationOrder: Record<EquipmentRegistryAsset["calibrationStatus"], number> = {
  expired: 0,
  due: 1,
  untracked: 2,
  current: 3,
  "not-applicable": 4,
};

export function sortEquipmentWorkspace(
  assets: readonly EquipmentRegistryAsset[],
  key: EquipmentRegistrySortKey,
  direction: EquipmentRegistrySortDirection,
): EquipmentRegistryAsset[] {
  const multiplier = direction === "asc" ? 1 : -1;
  return [...assets].sort((left, right) => {
    const primary = compareSortValue(left, right, key) * multiplier;
    if (primary !== 0) return primary;
    return stableIdentityCompare(left, right);
  });
}

export function filterEquipmentWorkspaceRisk(
  assets: readonly EquipmentRegistryAsset[],
  risk: EquipmentRegistryRiskFilter,
): EquipmentRegistryAsset[] {
  if (risk === "all") return [...assets];
  return assets.filter((asset) => {
    if (risk === "offline") {
      return (
        asset.connectionStatus === "disconnected" ||
        asset.healthStatus === "offline" ||
        asset.statusKeys.includes("offline")
      );
    }
    if (risk === "attention") {
      return (
        asset.healthStatus === "warning" ||
        asset.healthStatus === "alarm" ||
        asset.statusKeys.some((value) => value === "warning" || value === "alarm")
      );
    }
    if (risk === "calibration-risk")
      return asset.calibrationStatus === "due" || asset.calibrationStatus === "expired";
    return asset.calibrationStatus === "untracked";
  });
}

export function groupEquipmentWorkspace(
  assets: readonly EquipmentRegistryAsset[],
  mode: EquipmentRegistryGroupMode,
): EquipmentRegistryGroup[] {
  if (mode === "none") {
    return [createGroup("all", "Усі активи", assets)];
  }

  const grouped = new Map<string, { label: string; assets: EquipmentRegistryAsset[] }>();
  for (const asset of assets) {
    const { key, label } = groupIdentity(asset, mode);
    const current = grouped.get(key);
    if (current) current.assets.push(asset);
    else grouped.set(key, { label, assets: [asset] });
  }

  return [...grouped.entries()]
    .map(([key, value]) => createGroup(key, value.label, value.assets))
    .sort((left, right) => compareText(left.label, right.label) || compareText(left.key, right.key));
}

export function paginateEquipmentWorkspace(
  assets: readonly EquipmentRegistryAsset[],
  requestedPage: number,
  pageSize = EQUIPMENT_REGISTRY_PAGE_SIZE,
): EquipmentRegistryPage {
  const normalizedPageSize = Math.max(1, Math.floor(pageSize));
  const pageCount = Math.max(1, Math.ceil(assets.length / normalizedPageSize));
  const page = Math.min(Math.max(0, Math.floor(requestedPage)), pageCount - 1);
  const start = assets.length === 0 ? 0 : page * normalizedPageSize;
  const end = Math.min(assets.length, start + normalizedPageSize);
  return {
    page,
    pageCount,
    pageSize: normalizedPageSize,
    start,
    end,
    items: assets.slice(start, end),
  };
}

export function equipmentAssetHasIssue(asset: EquipmentRegistryAsset): boolean {
  return (
    asset.connectionStatus === "disconnected" ||
    asset.healthStatus === "offline" ||
    asset.healthStatus === "warning" ||
    asset.healthStatus === "alarm" ||
    asset.statusKeys.some((value) => value === "offline" || value === "warning" || value === "alarm") ||
    asset.calibrationStatus === "due" ||
    asset.calibrationStatus === "expired" ||
    asset.calibrationStatus === "untracked"
  );
}

export function primaryEquipmentState(asset: EquipmentRegistryAsset): string {
  return (
    asset.lifecycleStatus ?? asset.connectionStatus ?? asset.healthStatus ?? asset.catalogStatus ?? "unknown"
  );
}

function createGroup(
  key: string,
  label: string,
  assets: readonly EquipmentRegistryAsset[],
): EquipmentRegistryGroup {
  return {
    key,
    label,
    count: assets.length,
    issueCount: assets.filter(equipmentAssetHasIssue).length,
    assets: [...assets],
  };
}

function groupIdentity(
  asset: EquipmentRegistryAsset,
  mode: Exclude<EquipmentRegistryGroupMode, "none">,
): { key: string; label: string } {
  if (mode === "chamber") {
    return { key: asset.chamberId ?? "unassigned", label: asset.chamberLabel ?? "Без прив’язки до камери" };
  }
  if (mode === "manufacturer") {
    return {
      key: asset.manufacturer ?? "unknown-manufacturer",
      label: asset.manufacturer ?? "Виробник не заданий",
    };
  }
  if (mode === "category") {
    return { key: asset.category, label: categoryLabel(asset.category) };
  }
  const state = primaryEquipmentState(asset);
  return { key: state, label: stateLabel(state) };
}

function compareSortValue(
  left: EquipmentRegistryAsset,
  right: EquipmentRegistryAsset,
  key: EquipmentRegistrySortKey,
): number {
  if (key === "identity") return compareText(left.primaryIdentifier, right.primaryIdentifier);
  if (key === "category") return categoryOrder[left.category] - categoryOrder[right.category];
  if (key === "manufacturer") return compareNullable(left.manufacturer, right.manufacturer);
  if (key === "location")
    return compareNullable(
      left.chamberLabel ?? left.locationLabel,
      right.chamberLabel ?? right.locationLabel,
    );
  if (key === "calibration")
    return calibrationOrder[left.calibrationStatus] - calibrationOrder[right.calibrationStatus];
  return compareText(primaryEquipmentState(left), primaryEquipmentState(right));
}

function stableIdentityCompare(left: EquipmentRegistryAsset, right: EquipmentRegistryAsset): number {
  return (
    compareText(left.primaryIdentifier, right.primaryIdentifier) ||
    compareText(left.displayName, right.displayName) ||
    compareText(left.key, right.key)
  );
}

function compareNullable(left: string | null, right: string | null): number {
  if (left === null && right === null) return 0;
  if (left === null) return 1;
  if (right === null) return -1;
  return compareText(left, right);
}

function compareText(left: string, right: string): number {
  return left.localeCompare(right, "uk", { numeric: true, sensitivity: "base" });
}

function categoryLabel(category: EquipmentRegistryAsset["category"]): string {
  return {
    "refrigeration-equipment": "Холодильне обладнання",
    "temperature-controller": "Температурні контролери",
    "energy-meter": "Лічильники електроенергії",
    "physical-sensor": "Фізичні датчики",
  }[category];
}

function stateLabel(value: string): string {
  return (
    {
      active: "Активні",
      inactive: "Неактивні",
      maintenance: "Обслуговування",
      retired: "Виведені",
      normal: "Норма",
      warning: "Попередження",
      alarm: "Тривога",
      offline: "Офлайн",
      connected: "Підключені",
      disconnected: "Відключені",
      unknown: "Невідомий стан",
    }[value] ?? value
  );
}
