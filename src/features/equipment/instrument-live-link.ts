import type { CommissioningSession } from "./commissioning-repository";
import { sectionEquipmentId, sectionProbeCount } from "./xjp60d-sections";

// Canonical identities used by commissioning activation and Device Agent.
const equipmentPrefixes: Record<string, string> = {
  "dixell-xjp60d": "K",
  "f-and-f-le01mp": "LE01MP-",
  "embraco-sync": "EMBRACO-",
};

export function instrumentLiveLink(session: CommissioningSession): string | null {
  const sectionCount = sectionProbeCount(session.profileId);
  if (
    session.lifecycle !== "active" ||
    !session.nodeId?.trim() ||
    !session.profileId ||
    (!Object.hasOwn(equipmentPrefixes, session.profileId) && sectionCount === null) ||
    session.unitId === null ||
    !Number.isInteger(session.unitId) ||
    session.unitId < 1 ||
    session.unitId > (sectionCount === null ? 247 : 242) ||
    (sectionCount !== null && !session.busId)
  )
    return null;

  const params = new URLSearchParams({
    workspace: "explorer",
    node: session.nodeId,
    equipment:
      sectionCount === null
        ? `${equipmentPrefixes[session.profileId]}${session.unitId}`
        : sectionEquipmentId(session.busId!, session.unitId),
  });
  return `/live?${params}`;
}
