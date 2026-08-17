import type { LiveDashboardInventoryItem } from "@/features/live-dashboards/types";
import { liveDashboardInventoryToTelemetryPointDescriptor } from "@/features/live-dashboards/telemetry-selection-adapter";
import {
  buildTelemetryPointHierarchy,
  telemetryPointSelectionKey,
  type TelemetryPointHierarchy,
} from "@/features/telemetry-selection/hierarchy";
import type { SessionBindingOption } from "@/lib/sessions/types";

export type SessionTelemetrySelectionModel = {
  hierarchy: TelemetryPointHierarchy;
  bindingsByPointKey: ReadonlyMap<string, SessionBindingOption>;
  eligibleInventoryCount: number;
};

function bindingIdentity(value: {
  node_id: string;
  equipment_id: string;
  channel_id: string;
  metric: string;
  unit: string;
}): string {
  return [value.node_id, value.equipment_id, value.channel_id, value.metric, value.unit]
    .map(encodeURIComponent)
    .join("|");
}

export function buildSessionTelemetrySelectionModel(
  organizationId: string,
  inventory: readonly LiveDashboardInventoryItem[],
  bindingOptions: readonly SessionBindingOption[],
): SessionTelemetrySelectionModel {
  const optionByIdentity = new Map(bindingOptions.map((option) => [bindingIdentity(option), option]));
  const eligibleInventory: LiveDashboardInventoryItem[] = [];
  const bindingsByPointKey = new Map<string, SessionBindingOption>();

  for (const item of inventory) {
    const option = optionByIdentity.get(
      bindingIdentity({
        node_id: item.node_id,
        equipment_id: item.equipment_id,
        channel_id: item.channel_id,
        metric: item.metric,
        unit: item.native_unit,
      }),
    );
    if (!option) continue;

    const descriptor = liveDashboardInventoryToTelemetryPointDescriptor(item, organizationId);
    const pointKey = telemetryPointSelectionKey(descriptor);
    if (bindingsByPointKey.has(pointKey)) continue;
    bindingsByPointKey.set(pointKey, option);
    eligibleInventory.push(item);
  }

  const hierarchy = buildTelemetryPointHierarchy(
    eligibleInventory.map((item) => liveDashboardInventoryToTelemetryPointDescriptor(item, organizationId)),
    organizationId,
  );

  return {
    hierarchy,
    bindingsByPointKey,
    eligibleInventoryCount: bindingsByPointKey.size,
  };
}

export function resolveSelectedSessionBindings(
  model: SessionTelemetrySelectionModel,
  selectedPointKeys: readonly string[],
): SessionBindingOption[] {
  const requested = new Set(selectedPointKeys);
  const bindings: SessionBindingOption[] = [];
  for (const pointKey of model.hierarchy.orderedLeafKeys) {
    if (!requested.has(pointKey)) continue;
    const binding = model.bindingsByPointKey.get(pointKey);
    if (binding) bindings.push(binding);
  }
  return bindings;
}
