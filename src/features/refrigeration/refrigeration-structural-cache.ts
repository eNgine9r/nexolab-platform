import type { EquipmentLifecycleRepository } from "./equipment-lifecycle-repository";
import type {
  PublishLayoutDraftInput,
  RefrigerationLayoutRepository,
  RestoreLayoutRevisionInput,
  SaveLayoutDraftInput,
  UploadEquipmentImageInput,
} from "./layout-repository";

const FRESH_TTL_MS = 30_000;
const STALE_TTL_MS = 5 * 60_000;
const MAX_ENTRIES = 32;

type CacheEntry<T> = {
  value: T;
  storedAt: number;
  touchedAt: number;
};

type CacheBucket = {
  values: Map<string, CacheEntry<unknown>>;
  inflight: Map<string, Promise<unknown>>;
};

const buckets = new Map<string, CacheBucket>();

function bucket(scope: string): CacheBucket {
  let current = buckets.get(scope);
  if (!current) {
    current = { values: new Map(), inflight: new Map() };
    buckets.set(scope, current);
  }
  return current;
}

async function cached<T>(scope: string, key: string, loader: () => Promise<T>): Promise<T> {
  const now = Date.now();
  const current = bucket(scope);
  const stored = current.values.get(key) as CacheEntry<T> | undefined;

  if (stored && now - stored.storedAt <= FRESH_TTL_MS) {
    stored.touchedAt = now;
    return stored.value;
  }

  if (stored && now - stored.storedAt <= STALE_TTL_MS) {
    stored.touchedAt = now;
    void revalidate(scope, key, loader);
    return stored.value;
  }

  return revalidate(scope, key, loader);
}

async function revalidate<T>(scope: string, key: string, loader: () => Promise<T>): Promise<T> {
  const current = bucket(scope);
  const existing = current.inflight.get(key) as Promise<T> | undefined;
  if (existing) return existing;

  const request = loader()
    .then((value) => {
      const now = Date.now();
      current.values.set(key, { value, storedAt: now, touchedAt: now });
      trim(current);
      return value;
    })
    .finally(() => {
      current.inflight.delete(key);
    });

  current.inflight.set(key, request);
  return request;
}

function trim(current: CacheBucket): void {
  if (current.values.size <= MAX_ENTRIES) return;
  const oldest = [...current.values.entries()]
    .sort((left, right) => left[1].touchedAt - right[1].touchedAt)
    .slice(0, current.values.size - MAX_ENTRIES);
  for (const [key] of oldest) current.values.delete(key);
}

export function invalidateRefrigerationStructuralCache(scope: string, equipmentId?: string): void {
  if (!equipmentId) {
    buckets.delete(scope);
    return;
  }
  const current = buckets.get(scope);
  if (!current) return;
  const encoded = encodeURIComponent(equipmentId);
  for (const key of current.values.keys()) {
    if (key.includes(encoded)) current.values.delete(key);
  }
}

export function createCachedEquipmentLifecycleRepository(
  repository: EquipmentLifecycleRepository,
  scope: string,
): EquipmentLifecycleRepository {
  return {
    listNodes: () => cached(scope, "nodes", () => repository.listNodes()),
    listClimateChamberChannels: (chamberId) =>
      cached(scope, `chamber:${encodeURIComponent(chamberId)}`, () =>
        repository.listClimateChamberChannels(chamberId),
      ),
    listImages: (equipmentId) =>
      cached(scope, `equipment:${encodeURIComponent(equipmentId)}:images`, () =>
        repository.listImages(equipmentId),
      ),
    retireImage: async (equipmentId, imageId, expectedVersion) => {
      const result = await repository.retireImage(equipmentId, imageId, expectedVersion);
      invalidateRefrigerationStructuralCache(scope, equipmentId);
      return result;
    },
    listBindings: (equipmentId, includeHistory) =>
      cached(
        scope,
        `equipment:${encodeURIComponent(equipmentId)}:bindings:${includeHistory ? "history" : "active"}`,
        () => repository.listBindings(equipmentId, includeHistory),
      ),
    listAvailableSensors: (equipmentId) =>
      cached(scope, `equipment:${encodeURIComponent(equipmentId)}:available`, () =>
        repository.listAvailableSensors(equipmentId),
      ),
    replaceSensorConfiguration: async (...args) => {
      const result = await repository.replaceSensorConfiguration(...args);
      invalidateRefrigerationStructuralCache(scope, args[0]);
      return result;
    },
    bindSensor: async (...args) => {
      const result = await repository.bindSensor(...args);
      invalidateRefrigerationStructuralCache(scope, args[0]);
      return result;
    },
    unbindSensor: async (...args) => {
      const result = await repository.unbindSensor(...args);
      invalidateRefrigerationStructuralCache(scope, args[0]);
      return result;
    },
  };
}

export function createCachedLayoutRepository(
  repository: RefrigerationLayoutRepository,
  scope: string,
): RefrigerationLayoutRepository {
  const draftKey = (equipmentId: string) => `equipment:${encodeURIComponent(equipmentId)}:layout:draft`;
  const publishedKey = (equipmentId: string) =>
    `equipment:${encodeURIComponent(equipmentId)}:layout:published`;
  const historyKey = (equipmentId: string) => `equipment:${encodeURIComponent(equipmentId)}:layout:history`;

  const invalidate = (equipmentId: string) => invalidateRefrigerationStructuralCache(scope, equipmentId);

  return {
    getDraft: (equipmentId) => cached(scope, draftKey(equipmentId), () => repository.getDraft(equipmentId)),
    getPublished: (equipmentId) =>
      cached(scope, publishedKey(equipmentId), () => repository.getPublished(equipmentId)),
    listHistory: (equipmentId) =>
      cached(scope, historyKey(equipmentId), () => repository.listHistory(equipmentId)),
    saveDraft: async (input: SaveLayoutDraftInput) => {
      const result = await repository.saveDraft(input);
      if (result.ok) invalidate(input.equipmentId);
      return result;
    },
    publishDraft: async (input: PublishLayoutDraftInput) => {
      const result = await repository.publishDraft(input);
      if (result.ok) invalidate(input.equipmentId);
      return result;
    },
    restoreRevision: async (input: RestoreLayoutRevisionInput) => {
      const result = await repository.restoreRevision(input);
      if (result.ok) invalidate(input.equipmentId);
      return result;
    },
    uploadImage: async (input: UploadEquipmentImageInput) => {
      const result = await repository.uploadImage(input);
      if (result.ok) invalidate(input.equipmentId);
      return result;
    },
  };
}

export type StructuralCacheInspection = {
  scopes: number;
  entries: number;
  inflight: number;
};

export function inspectRefrigerationStructuralCache(): StructuralCacheInspection {
  let entries = 0;
  let inflight = 0;
  for (const current of buckets.values()) {
    entries += current.values.size;
    inflight += current.inflight.size;
  }
  return { scopes: buckets.size, entries, inflight };
}
