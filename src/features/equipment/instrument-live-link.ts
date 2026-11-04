import type { CommissioningSession } from "./commissioning-repository";

// Canonical identities used by commissioning activation and Device Agent.
const equipmentPrefixes: Record<string, string> = {
  "dixell-xjp60d": "K",
  "f-and-f-le01mp": "LE01MP-",
  "embraco-sync": "EMBRACO-",
};

export function instrumentLiveLink(session: CommissioningSession): string | null {
  if (
    session.lifecycle !== "active" ||
    !session.nodeId?.trim() ||
    !session.profileId ||
    !Object.hasOwn(equipmentPrefixes, session.profileId) ||
    session.unitId === null ||
    !Number.isInteger(session.unitId) ||
    session.unitId < 1 ||
    session.unitId > 247
  )
    return null;

  const params = new URLSearchParams({
    workspace: "explorer",
    node: session.nodeId,
    equipment: `${equipmentPrefixes[session.profileId]}${session.unitId}`,
  });
  return `/live?${params}`;
}
