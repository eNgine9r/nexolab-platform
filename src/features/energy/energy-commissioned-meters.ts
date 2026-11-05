import type { CommissioningSession } from "@/features/equipment/commissioning-repository";

/** An inventory identity, never an alias for a legacy Unit-only meter. */
export interface CommissionedEnergyMeter {
  nodeId: string;
  busId: string;
  unitId: number;
  equipmentId: string;
  label: string;
  family: "sdm120";
}

export function energyMeterIdentity(nodeId: string, equipmentId: string): string {
  return JSON.stringify([nodeId, equipmentId]);
}

/** Caller must supply sessions from the current authorized organization. */
export function commissionedEnergyMeters(
  sessions: readonly CommissioningSession[],
): CommissionedEnergyMeter[] {
  const candidates = new Map<string, CommissionedEnergyMeter[]>();
  for (const session of sessions) {
    const { nodeId, busId, unitId } = session;
    if (
      session.lifecycle !== "active" ||
      session.profileId !== "eastron-sdm120m" ||
      session.profileVersion !== "eastron-sdm120m-fc04-v1" ||
      !nodeId ||
      nodeId !== nodeId.trim() ||
      !busId ||
      !/^commissioning-[0-9a-f]{16}$/.test(busId) ||
      unitId === null ||
      !Number.isInteger(unitId) ||
      unitId < 1 ||
      unitId > 247
    )
      continue;

    const equipmentId = `SDM120M:${busId}:${unitId}`;
    const key = energyMeterIdentity(nodeId, equipmentId);
    const meter: CommissionedEnergyMeter = {
      nodeId,
      busId,
      unitId,
      equipmentId,
      family: "sdm120",
      label: session.displayName?.trim() || `SDM120M · ${busId} · Unit ${unitId}`,
    };
    candidates.set(key, [...(candidates.get(key) ?? []), meter]);
  }
  // An ambiguous inventory must not arbitrarily attribute data to one session.
  return [...candidates.values()].filter((items) => items.length === 1).map((items) => items[0]);
}
