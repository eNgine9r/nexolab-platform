import type { RefrigerationEquipment } from "@/data/refrigeration";
import type { AvailableSensor } from "@/features/refrigeration/equipment-lifecycle-repository";
import {
  buildTelemetryPointHierarchy,
  telemetryPointSelectionKey,
  type TelemetryPointDescriptor,
  type TelemetryPointHierarchy,
} from "@/features/telemetry-selection/hierarchy";

export type SensorTelemetrySelectionModel = {
  hierarchy: TelemetryPointHierarchy;
  channelIdByPointKey: ReadonlyMap<string, string>;
  pointKeyByChannelId: ReadonlyMap<string, string>;
  orderedPointKeys: string[];
};

const UNCLASSIFIED_LABORATORY = {
  id: "equipment-map:unclassified-laboratory",
  label: "Лабораторія не вказана",
} as const;
const UNCLASSIFIED_ZONE = {
  id: "equipment-map:unclassified-zone",
  label: "Зона не вказана",
} as const;
const UNCLASSIFIED_EQUIPMENT_TYPE = {
  id: "equipment-map:unclassified-equipment-type",
  label: "Тип обладнання не вказано",
} as const;

function text(value: string | null | undefined): string | null {
  const normalized = value?.trim();
  return normalized ? normalized : null;
}

function identity(prefix: string, value: string) {
  return { id: `equipment-map:${prefix}:${value}`, label: value };
}

function descriptorForChannel(
  equipment: RefrigerationEquipment,
  channel: AvailableSensor,
  organizationId: string,
): TelemetryPointDescriptor {
  const nodeId = text(equipment.transportNodeId);
  if (!nodeId) {
    throw new Error("Equipment Map telemetry selection requires a physical transport node.");
  }

  const laboratory = text(equipment.laboratory);
  const zone = text(equipment.zone);
  const equipmentType = text(equipment.type);

  return {
    organizationId,
    laboratory: laboratory ? identity("laboratory", laboratory) : UNCLASSIFIED_LABORATORY,
    zone: zone ? identity("zone", zone) : UNCLASSIFIED_ZONE,
    equipmentType: equipmentType ? identity("equipment-type", equipmentType) : UNCLASSIFIED_EQUIPMENT_TYPE,
    equipment: {
      id: equipment.id,
      label: equipment.name,
    },
    nodeId,
    channelId: channel.channelId,
    channelLabel: channel.channelId,
    metric: channel.metric,
    metricLabel: channel.metric,
    unit: channel.unit,
  };
}

export function buildSensorTelemetrySelectionModel({
  equipment,
  channels,
  organizationId,
}: {
  equipment: RefrigerationEquipment;
  channels: readonly AvailableSensor[];
  organizationId: string;
}): SensorTelemetrySelectionModel {
  const scopedOrganizationId = organizationId.trim();
  if (!scopedOrganizationId) {
    throw new Error("Equipment Map telemetry selection requires organization scope.");
  }

  const descriptors: TelemetryPointDescriptor[] = [];
  const channelIdByPointKey = new Map<string, string>();
  const pointKeyByChannelId = new Map<string, string>();

  for (const channel of channels) {
    if (pointKeyByChannelId.has(channel.channelId)) {
      throw new Error(`Equipment Map contains duplicate channel identity ${channel.channelId}.`);
    }
    const descriptor = descriptorForChannel(equipment, channel, scopedOrganizationId);
    const pointKey = telemetryPointSelectionKey(descriptor);
    const existingChannelId = channelIdByPointKey.get(pointKey);
    if (existingChannelId && existingChannelId !== channel.channelId) {
      throw new Error(
        `Equipment Map contains duplicate telemetry identity for channels ${existingChannelId} and ${channel.channelId}.`,
      );
    }
    descriptors.push(descriptor);
    channelIdByPointKey.set(pointKey, channel.channelId);
    pointKeyByChannelId.set(channel.channelId, pointKey);
  }

  const hierarchy = buildTelemetryPointHierarchy(descriptors, scopedOrganizationId);
  const orderedPointKeys = hierarchy.orderedLeafKeys.filter((pointKey) => channelIdByPointKey.has(pointKey));

  return {
    hierarchy,
    channelIdByPointKey,
    pointKeyByChannelId,
    orderedPointKeys,
  };
}

export function selectedSensorChannelId(
  model: SensorTelemetrySelectionModel,
  pointKeys: readonly string[],
): string | null {
  const selected = new Set(pointKeys);
  const canonical = model.hierarchy.orderedLeafKeys.filter(
    (pointKey) => selected.has(pointKey) && model.channelIdByPointKey.has(pointKey),
  );
  if (canonical.length !== 1) return null;
  return model.channelIdByPointKey.get(canonical[0]) ?? null;
}
