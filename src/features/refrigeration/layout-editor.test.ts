import { describe, expect, it } from "vitest";

import {
  applySnap,
  clampNormalized,
  nearestSlot,
  pushHistory,
  redo,
  snapToGrid,
  undo,
  type CommandHistory,
  type LayoutPlacement,
  type MovePlacementCommand,
} from "./layout-editor";

const placements: LayoutPlacement[] = [
  { sensorId: "sensor-1", x: 0.2, y: 0.3 },
  { sensorId: "sensor-2", x: 0.7, y: 0.8 },
];

const command: MovePlacementCommand = {
  type: "move-placement",
  sensorId: "sensor-1",
  before: { x: 0.2, y: 0.3 },
  after: { x: 0.45, y: 0.55 },
};

describe("layout editor primitives", () => {
  it("clamps normalized coordinates to the inclusive unit interval", () => {
    expect(clampNormalized(-1)).toBe(0);
    expect(clampNormalized(0.4)).toBe(0.4);
    expect(clampNormalized(2)).toBe(1);
    expect(clampNormalized(Number.NaN)).toBe(0);
  });

  it("snaps coordinates to a deterministic grid", () => {
    expect(snapToGrid(0.26, 10)).toBe(0.3);
    expect(applySnap({ x: 0.24, y: 0.76 }, "grid", { gridDivisions: 4 })).toEqual({
      x: 0.25,
      y: 0.75,
    });
  });

  it("rejects invalid grid and history limits", () => {
    expect(() => snapToGrid(0.5, 0)).toThrow(RangeError);
    expect(() => pushHistory({ past: [], future: [] }, command, 0)).toThrow(RangeError);
  });

  it("selects the nearest normalized slot", () => {
    expect(
      nearestSlot({ x: 0.58, y: 0.61 }, [
        { x: 0.2, y: 0.2 },
        { x: 0.6, y: 0.6 },
      ]),
    ).toEqual({ x: 0.6, y: 0.6 });
  });

  it("records a command and clears the redo branch", () => {
    const history = pushHistory({ past: [], future: [command] }, command);

    expect(history.past).toEqual([command]);
    expect(history.future).toEqual([]);
  });

  it("undoes and redoes an exact marker move", () => {
    const appliedPlacements = [{ sensorId: "sensor-1", x: 0.45, y: 0.55 }, placements[1]];
    const initialHistory: CommandHistory = { past: [command], future: [] };

    const undone = undo(appliedPlacements, initialHistory);
    expect(undone.placements[0]).toEqual(placements[0]);
    expect(undone.history.future).toEqual([command]);

    const redone = redo(undone.placements, undone.history);
    expect(redone.placements[0]).toEqual(appliedPlacements[0]);
    expect(redone.history.future).toEqual([]);
  });

  it("keeps no-op undo and redo calls stable", () => {
    const history: CommandHistory = { past: [], future: [] };

    expect(undo(placements, history)).toEqual({ placements, history });
    expect(redo(placements, history)).toEqual({ placements, history });
  });
});
