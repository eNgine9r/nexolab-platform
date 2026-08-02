import type { RefrigerationSensor } from "@/data/refrigeration";
import { clampPoint, type LayoutPlacement, type NormalizedPoint } from "./layout-editor";

export type SensorPlacementChange =
  | { type: "add"; sensorId: string; point?: NormalizedPoint }
  | { type: "remove"; sensorId: string }
  | { type: "replace"; sensorId: string; replacementSensorId: string };

export function assignedSensorIds(placements: readonly LayoutPlacement[]): ReadonlySet<string> {
  return new Set(placements.map(({ sensorId }) => sensorId));
}

export function availableSensors(
  sensors: readonly RefrigerationSensor[],
  placements: readonly LayoutPlacement[],
): RefrigerationSensor[] {
  const assigned = assignedSensorIds(placements);
  return sensors.filter(({ id }) => !assigned.has(id));
}

export function replacementSensors(
  sensors: readonly RefrigerationSensor[],
  selectedSensorId: string,
): RefrigerationSensor[] {
  return sensors.filter(({ id }) => id !== selectedSensorId);
}

export function applySensorPlacementChange(
  placements: readonly LayoutPlacement[],
  sensors: readonly RefrigerationSensor[],
  change: SensorPlacementChange,
): LayoutPlacement[] {
  const sensorIds = new Set(sensors.map(({ id }) => id));
  const assigned = assignedSensorIds(placements);

  if (change.type === "add") {
    assertKnownSensor(sensorIds, change.sensorId);
    if (assigned.has(change.sensorId)) {
      throw new Error(`Sensor ${change.sensorId} is already assigned.`);
    }
    const sensor = sensors.find(({ id }) => id === change.sensorId);
    const point = change.point ?? suggestPlacement(sensor, placements);
    return [...placements, { sensorId: change.sensorId, ...clampPoint(point) }];
  }

  if (change.type === "remove") {
    if (!assigned.has(change.sensorId)) {
      throw new Error(`Sensor ${change.sensorId} is not assigned.`);
    }
    if (placements.length <= 1) {
      throw new Error("A layout must retain at least one sensor placement.");
    }
    return placements.filter(({ sensorId }) => sensorId !== change.sensorId);
  }

  assertKnownSensor(sensorIds, change.replacementSensorId);
  if (!assigned.has(change.sensorId)) {
    throw new Error(`Sensor ${change.sensorId} is not assigned.`);
  }
  if (change.sensorId === change.replacementSensorId) {
    throw new Error("Replacement sensor must be different from the selected sensor.");
  }

  if (assigned.has(change.replacementSensorId)) {
    return placements.map((placement) => {
      if (placement.sensorId === change.sensorId) {
        return { ...placement, sensorId: change.replacementSensorId };
      }
      if (placement.sensorId === change.replacementSensorId) {
        return { ...placement, sensorId: change.sensorId };
      }
      return placement;
    });
  }

  return placements.map((placement) =>
    placement.sensorId === change.sensorId
      ? { ...placement, sensorId: change.replacementSensorId }
      : placement,
  );
}

export function suggestPlacement(
  sensor: Pick<RefrigerationSensor, "x" | "y"> | undefined,
  placements: readonly LayoutPlacement[],
): NormalizedPoint {
  const preferred = sensor ? clampPoint({ x: sensor.x, y: sensor.y }) : { x: 0.5, y: 0.5 };
  if (!isOccupied(preferred, placements)) return preferred;

  for (let ring = 1; ring <= 8; ring += 1) {
    const radius = ring * 0.035;
    for (let step = 0; step < 12; step += 1) {
      const angle = (Math.PI * 2 * step) / 12;
      const candidate = clampPoint({
        x: preferred.x + Math.cos(angle) * radius,
        y: preferred.y + Math.sin(angle) * radius,
      });
      if (!isOccupied(candidate, placements)) return candidate;
    }
  }

  return preferred;
}

function isOccupied(point: NormalizedPoint, placements: readonly LayoutPlacement[]): boolean {
  return placements.some((placement) => Math.hypot(placement.x - point.x, placement.y - point.y) < 0.025);
}

function assertKnownSensor(sensorIds: ReadonlySet<string>, sensorId: string): void {
  if (!sensorIds.has(sensorId)) {
    throw new Error(`Unknown sensor ${sensorId}.`);
  }
}
