export const sectionProfilePrefix = "dixell-xjp60d-sections-";

export function sectionProbeCount(profileId: string | null): number | null {
  const count = profileId?.startsWith(sectionProfilePrefix)
    ? profileId.slice(sectionProfilePrefix.length)
    : "";
  return /^[1-6]$/.test(count) ? Number(count) : null;
}

export function sectionEquipmentId(busId: string, firstAddress: number): string {
  return `XJP60D-S:${busId}:${firstAddress}`;
}
