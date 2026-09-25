import type {
  CommissioningRepository,
  CommissioningSession,
  SupportedDeviceProfile,
} from "./commissioning-repository";

export type CommissionedControllerAssociation = {
  session: CommissioningSession;
  profile: SupportedDeviceProfile;
};

export async function loadCommissionedControllerAssociation(
  repository: CommissioningRepository,
  equipmentId: string,
  signal?: AbortSignal,
): Promise<CommissionedControllerAssociation | null> {
  const [sessions, profiles] = await Promise.all([
    repository.listSessions(signal),
    repository.listProfiles(signal),
  ]);
  const profileById = new Map(profiles.map((profile) => [profile.id, profile] as const));
  const candidates = sessions
    .filter((session) => session.lifecycle === "verified" && session.targetEquipmentKey === equipmentId)
    .map((session) => ({
      session,
      profile: session.profileId ? (profileById.get(session.profileId) ?? null) : null,
    }))
    .filter(
      (item): item is CommissionedControllerAssociation =>
        item.profile !== null &&
        item.profile.activationSupported === false &&
        item.session.deviceClass === "temperature-controller",
    )
    .sort((left, right) => right.session.updatedAt.localeCompare(left.session.updatedAt));
  return candidates[0] ?? null;
}
