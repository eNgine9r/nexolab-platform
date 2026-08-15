import {
  buildTelemetryPointHierarchy,
  telemetryPointSelectionKey,
  type TelemetryPointDescriptor,
  type TelemetryPointHierarchy,
} from "@/features/telemetry-selection/hierarchy";

import { addDashboardDraftItem, dashboardItemIdentity } from "./model";
import type { LiveDashboardDraft, LiveDashboardDraftItem, LiveDashboardInventoryItem } from "./types";

const UNCLASSIFIED_LABORATORY_ID = "__unclassified_laboratory__";
const UNCLASSIFIED_ZONE_PREFIX = "__unclassified_zone__";

const EQUIPMENT_TYPE_LABELS: Readonly<Record<string, string>> = {
  temperature_controller: "Температурний контролер",
  energy_meter: "Лічильник енергії",
};

export type LiveDashboardTelemetrySelectionModel = {
  hierarchy: TelemetryPointHierarchy;
  selectedKeys: string[];
  unresolvedItems: LiveDashboardDraftItem[];
  inventoryIdentities: ReadonlySet<string>;
  inventoryByPointKey: ReadonlyMap<string, LiveDashboardInventoryItem>;
};

function textIdentity(value: string): { id: string; label: string } {
  return { id: value, label: value };
}

export function liveDashboardInventoryToTelemetryPointDescriptor(
  item: LiveDashboardInventoryItem,
  organizationId: string,
): TelemetryPointDescriptor {
  const laboratory = item.laboratory?.trim();
  const zone = item.zone?.trim();
  return {
    organizationId,
    laboratory: laboratory
      ? textIdentity(laboratory)
      : { id: UNCLASSIFIED_LABORATORY_ID, label: "Лабораторія не вказана" },
    zone: zone
      ? textIdentity(zone)
      : {
          id: `${UNCLASSIFIED_ZONE_PREFIX}:${item.climate_chamber_id}`,
          label: `Зона не вказана · ${item.climate_chamber_code} · ${item.climate_chamber_name}`,
        },
    equipmentType: {
      id: item.equipment_type,
      label: EQUIPMENT_TYPE_LABELS[item.equipment_type] ?? item.equipment_type,
    },
    equipment: { id: item.equipment_id, label: item.equipment_name },
    nodeId: item.node_id,
    channelId: item.channel_id,
    channelLabel: item.channel_name,
    metric: item.metric,
    metricLabel: item.metric,
    unit: item.native_unit,
  };
}

export function buildLiveDashboardTelemetrySelectionModel(
  organizationId: string,
  inventory: readonly LiveDashboardInventoryItem[],
  draftItems: readonly LiveDashboardDraftItem[],
): LiveDashboardTelemetrySelectionModel {
  const descriptors = inventory.map((item) =>
    liveDashboardInventoryToTelemetryPointDescriptor(item, organizationId),
  );
  const hierarchy = buildTelemetryPointHierarchy(descriptors, organizationId);
  const inventoryByIdentity = new Map<string, LiveDashboardInventoryItem>();
  const inventoryByPointKey = new Map<string, LiveDashboardInventoryItem>();

  for (let index = 0; index < inventory.length; index += 1) {
    const item = inventory[index];
    const descriptor = descriptors[index];
    const identity = dashboardItemIdentity(item);
    if (!inventoryByIdentity.has(identity)) inventoryByIdentity.set(identity, item);
    const pointKey = telemetryPointSelectionKey(descriptor);
    if (!inventoryByPointKey.has(pointKey)) inventoryByPointKey.set(pointKey, item);
  }

  const selectedSet = new Set<string>();
  const unresolvedItems: LiveDashboardDraftItem[] = [];
  for (const item of draftItems) {
    const inventoryItem = inventoryByIdentity.get(dashboardItemIdentity(item));
    if (!inventoryItem) {
      unresolvedItems.push(item);
      continue;
    }
    selectedSet.add(
      telemetryPointSelectionKey(
        liveDashboardInventoryToTelemetryPointDescriptor(inventoryItem, organizationId),
      ),
    );
  }

  return {
    hierarchy,
    selectedKeys: hierarchy.orderedLeafKeys.filter((key) => selectedSet.has(key)),
    unresolvedItems,
    inventoryIdentities: new Set(inventoryByIdentity.keys()),
    inventoryByPointKey,
  };
}

export function reconcileLiveDashboardTelemetrySelection(
  draft: LiveDashboardDraft,
  selectedPointKeys: readonly string[],
  organizationId: string,
  inventory: readonly LiveDashboardInventoryItem[],
): LiveDashboardDraft {
  const model = buildLiveDashboardTelemetrySelectionModel(organizationId, inventory, draft.items);
  const requested = new Set(selectedPointKeys);
  const selectedInventoryIdentities = new Set<string>();

  for (const pointKey of model.hierarchy.orderedLeafKeys) {
    if (!requested.has(pointKey)) continue;
    const item = model.inventoryByPointKey.get(pointKey);
    if (item) selectedInventoryIdentities.add(dashboardItemIdentity(item));
  }

  let next: LiveDashboardDraft = {
    ...draft,
    items: draft.items.filter((item) => {
      const identity = dashboardItemIdentity(item);
      return !model.inventoryIdentities.has(identity) || selectedInventoryIdentities.has(identity);
    }),
  };
  const existing = new Set(next.items.map(dashboardItemIdentity));

  for (const pointKey of model.hierarchy.orderedLeafKeys) {
    if (!requested.has(pointKey)) continue;
    const item = model.inventoryByPointKey.get(pointKey);
    if (!item) continue;
    const identity = dashboardItemIdentity(item);
    if (existing.has(identity)) continue;
    const result = addDashboardDraftItem(next, item);
    next = result.draft;
    if (result.added) existing.add(identity);
  }

  return next;
}
