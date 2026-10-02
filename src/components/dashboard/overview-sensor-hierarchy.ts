import type { ClimateChamberEquipment } from "@/features/refrigeration/climate-catalog-repository";

export type OverviewSensor = { channelId: string; label: string };
export type OverviewGroup = {
  id: string;
  label: string;
  sensors: OverviewSensor[];
  children?: OverviewGroup[];
};

export function buildOverviewSensorHierarchy(
  channelIds: readonly string[],
  nodeId: string | null,
  catalog: readonly ClimateChamberEquipment[],
): OverviewGroup[] {
  const cameras = new Map<string, OverviewGroup>();
  for (const channelId of new Set(channelIds)) {
    const candidates = catalog.flatMap((equipment) => {
      if (!nodeId || equipment.climateChamber.transportNodeId !== nodeId) return [];
      return equipment.temperatureChannels
        .filter((channel) => channel.sourceChannelId === channelId)
        .map((channel) => {
          const devices = equipment.temperatureControllers.filter(
            (device) => device.id === channel.deviceId && device.unitId === channel.controllerUnitId,
          );
          return { equipment, channel, device: devices.length === 1 ? devices[0] : undefined };
        });
    });
    const match = candidates.length === 1 && candidates[0]?.device ? candidates[0] : undefined;
    const cameraId = match?.equipment.climateChamber.id ?? "unconfirmed";
    let camera = cameras.get(cameraId);
    if (!camera) {
      camera = {
        id: cameraId,
        label: match?.equipment.climateChamber.name ?? "Прив’язку до камери не підтверджено",
        sensors: [],
        children: [],
      };
      cameras.set(cameraId, camera);
    }
    const deviceId = match?.device?.id ?? "unconfirmed";
    let device = camera.children!.find((item) => item.id === deviceId);
    if (!device) {
      device = { id: deviceId, label: match?.device?.displayName ?? "Прилад не визначено", sensors: [] };
      camera.children!.push(device);
    }
    const sensor = { channelId, label: match?.channel.displayName ?? channelId };
    device.sensors.push(sensor);
    camera.sensors.push(sensor);
  }
  return [...cameras.values()];
}
