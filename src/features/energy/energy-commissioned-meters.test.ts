import { describe, expect, it } from "vitest";
import type { CommissioningSession } from "@/features/equipment/commissioning-repository";
import { commissionedEnergyMeters, energyMeterIdentity } from "./energy-commissioned-meters";

function session(overrides: Partial<CommissioningSession> = {}): CommissioningSession {
  return {
    id: "a",
    lifecycle: "active",
    deviceClass: "energy-meter",
    manufacturer: "Eastron",
    model: "SDM120M",
    profileId: "eastron-sdm120m",
    profileVersion: "eastron-sdm120m-fc04-v1",
    transportKind: "modbus_rtu",
    nodeId: "edge-a",
    busId: "commissioning-0123456789abcdef",
    stableTransportIdentifier: null,
    unitId: 1,
    ipAddress: null,
    targetEquipmentKey: null,
    blockedReason: null,
    unsupportedReason: null,
    version: 1,
    createdBy: "test",
    updatedBy: "test",
    createdAt: "",
    updatedAt: "",
    cancelledAt: null,
    displayName: "Перший",
    ...overrides,
  };
}

describe("commissioned Energy meter identity", () => {
  it("separates equal Unit IDs across buses and nodes from the legacy meter", () => {
    const meters = commissionedEnergyMeters([
      session(),
      session({ id: "b", busId: "commissioning-fedcba9876543210", displayName: "Другий" }),
      session({ id: "c", nodeId: "edge-b" }),
    ]);
    expect(meters).toHaveLength(3);
    expect(new Set(meters.map((item) => energyMeterIdentity(item.nodeId, item.equipmentId))).size).toBe(3);
    expect(meters.every((item) => item.equipmentId !== "SDM120M-1")).toBe(true);
    expect(meters.map((item) => item.label)).toEqual(["Перший", "Другий", "Перший"]);
  });

  it("excludes duplicate, inactive, unsupported or malformed session identities", () => {
    expect(
      commissionedEnergyMeters([
        session(),
        session({ id: "duplicate" }),
        session({ id: "inactive", lifecycle: "verified", busId: "commissioning-fedcba9876543210" }),
        session({ id: "old", profileVersion: "unknown", busId: "commissioning-fedcba9876543210" }),
        session({ id: "bus", busId: "rs485-main" }),
        session({ id: "unit", unitId: 248, busId: "commissioning-fedcba9876543210" }),
      ]),
    ).toEqual([]);
  });
});
