import type { LayoutPlacement } from "./layout-editor";

export const LAYOUT_DRAFT_SCHEMA_VERSION = 1;

export interface LayoutDraftPayload {
  version: typeof LAYOUT_DRAFT_SCHEMA_VERSION;
  equipmentId: string;
  savedAt: string;
  placements: LayoutPlacement[];
}

export interface LayoutDraftStorage {
  load(equipmentId: string): string | null;
  save(equipmentId: string, payload: string): void;
  remove(equipmentId: string): void;
}

export function layoutDraftStorageKey(equipmentId: string): string {
  return `nexolab:refrigeration-layout-draft:v${LAYOUT_DRAFT_SCHEMA_VERSION}:${equipmentId}`;
}

export function createLayoutDraftPayload(
  equipmentId: string,
  placements: readonly LayoutPlacement[],
  savedAt = new Date().toISOString(),
): LayoutDraftPayload {
  return {
    version: LAYOUT_DRAFT_SCHEMA_VERSION,
    equipmentId,
    savedAt,
    placements: placements.map((placement) => ({ ...placement })),
  };
}

export function serializeLayoutDraft(payload: LayoutDraftPayload): string {
  return JSON.stringify(payload);
}

export function parseLayoutDraft(
  raw: string | null,
  expectedEquipmentId: string,
  allowedSensorIds: ReadonlySet<string>,
): LayoutDraftPayload | null {
  if (!raw) return null;

  try {
    const value: unknown = JSON.parse(raw);
    if (!isRecord(value)) return null;

    if (
      value.version !== LAYOUT_DRAFT_SCHEMA_VERSION ||
      value.equipmentId !== expectedEquipmentId ||
      typeof value.savedAt !== "string" ||
      Number.isNaN(Date.parse(value.savedAt)) ||
      !Array.isArray(value.placements)
    ) {
      return null;
    }

    const seen = new Set<string>();
    const placements: LayoutPlacement[] = [];

    for (const candidate of value.placements) {
      if (!isRecord(candidate)) return null;

      const { sensorId, x, y } = candidate;
      if (
        typeof sensorId !== "string" ||
        !allowedSensorIds.has(sensorId) ||
        seen.has(sensorId) ||
        !isNormalizedCoordinate(x) ||
        !isNormalizedCoordinate(y)
      ) {
        return null;
      }

      seen.add(sensorId);
      placements.push({ sensorId, x, y });
    }

    if (placements.length !== allowedSensorIds.size) return null;

    return {
      version: LAYOUT_DRAFT_SCHEMA_VERSION,
      equipmentId: expectedEquipmentId,
      savedAt: value.savedAt,
      placements,
    };
  } catch {
    return null;
  }
}

export function createBrowserLayoutDraftStorage(
  storage: Pick<Storage, "getItem" | "setItem" | "removeItem">,
): LayoutDraftStorage {
  return {
    load(equipmentId) {
      try {
        return storage.getItem(layoutDraftStorageKey(equipmentId));
      } catch {
        return null;
      }
    },
    save(equipmentId, payload) {
      try {
        storage.setItem(layoutDraftStorageKey(equipmentId), payload);
      } catch {
        // Recovery is best-effort. The editor must remain usable without storage.
      }
    },
    remove(equipmentId) {
      try {
        storage.removeItem(layoutDraftStorageKey(equipmentId));
      } catch {
        // Removing recovery data is best-effort.
      }
    },
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isNormalizedCoordinate(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
}
