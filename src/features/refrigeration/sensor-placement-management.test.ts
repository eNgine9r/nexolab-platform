import { describe, expect, it } from "vitest";

import type { RefrigerationSensor } from "@/data/refrigeration";

import {
  applySensorPlacementChange,
  availableSensors,
  replacementSensors,
  suggestPlacement,
} from "./sensor-placement-management";

const sensors = [
  { id: "sensor-1", x: 0.2, y: 0.3 },
  { id: "sensor-2", x: 0.5, y: 0.5 },
  { id: "sensor-3", x: 0.8, y: 0.7 },
] as RefrigerationSensor[];

const placements = [
  { sensorId: "sensor-1", x: 0.2, y: 0.3 },
  { sensorId: "sensor-2", x: 0.5, y: 0.5 },
];

describe("sensor placement management", () => {
  it("lists sensors that are not assigned to the image", () => {
    expect(availableSensors(sensors, placements).map(({ id }) => id)).toEqual(["sensor-3"]);
  });

  it("lists every other sensor as a replacement candidate", () => {
    expect(replacementSensors(sensors, "sensor-1").map(({ id }) => id)).toEqual([
      "sensor-2",
      "sensor-3",
    ]);
  });

  it("adds an available sensor at its preferred free point", () => {
    expect(
      applySensorPlacementChange(placements, sensors, { type: "add", sensorId: "sensor-3" }),
    ).toContainEqual({ sensorId: "sensor-3", x: 0.8, y: 0.7 });
  });

  it("replaces an assigned sensor with an available sensor while preserving coordinates", () => {
    const next = applySensorPlacementChange(placements, sensors, {
      type: "replace",
      sensorId: "sensor-1",
      replacementSensorId: "sensor-3",
    });

    expect(next).toContainEqual({ sensorId: "sensor-3", x: 0.2, y: 0.3 });
    expect(next.some(({ sensorId }) => sensorId === "sensor-1")).toBe(false);
  });

  it("swaps two assigned sensors while preserving both physical positions", () => {
    const next = applySensorPlacementChange(placements, sensors, {
      type: "replace",
      sensorId: "sensor-1",
      replacementSensorId: "sensor-2",
    });

    expect(next).toContainEqual({ sensorId: "sensor-2", x: 0.2, y: 0.3 });
    expect(next).toContainEqual({ sensorId: "sensor-1", x: 0.5, y: 0.5 });
  });

  it("removes an assigned sensor but never allows an empty layout", () => {
    expect(
      applySensorPlacementChange(placements, sensors, { type: "remove", sensorId: "sensor-1" }),
    ).toEqual([{ sensorId: "sensor-2", x: 0.5, y: 0.5 }]);

    expect(() =>
      applySensorPlacementChange([placements[0]], sensors, {
        type: "remove",
        sensorId: "sensor-1",
      }),
    ).toThrow("at least one sensor");
  });

  it("rejects duplicate additions, self replacement and unknown assignments", () => {
    expect(() =>
      applySensorPlacementChange(placements, sensors, { type: "add", sensorId: "sensor-1" }),
    ).toThrow("already assigned");
    expect(() =>
      applySensorPlacementChange(placements, sensors, {
        type: "replace",
        sensorId: "sensor-1",
        replacementSensorId: "sensor-1",
      }),
    ).toThrow("different");
    expect(() =>
      applySensorPlacementChange(placements, sensors, { type: "add", sensorId: "missing" }),
    ).toThrow("Unknown sensor");
  });

  it("finds a nearby free point when the preferred position is occupied", () => {
    const point = suggestPlacement(sensors[0], placements);
    expect(point).not.toEqual({ x: 0.2, y: 0.3 });
    expect(point.x).toBeGreaterThanOrEqual(0);
    expect(point.x).toBeLessThanOrEqual(1);
    expect(point.y).toBeGreaterThanOrEqual(0);
    expect(point.y).toBeLessThanOrEqual(1);
  });
});
