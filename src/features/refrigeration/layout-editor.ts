import type { RefrigerationSensor } from "@/data/refrigeration";

export const DEFAULT_GRID_STEP = 0.025;
export const KEYBOARD_FINE_STEP = 0.005;
export const KEYBOARD_COARSE_STEP = 0.025;

export interface NormalizedPoint {
  x: number;
  y: number;
}

export interface MoveOptions {
  snapToGrid: boolean;
  gridStep?: number;
}

export function clampNormalized(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }

  return Math.min(1, Math.max(0, value));
}

export function snapNormalized(value: number, step = DEFAULT_GRID_STEP): number {
  if (!Number.isFinite(step) || step <= 0 || step > 1) {
    return clampNormalized(value);
  }

  return clampNormalized(Math.round(value / step) * step);
}

export function normalizePoint(point: NormalizedPoint, options: MoveOptions): NormalizedPoint {
  const x = clampNormalized(point.x);
  const y = clampNormalized(point.y);

  if (!options.snapToGrid) {
    return { x, y };
  }

  const gridStep = options.gridStep ?? DEFAULT_GRID_STEP;

  return {
    x: snapNormalized(x, gridStep),
    y: snapNormalized(y, gridStep),
  };
}

export function moveSensor(
  sensors: readonly RefrigerationSensor[],
  sensorId: string,
  point: NormalizedPoint,
  options: MoveOptions,
): RefrigerationSensor[] {
  const normalized = normalizePoint(point, options);

  return sensors.map((sensor) =>
    sensor.id === sensorId
      ? {
          ...sensor,
          x: normalized.x,
          y: normalized.y,
        }
      : sensor,
  );
}

export function moveSensorByDelta(
  sensors: readonly RefrigerationSensor[],
  sensorId: string,
  delta: NormalizedPoint,
  options: MoveOptions,
): RefrigerationSensor[] {
  const sensor = sensors.find((candidate) => candidate.id === sensorId);

  if (!sensor) {
    return cloneSensors(sensors);
  }

  return moveSensor(
    sensors,
    sensorId,
    {
      x: sensor.x + delta.x,
      y: sensor.y + delta.y,
    },
    options,
  );
}

export function cloneSensors(sensors: readonly RefrigerationSensor[]): RefrigerationSensor[] {
  return sensors.map((sensor) => ({
    ...sensor,
    trend: [...sensor.trend],
  }));
}

export function placementsChanged(
  baseline: readonly RefrigerationSensor[],
  candidate: readonly RefrigerationSensor[],
): boolean {
  if (baseline.length !== candidate.length) {
    return true;
  }

  const candidateById = new Map(candidate.map((sensor) => [sensor.id, sensor]));

  return baseline.some((sensor) => {
    const next = candidateById.get(sensor.id);

    return !next || next.x !== sensor.x || next.y !== sensor.y;
  });
}

export function normalizedPointFromClient(
  clientX: number,
  clientY: number,
  bounds: Pick<DOMRect, "left" | "top" | "width" | "height">,
): NormalizedPoint {
  if (bounds.width <= 0 || bounds.height <= 0) {
    return { x: 0, y: 0 };
  }

  return {
    x: clampNormalized((clientX - bounds.left) / bounds.width),
    y: clampNormalized((clientY - bounds.top) / bounds.height),
  };
}
