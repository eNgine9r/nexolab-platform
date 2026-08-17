import type { LiveDashboardInventoryItem } from "@/features/live-dashboards/types";
import {
  buildTelemetryPointHierarchy,
  telemetryPointSelectionKey,
  type TelemetryPointDescriptor,
  type TelemetryPointHierarchy,
} from "@/features/telemetry-selection/hierarchy";
import type { SessionBinding } from "@/lib/sessions/types";

export interface ReportTelemetrySelectionModel {
  hierarchy: TelemetryPointHierarchy;
  pointKeyByBindingId: ReadonlyMap<string, string>;
  bindingIdByPointKey: ReadonlyMap<string, string>;
  orderedPointKeys: string[];
  orderedBindingIds: string[];
}

const UNCLASSIFIED_LABORATORY = {
  id: "reports:unclassified-laboratory",
  label: "Лабораторія не вказана",
} as const;
const UNCLASSIFIED_ZONE = {
  id: "reports:unclassified-zone",
  label: "Зона не вказана",
} as const;
const UNCLASSIFIED_EQUIPMENT_TYPE = {
  id: "reports:unclassified-equipment-type",
  label: "Тип обладнання не вказано",
} as const;
const UNIT_NOT_SPECIFIED = "Не вказано";

function text(value: string | null | undefined): string | null {
  const normalized = value?.trim();
  return normalized ? normalized : null;
}

function inventoryIdentity(item: LiveDashboardInventoryItem): string {
  return JSON.stringify([
    item.node_id,
    item.equipment_id,
    item.channel_id,
    item.metric,
    item.native_unit,
  ]);
}

function bindingIdentity(binding: SessionBinding): string | null {
  const unit = text(binding.unit);
  if (!unit) return null;
  return JSON.stringify([
    binding.node_id,
    binding.equipment_id,
    binding.channel_id,
    binding.metric,
    unit,
  ]);
}

function compareBindings(left: SessionBinding, right: SessionBinding): number {
  const leftIdentity = [
    left.node_id,
    left.equipment_id,
    left.channel_id,
    left.metric,
    left.unit ?? "",
    left.id,
  ].join("\u0000");
  const rightIdentity = [
    right.node_id,
    right.equipment_id,
    right.channel_id,
    right.metric,
    right.unit ?? "",
    right.id,
  ].join("\u0000");
  return leftIdentity.localeCompare(rightIdentity, "uk-UA", {
    numeric: true,
    sensitivity: "base",
  });
}

function descriptorForBinding(
  binding: SessionBinding,
  inventoryItem: LiveDashboardInventoryItem | undefined,
  organizationId: string,
): TelemetryPointDescriptor {
  const laboratory = text(inventoryItem?.laboratory);
  const zone = text(inventoryItem?.zone);
  const equipmentType = text(inventoryItem?.equipment_type);
  const equipmentName = text(inventoryItem?.equipment_name) ?? binding.equipment_id;
  const channelName = text(inventoryItem?.channel_name) ?? binding.channel_id;

  return {
    organizationId,
    laboratory: laboratory
      ? { id: `reports:laboratory:${laboratory}`, label: laboratory }
      : UNCLASSIFIED_LABORATORY,
    zone: zone ? { id: `reports:zone:${zone}`, label: zone } : UNCLASSIFIED_ZONE,
    equipmentType: equipmentType
      ? { id: `reports:equipment-type:${equipmentType}`, label: equipmentType }
      : UNCLASSIFIED_EQUIPMENT_TYPE,
    equipment: {
      id: binding.equipment_id,
      label: equipmentName,
    },
    nodeId: binding.node_id,
    channelId: binding.channel_id,
    channelLabel: channelName,
    metric: binding.metric,
    metricLabel: binding.metric,
    unit: text(binding.unit) ?? UNIT_NOT_SPECIFIED,
  };
}

export function buildReportTelemetrySelectionModel({
  bindings,
  inventory,
  organizationId,
}: {
  bindings: readonly SessionBinding[];
  inventory: readonly LiveDashboardInventoryItem[];
  organizationId: string;
}): ReportTelemetrySelectionModel {
  const inventoryByIdentity = new Map(
    inventory.map((item) => [inventoryIdentity(item), item] as const),
  );
  const pointKeyByBindingId = new Map<string, string>();
  const bindingIdByPointKey = new Map<string, string>();
  const descriptors: TelemetryPointDescriptor[] = [];

  for (const binding of [...bindings].sort(compareBindings)) {
    const identity = bindingIdentity(binding);
    const descriptor = descriptorForBinding(
      binding,
      identity ? inventoryByIdentity.get(identity) : undefined,
      organizationId,
    );
    const pointKey = telemetryPointSelectionKey(descriptor);
    const existingBindingId = bindingIdByPointKey.get(pointKey);
    if (existingBindingId && existingBindingId !== binding.id) {
      throw new Error(
        `Report session contains duplicate telemetry identity for bindings ${existingBindingId} and ${binding.id}.`,
      );
    }
    descriptors.push(descriptor);
    pointKeyByBindingId.set(binding.id, pointKey);
    bindingIdByPointKey.set(pointKey, binding.id);
  }

  const hierarchy = buildTelemetryPointHierarchy(descriptors, organizationId);
  const orderedPointKeys = hierarchy.orderedLeafKeys.filter((pointKey) =>
    bindingIdByPointKey.has(pointKey),
  );
  const orderedBindingIds = orderedPointKeys.map((pointKey) => {
    const bindingId = bindingIdByPointKey.get(pointKey);
    if (!bindingId) {
      throw new Error(`Missing report binding for telemetry point ${pointKey}.`);
    }
    return bindingId;
  });

  return {
    hierarchy,
    pointKeyByBindingId,
    bindingIdByPointKey,
    orderedPointKeys,
    orderedBindingIds,
  };
}

export function reportBindingIdsForSelection(
  model: ReportTelemetrySelectionModel,
  pointKeys: readonly string[],
): string[] {
  const selected = new Set(pointKeys);
  return model.hierarchy.orderedLeafKeys.flatMap((pointKey) => {
    if (!selected.has(pointKey)) return [];
    const bindingId = model.bindingIdByPointKey.get(pointKey);
    return bindingId ? [bindingId] : [];
  });
}
