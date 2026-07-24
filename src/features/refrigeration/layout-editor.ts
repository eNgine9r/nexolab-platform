export type NormalizedPoint = {
  x: number;
  y: number;
};

export type SnapMode = "none" | "grid" | "slots";

export type LayoutPlacement = NormalizedPoint & {
  sensorId: string;
};

export type MovePlacementCommand = {
  type: "move-placement";
  sensorId: string;
  before: NormalizedPoint;
  after: NormalizedPoint;
};

export type LayoutCommand = MovePlacementCommand;

export type CommandHistory = {
  past: LayoutCommand[];
  future: LayoutCommand[];
};

const DEFAULT_HISTORY_LIMIT = 100;

export function clampNormalized(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

export function clampPoint(point: NormalizedPoint): NormalizedPoint {
  return {
    x: clampNormalized(point.x),
    y: clampNormalized(point.y),
  };
}

export function snapToGrid(value: number, divisions: number): number {
  if (!Number.isInteger(divisions) || divisions <= 0) {
    throw new RangeError("Grid divisions must be a positive integer.");
  }

  return clampNormalized(Math.round(clampNormalized(value) * divisions) / divisions);
}

export function nearestSlot(point: NormalizedPoint, slots: readonly NormalizedPoint[]): NormalizedPoint {
  if (slots.length === 0) return clampPoint(point);

  const target = clampPoint(point);
  let closest = clampPoint(slots[0]);
  let closestDistance = squaredDistance(target, closest);

  for (const slot of slots.slice(1)) {
    const candidate = clampPoint(slot);
    const distance = squaredDistance(target, candidate);

    if (distance < closestDistance) {
      closest = candidate;
      closestDistance = distance;
    }
  }

  return closest;
}

export function applySnap(
  point: NormalizedPoint,
  mode: SnapMode,
  options: { gridDivisions?: number; slots?: readonly NormalizedPoint[] } = {},
): NormalizedPoint {
  const clamped = clampPoint(point);

  if (mode === "grid") {
    const divisions = options.gridDivisions ?? 20;
    return {
      x: snapToGrid(clamped.x, divisions),
      y: snapToGrid(clamped.y, divisions),
    };
  }

  if (mode === "slots") {
    return nearestSlot(clamped, options.slots ?? []);
  }

  return clamped;
}

export function movePlacement(
  placements: readonly LayoutPlacement[],
  sensorId: string,
  point: NormalizedPoint,
): LayoutPlacement[] {
  const nextPoint = clampPoint(point);

  return placements.map((placement) =>
    placement.sensorId === sensorId ? { ...placement, ...nextPoint } : placement,
  );
}

export function executeCommand(
  placements: readonly LayoutPlacement[],
  command: LayoutCommand,
): LayoutPlacement[] {
  return movePlacement(placements, command.sensorId, command.after);
}

export function undoCommand(
  placements: readonly LayoutPlacement[],
  command: LayoutCommand,
): LayoutPlacement[] {
  return movePlacement(placements, command.sensorId, command.before);
}

export function pushHistory(
  history: CommandHistory,
  command: LayoutCommand,
  limit = DEFAULT_HISTORY_LIMIT,
): CommandHistory {
  if (!Number.isInteger(limit) || limit <= 0) {
    throw new RangeError("History limit must be a positive integer.");
  }

  return {
    past: [...history.past, command].slice(-limit),
    future: [],
  };
}

export function undo(
  placements: readonly LayoutPlacement[],
  history: CommandHistory,
): { placements: LayoutPlacement[]; history: CommandHistory } {
  const command = history.past.at(-1);

  if (!command) {
    return { placements: [...placements], history };
  }

  return {
    placements: undoCommand(placements, command),
    history: {
      past: history.past.slice(0, -1),
      future: [command, ...history.future],
    },
  };
}

export function redo(
  placements: readonly LayoutPlacement[],
  history: CommandHistory,
): { placements: LayoutPlacement[]; history: CommandHistory } {
  const [command, ...remainingFuture] = history.future;

  if (!command) {
    return { placements: [...placements], history };
  }

  return {
    placements: executeCommand(placements, command),
    history: {
      past: [...history.past, command],
      future: remainingFuture,
    },
  };
}

function squaredDistance(first: NormalizedPoint, second: NormalizedPoint): number {
  const deltaX = first.x - second.x;
  const deltaY = first.y - second.y;
  return deltaX * deltaX + deltaY * deltaY;
}
