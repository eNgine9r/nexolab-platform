import type { CommissioningSession } from "./commissioning-repository";
import { sectionEquipmentId, sectionProbeCount } from "./xjp60d-sections";

// Canonical identities used by commissioning activation and Device Agent.
const equipmentPrefixes: Record<string, string> = {
  "dixell-xjp60d": "K",
  "f-and-f-le01mp": "LE01MP-",
  "embraco-sync": "EMBRACO-",
  "eastron-sdm120m": "SDM120M-",
  "waveshare-8ai-b-v3": "WAVESHARE-8AI-",
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
    ((sectionCount !== null ||
      session.profileId === "eastron-sdm120m" ||
      session.profileId === "waveshare-8ai-b-v3") &&
      !session.busId)
  )
    return null;

  const params = new URLSearchParams({
    workspace: "explorer",
    node: session.nodeId,
    equipment:
      session.profileId === "waveshare-8ai-b-v3" && session.busId?.startsWith("commissioning-")
        ? `WAVESHARE-8AI:${session.busId}:${session.unitId}`
        : session.profileId === "eastron-sdm120m" && session.busId?.startsWith("commissioning-")
          ? `SDM120M:${session.busId}:${session.unitId}`
          : sectionCount === null
            ? `${equipmentPrefixes[session.profileId]}${session.unitId}`
            : sectionEquipmentId(session.busId!, session.unitId),
  });
  return `/live?${params}`;
}
