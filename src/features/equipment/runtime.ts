import type { ClimateCatalogRepository } from "@/features/refrigeration/climate-catalog-repository";
import {
  createRefrigerationEquipmentRuntime,
  type RefrigerationEquipmentRuntimeInput,
} from "@/features/refrigeration/equipment-repository-runtime";
import type { RefrigerationEquipmentRepository } from "@/features/refrigeration/equipment-repository";

export type EquipmentRegistryRuntime = {
  mode: "demo" | "live";
  equipmentRepository: RefrigerationEquipmentRepository | null;
  climateCatalogRepository: ClimateCatalogRepository | null;
  error: string | null;
};

export function createEquipmentRegistryRuntime(
  input: RefrigerationEquipmentRuntimeInput = {},
): EquipmentRegistryRuntime {
  // Reuse the proven authentication and organization-scoping boundary instead of creating a parallel client.
  const runtime = createRefrigerationEquipmentRuntime(input);
  return {
    mode: runtime.mode,
    equipmentRepository: runtime.equipmentRepository,
    climateCatalogRepository: runtime.climateCatalogRepository ?? null,
    error: runtime.error,
  };
}
