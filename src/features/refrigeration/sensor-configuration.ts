import type { RefrigerationSensor, SensorSide, SensorStatus } from "@/data/refrigeration";
import type {
  AvailableSensor,
  SensorBinding,
  SensorConfigurationItem,
} from "@/features/refrigeration/equipment-lifecycle-repository";
import type { LayoutPlacement } from "@/features/refrigeration/layout-editor";

export type StagedSensorConfiguration = RefrigerationSensor & {
  slotKey: string;
  metric: string;
  unit: string;
};

export function buildStagedSensorConfiguration(
  bindings: readonly SensorBinding[],
  channels: readonly AvailableSensor[],
  placements: readonly LayoutPlacement[],
): StagedSensorConfiguration[] {
  const channelById = new Map(channels.map((channel) => [channel.channelId, channel]));
  const placementById = new Map(placements.map((placement) => [placement.sensorId, placement]));

  return bindings
    .filter((binding) => binding.unboundAt === null)
    .map((binding) => {
      const channel = channelById.get(binding.channelId);
      const placement = placementById.get(binding.channelId) ?? defaultPlacement(
        binding.side,
        binding.shelf,
        binding.position,
      );
      return {
        id: binding.channelId,
        slotKey: binding.slotKey,
        label: binding.label,
        name: sensorName(channel, binding.channelId),
        side: binding.side,
        shelf: binding.shelf,
        position: binding.position,
        x: placement.x,
        y: placement.y,
        temperatureC: channel?.latestValue ?? null,
        status: statusFromQuality(channel),
        updatedAt: channel?.capturedAt ?? binding.boundAt,
        trend: channel?.latestValue === null || channel?.latestValue === undefined
          ? []
          : [channel.latestValue],
        metric: channel?.metric ?? "temperature",
        unit: channel?.unit ?? "degC",
      };
    })
    .sort(compareStagedSensors);
}

export function addChannelToConfiguration(
  current: readonly StagedSensorConfiguration[],
  channel: AvailableSensor,
  totalSlots: number,
): StagedSensorConfiguration[] {
  if (current.some((sensor) => sensor.id === channel.channelId)) return [...current];
  const slot = firstAvailableSlot(current, totalSlots);
  if (!slot) throw new Error("Усі доступні позиції датчиків уже зайняті.");
  const placement = defaultPlacement(slot.side, slot.shelf, slot.position);
  const sensor: StagedSensorConfiguration = {
    id: channel.channelId,
    slotKey: slot.slotKey,
    label: slot.label,
    name: sensorName(channel, channel.channelId),
    side: slot.side,
    shelf: slot.shelf,
    position: slot.position,
    x: placement.x,
    y: placement.y,
    temperatureC: channel.latestValue,
    status: statusFromQuality(channel),
    updatedAt: channel.capturedAt,
    trend: channel.latestValue === null ? [] : [channel.latestValue],
    metric: channel.metric,
    unit: channel.unit,
  };
  return [...current, sensor].sort(compareStagedSensors);
}

export function replaceConfiguredChannel(
  current: readonly StagedSensorConfiguration[],
  sensorId: string,
  channel: AvailableSensor,
): StagedSensorConfiguration[] {
  if (
    channel.channelId !== sensorId &&
    current.some((sensor) => sensor.id === channel.channelId)
  ) {
    throw new Error("Цей датчик уже використовується на схемі.");
  }
  return current
    .map((sensor) =>
      sensor.id === sensorId
        ? {
            ...sensor,
            id: channel.channelId,
            name: sensorName(channel, channel.channelId),
            temperatureC: channel.latestValue,
            status: statusFromQuality(channel),
            updatedAt: channel.capturedAt,
            trend: channel.latestValue === null ? [] : [channel.latestValue],
            metric: channel.metric,
            unit: channel.unit,
          }
        : sensor,
    )
    .sort(compareStagedSensors);
}

export function updateConfiguredSensor(
  current: readonly StagedSensorConfiguration[],
  sensorId: string,
  patch: Partial<Pick<StagedSensorConfiguration, "label" | "side" | "shelf" | "position">>,
): StagedSensorConfiguration[] {
  return current
    .map((sensor) => {
      if (sensor.id !== sensorId) return sensor;
      const side = patch.side ?? sensor.side;
      const shelf = patch.shelf ?? sensor.shelf;
      const position = patch.position ?? sensor.position;
      const slotKey = slotKeyFor(side, shelf, position);
      const conflict = current.some(
        (candidate) => candidate.id !== sensorId && candidate.slotKey === slotKey,
      );
      if (conflict) throw new Error("Вибрана позиція вже зайнята іншим датчиком.");
      return {
        ...sensor,
        ...patch,
        side,
        shelf,
        position,
        slotKey,
      };
    })
    .sort(compareStagedSensors);
}

export function removeConfiguredSensor(
  current: readonly StagedSensorConfiguration[],
  sensorId: string,
): StagedSensorConfiguration[] {
  return current.filter((sensor) => sensor.id !== sensorId);
}

export function moveConfiguredSensor(
  current: readonly StagedSensorConfiguration[],
  sensorId: string,
  x: number,
  y: number,
): StagedSensorConfiguration[] {
  return current.map((sensor) =>
    sensor.id === sensorId ? { ...sensor, x: clampCoordinate(x), y: clampCoordinate(y) } : sensor,
  );
}

export function configurationPayload(
  configuration: readonly StagedSensorConfiguration[],
): SensorConfigurationItem[] {
  return configuration.map((sensor) => ({
    slotKey: sensor.slotKey,
    channelId: sensor.id,
    label: sensor.label.trim(),
    side: sensor.side,
    shelf: sensor.shelf,
    position: sensor.position,
    x: sensor.x,
    y: sensor.y,
  }));
}

export function configurationsEqual(
  first: readonly StagedSensorConfiguration[],
  second: readonly StagedSensorConfiguration[],
): boolean {
  if (first.length !== second.length) return false;
  const secondById = new Map(second.map((sensor) => [sensor.id, sensor]));
  return first.every((sensor) => {
    const candidate = secondById.get(sensor.id);
    return Boolean(
      candidate &&
        candidate.slotKey === sensor.slotKey &&
        candidate.label === sensor.label &&
        candidate.side === sensor.side &&
        candidate.shelf === sensor.shelf &&
        candidate.position === sensor.position &&
        Math.abs(candidate.x - sensor.x) < 0.000001 &&
        Math.abs(candidate.y - sensor.y) < 0.000001,
    );
  });
}

export function unusedClimateChamberChannels(
  channels: readonly AvailableSensor[],
  configuration: readonly StagedSensorConfiguration[],
  equipmentId: string,
): AvailableSensor[] {
  const used = new Set(configuration.map((sensor) => sensor.id));
  return channels.filter(
    (channel) =>
      !used.has(channel.channelId) &&
      (!channel.isBound || channel.boundEquipmentId === equipmentId),
  );
}

export function selectableReplacementChannels(
  channels: readonly AvailableSensor[],
  configuration: readonly StagedSensorConfiguration[],
  sensorId: string,
  equipmentId: string,
): AvailableSensor[] {
  const usedByOther = new Set(
    configuration.filter((sensor) => sensor.id !== sensorId).map((sensor) => sensor.id),
  );
  return channels.filter(
    (channel) =>
      !usedByOther.has(channel.channelId) &&
      (!channel.isBound || channel.boundEquipmentId === equipmentId),
  );
}

function firstAvailableSlot(
  current: readonly StagedSensorConfiguration[],
  totalSlots: number,
): { slotKey: string; label: string; side: SensorSide; shelf: number; position: number } | null {
  const used = new Set(current.map((sensor) => sensor.slotKey));
  const capacity = Math.min(48, Math.max(0, totalSlots));
  for (let index = 0; index < capacity; index += 1) {
    const side: SensorSide = index < 24 ? "front" : "rear";
    const localIndex = index % 24;
    const shelf = Math.floor(localIndex / 6) + 1;
    const position = (localIndex % 6) + 1;
    const slotKey = slotKeyFor(side, shelf, position);
    if (used.has(slotKey)) continue;
    return {
      slotKey,
      label: `${String(localIndex + 1).padStart(2, "0")}${side === "front" ? "F" : "R"}`,
      side,
      shelf,
      position,
    };
  }
  return null;
}

function slotKeyFor(side: SensorSide, shelf: number, position: number): string {
  const localIndex = (shelf - 1) * 6 + position;
  return `${side}-${String(localIndex).padStart(2, "0")}`;
}

function defaultPlacement(side: SensorSide, shelf: number, position: number): LayoutPlacement {
  const column = position - 1;
  const xBase = 0.17 + column * 0.13;
  const yBase = 0.21 + (shelf - 1) * 0.205;
  const rearOffset = side === "rear" ? 0.032 : -0.032;
  return {
    sensorId: "",
    x: Math.min(0.94, xBase + rearOffset),
    y: Math.min(0.91, yBase + (side === "rear" ? 0.055 : 0)),
  };
}

function sensorName(channel: AvailableSensor | undefined, channelId: string): string {
  if (!channel) return channelId;
  return `${channel.metric} · ${channelId}`;
}

function statusFromQuality(channel: AvailableSensor | undefined): SensorStatus {
  if (!channel || channel.latestValue === null) return "no-data";
  const quality = channel.quality.toLowerCase();
  if (quality.includes("alarm") || quality.includes("error")) return "alarm";
  if (quality.includes("warning") || quality.includes("uncertain")) return "warning";
  return "normal";
}

function compareStagedSensors(
  first: StagedSensorConfiguration,
  second: StagedSensorConfiguration,
): number {
  return (
    first.side.localeCompare(second.side) ||
    first.shelf - second.shelf ||
    first.position - second.position ||
    first.id.localeCompare(second.id)
  );
}

function clampCoordinate(value: number): number {
  return Math.min(1, Math.max(0, value));
}
