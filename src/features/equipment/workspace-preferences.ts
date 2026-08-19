import { EQUIPMENT_REGISTRY_COLUMNS, type EquipmentRegistryColumn } from "./workspace";

export const EQUIPMENT_WORKSPACE_COLUMNS_STORAGE_KEY = "nexolab.equipment.workspace.columns.v1";
export const DEFAULT_EQUIPMENT_WORKSPACE_COLUMNS: readonly EquipmentRegistryColumn[] =
  EQUIPMENT_REGISTRY_COLUMNS;

export function parseEquipmentWorkspaceColumns(raw: string | null): EquipmentRegistryColumn[] {
  if (raw === null) return [...DEFAULT_EQUIPMENT_WORKSPACE_COLUMNS];
  try {
    const value = JSON.parse(raw) as unknown;
    if (!Array.isArray(value)) return [...DEFAULT_EQUIPMENT_WORKSPACE_COLUMNS];
    const allowed = new Set<EquipmentRegistryColumn>(EQUIPMENT_REGISTRY_COLUMNS);
    const columns = value.filter(
      (item): item is EquipmentRegistryColumn =>
        typeof item === "string" && allowed.has(item as EquipmentRegistryColumn),
    );
    if (columns.length !== value.length || new Set(columns).size !== columns.length) {
      return [...DEFAULT_EQUIPMENT_WORKSPACE_COLUMNS];
    }
    return columns;
  } catch {
    return [...DEFAULT_EQUIPMENT_WORKSPACE_COLUMNS];
  }
}

export function serializeEquipmentWorkspaceColumns(columns: readonly EquipmentRegistryColumn[]): string {
  return JSON.stringify(columns);
}
