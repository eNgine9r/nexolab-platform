import type { LayoutPlacement } from "@/features/refrigeration/layout-editor";

export const LAYOUT_DRAFT_SCHEMA_VERSION = 1;
export const LAYOUT_DRAFT_MAX_AGE_MS = 24 * 60 * 60 * 1000;
const FUTURE_CLOCK_SKEW_MS = 5 * 60 * 1000;
const STORAGE_PREFIX = "nexolab:refrigeration:layout-draft";

export type LayoutDraftPayload = {
  schemaVersion: typeof LAYOUT_DRAFT_SCHEMA_VERSION;
  equipmentId: string;
  savedAt: string;
  placements: LayoutPlacement[];
};

export type LayoutDraftStorage = {
  load: (equipmentId: string) => string | null;
  save: (equipmentId: string, payload: string) => boolean;
  remove: (equipmentId: string) => boolean;
};

export function layoutDraftStorageKey(equipmentId: string): string {
  return `${STORAGE_PREFIX}:${encodeURIComponent(equipmentId)}`;
}

export function createLayoutDraftPayload(
  equipmentId: string,
  placements: readonly LayoutPlacement[],
  savedAt = new Date().toISOString(),
): LayoutDraftPayload {
  return {
    schemaVersion: LAYOUT_DRAFT_SCHEMA_VERSION,
    equipmentId,
    savedAt,
    placements: placements.map(({ sensorId, x, y }) => ({ sensorId, x, y })),
  };
}

export function serializeLayoutDraft(payload: LayoutDraftPayload): string {
  return JSON.stringify(payload);
}

export function parseLayoutDraft(
  raw: string | null,
  expectedEquipmentId: string,
  allowedSensorIds: ReadonlySet<string>,
  nowMs = Date.now(),
): LayoutDraftPayload | null {
  if (!raw) return null;

  try {
    const candidate: unknown = JSON.parse(raw);
    if (!isRecord(candidate)) return null;
    if (candidate.schemaVersion !== LAYOUT_DRAFT_SCHEMA_VERSION) return null;
    if (candidate.equipmentId !== expectedEquipmentId) return null;
    if (typeof candidate.savedAt !== "string") return null;

    const savedAtMs = Date.parse(candidate.savedAt);
    if (!Number.isFinite(savedAtMs)) return null;
    if (savedAtMs > nowMs + FUTURE_CLOCK_SKEW_MS) return null;
    if (nowMs - savedAtMs > LAYOUT_DRAFT_MAX_AGE_MS) return null;
    if (!Array.isArray(candidate.placements)) return null;
    if (candidate.placements.length < 1 || candidate.placements.length > allowedSensorIds.size) {
      return null;
    }

    const placements: LayoutPlacement[] = [];
    const seen = new Set<string>();
    for (const value of candidate.placements) {
      if (!isRecord(value)) return null;
      const sensorId = value.sensorId;
      const x = value.x;
      const y = value.y;
      if (typeof sensorId !== "string" || !allowedSensorIds.has(sensorId) || seen.has(sensorId)) {
        return null;
      }
      if (!isNormalizedCoordinate(x) || !isNormalizedCoordinate(y)) return null;
      seen.add(sensorId);
      placements.push({ sensorId, x, y });
    }

    return {
      schemaVersion: LAYOUT_DRAFT_SCHEMA_VERSION,
      equipmentId: expectedEquipmentId,
      savedAt: new Date(savedAtMs).toISOString(),
      placements,
    };
  } catch {
    return null;
  }
}

export function createBrowserLayoutDraftStorage(storage: Storage): LayoutDraftStorage {
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
        return true;
      } catch {
        return false;
      }
    },
    remove(equipmentId) {
      try {
        storage.removeItem(layoutDraftStorageKey(equipmentId));
        return true;
      } catch {
        return false;
      }
    },
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNormalizedCoordinate(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
}
