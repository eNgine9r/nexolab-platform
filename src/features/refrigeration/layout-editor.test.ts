import { describe, expect, it } from "vitest";

import { getRefrigerationEquipment } from "@/data/refrigeration";

import {
  clampNormalized,
  cloneSensors,
  moveSensor,
  moveSensorByDelta,
  normalizedPointFromClient,
  placementsChanged,
  snapNormalized,
} from "./layout-editor";

function referenceSensors() {
  const equipment = getRefrigerationEquipment("showcase-106-01");

  if (!equipment) {
    throw new Error("Reference equipment is missing");
  }

  return equipment.sensors;
}

describe("layout editor coordinates", () => {
  it("clamps values to the normalized coordinate range", () => {
    expect(clampNormalized(-0.4)).toBe(0);
    expect(clampNormalized(0.45)).toBe(0.45);
    expect(clampNormalized(1.8)).toBe(1);
    expect(clampNormalized(Number.NaN)).toBe(0);
  });

  it("snaps normalized values to the configured grid", () => {
    expect(snapNormalized(0.263, 0.025)).toBeCloseTo(0.275);
    expect(snapNormalized(0.992, 0.025)).toBe(1);
  });

  it("moves one sensor without mutating the fixture source", () => {
    const source = referenceSensors();
    const before = source[0];
    const moved = moveSensor(source, before.id, { x: 0.44, y: 0.61 }, { snapToGrid: false });

    expect(moved[0]).toMatchObject({ x: 0.44, y: 0.61 });
    expect(source[0]).toBe(before);
    expect(source[0].x).not.toBe(0.44);
  });

  it("clamps keyboard-style delta movement", () => {
    const source = referenceSensors();
    const moved = moveSensorByDelta(source, source[0].id, { x: -2, y: 3 }, { snapToGrid: false });

    expect(moved[0]).toMatchObject({ x: 0, y: 1 });
  });

  it("detects placement changes independently from telemetry fields", () => {
    const source = referenceSensors();
    const telemetryOnly = cloneSensors(source).map((sensor, index) =>
      index === 0 ? { ...sensor, temperatureC: 99 } : sensor,
    );
    const moved = moveSensor(source, source[0].id, { x: 0.5, y: 0.5 }, { snapToGrid: false });

    expect(placementsChanged(source, telemetryOnly)).toBe(false);
    expect(placementsChanged(source, moved)).toBe(true);
  });

  it("converts client coordinates using the rendered stage bounds", () => {
    expect(
      normalizedPointFromClient(250, 350, {
        left: 50,
        top: 150,
        width: 400,
        height: 400,
      }),
    ).toEqual({ x: 0.5, y: 0.5 });
  });
});
