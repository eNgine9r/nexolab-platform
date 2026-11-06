import type { ClimateChamberEquipment } from "@/features/refrigeration/climate-catalog-repository";

export type OverviewSensor = { channelId: string; label: string };
export type OverviewGroup = {
  id: string;
  label: string;
  context?: string;
  sensors: OverviewSensor[];
};

export function buildOverviewSensorHierarchy(
  channelIds: readonly string[],
  nodeId: string | null,
  catalog: readonly ClimateChamberEquipment[],
): OverviewGroup[] {
  const devices = new Map<string, OverviewGroup>();
  const contexts = new Map<string, Set<string>>();

  for (const channelId of new Set(channelIds)) {
    const candidates = catalog.flatMap((equipment) => {
      if (!nodeId || equipment.climateChamber.transportNodeId !== nodeId) return [];
      return equipment.temperatureChannels
        .filter((channel) => channel.sourceChannelId === channelId)
        .map((channel) => {
          const matches = equipment.temperatureControllers.filter(
            (device) => device.id === channel.deviceId && device.unitId === channel.controllerUnitId,
          );
          return { equipment, channel, device: matches.length === 1 ? matches[0] : undefined };
        });
    });

    // An ambiguous or missing catalog association must never fabricate a controller identity.
    const match = candidates.length === 1 && candidates[0]?.device ? candidates[0] : undefined;
    const id = match
      ? JSON.stringify([
          nodeId,
          match.equipment.climateChamber.busId,
          match.device.id,
          match.device.unitId,
        ])
      : "unconfirmed";

    let group = devices.get(id);
    if (!group) {
      group = {
        id,
        label: match?.device.displayName?.trim() || "Прилад не підтверджено",
        sensors: [],
      };
      devices.set(id, group);
    }
    group.sensors.push({
      channelId,
      label: match?.channel.displayName?.trim() || channelId,
    });

    // A chamber is optional context only; it is never required to display or select a channel.
    const chamberName = match?.equipment.climateChamber.name?.trim();
    if (chamberName) {
      const names = contexts.get(id) ?? new Set<string>();
      names.add(chamberName);
      contexts.set(id, names);
    }
  }

  for (const group of devices.values()) {
    const names = contexts.get(group.id);
    if (names?.size) group.context = [...names].sort((a, b) => a.localeCompare(b, "uk-UA")).join(" · ");
  }

  return [...devices.values()].sort((left, right) => {
    if (left.id === "unconfirmed") return 1;
    if (right.id === "unconfirmed") return -1;
    return left.label.localeCompare(right.label, "uk-UA") || left.id.localeCompare(right.id);
  });
}
