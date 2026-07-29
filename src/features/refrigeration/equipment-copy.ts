import type { RefrigerationEquipment } from "@/data/refrigeration";
import type { RefrigerationEquipmentCreateInput } from "@/features/refrigeration/equipment-repository";

const COPY_NAME_SUFFIX = " — копія";
const COPY_CODE_SUFFIX = "-COPY";

export function createEquipmentCopyDraft(
  source: RefrigerationEquipment,
  existing: readonly RefrigerationEquipment[],
): RefrigerationEquipmentCreateInput {
  return {
    name: nextAvailableValue(
      `${source.name}${COPY_NAME_SUFFIX}`,
      existing.map(({ name }) => name),
      (base, index) => `${base} ${index}`,
    ),
    code: nextAvailableValue(
      `${source.code}${COPY_CODE_SUFFIX}`,
      existing.map(({ code }) => code),
      (base, index) => `${base}-${index}`,
    ),
    location: source.location,
    laboratory: source.laboratory ?? "",
    zone: source.zone ?? "",
    nodeId: "",
    type: source.type,
    manufacturer: source.manufacturer,
    model: source.model,
    serialNumber: "",
    temperatureClass: source.temperatureClass,
    installedAt: "",
    servicedAt: "",
    lifecycleStatus: "active",
    totalSensors: source.totalSensors,
  };
}

function nextAvailableValue(
  base: string,
  existingValues: readonly string[],
  formatCandidate: (base: string, index: number) => string,
): string {
  const normalized = new Set(
    existingValues.map((value) => value.trim().toLocaleLowerCase("uk-UA")),
  );
  if (!normalized.has(base.toLocaleLowerCase("uk-UA"))) return base;

  let index = 2;
  while (normalized.has(formatCandidate(base, index).toLocaleLowerCase("uk-UA"))) {
    index += 1;
  }
  return formatCandidate(base, index);
}
