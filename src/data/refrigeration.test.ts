import { describe, expect, it } from "vitest";

import { getRefrigerationEquipment, refrigerationEquipment } from "./refrigeration";

describe("refrigeration fixtures", () => {
  it("creates the reference showcase with exactly 48 unique sensors", () => {
    const equipment = getRefrigerationEquipment("showcase-106-01");

    expect(equipment).toBeDefined();
    expect(equipment?.sensors).toHaveLength(48);
    expect(new Set(equipment?.sensors.map((sensor) => sensor.id)).size).toBe(48);
    expect(new Set(equipment?.sensors.map((sensor) => sensor.label)).size).toBe(48);
  });

  it("keeps every persisted marker coordinate normalized", () => {
    const sensors = refrigerationEquipment.flatMap((equipment) => equipment.sensors);

    for (const sensor of sensors) {
      expect(sensor.x).toBeGreaterThanOrEqual(0);
      expect(sensor.x).toBeLessThanOrEqual(1);
      expect(sensor.y).toBeGreaterThanOrEqual(0);
      expect(sensor.y).toBeLessThanOrEqual(1);
    }
  });

  it("builds balanced front and rear layouts for the 48-sensor showcase", () => {
    const equipment = getRefrigerationEquipment("showcase-106-01");
    const front = equipment?.sensors.filter((sensor) => sensor.side === "front") ?? [];
    const rear = equipment?.sensors.filter((sensor) => sensor.side === "rear") ?? [];

    expect(front).toHaveLength(24);
    expect(rear).toHaveLength(24);
    expect(new Set(front.map((sensor) => sensor.shelf))).toEqual(new Set([1, 2, 3, 4]));
    expect(new Set(rear.map((sensor) => sensor.shelf))).toEqual(new Set([1, 2, 3, 4]));
  });

  it("returns undefined for an unknown equipment identifier", () => {
    expect(getRefrigerationEquipment("missing-equipment")).toBeUndefined();
  });
});
