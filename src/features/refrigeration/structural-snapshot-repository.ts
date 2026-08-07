import type { EquipmentImageMetadata, RefrigerationEquipment } from "@/data/refrigeration";

import type { AvailableSensor, SensorBinding } from "./equipment-lifecycle-repository";
import { parseEquipment } from "./equipment-repository";
import { draftEtag, type RefrigerationLayoutDraft } from "./layout-repository";

export type StructuralSampleState = "known" | "stale" | "unknown";

export type StructuralChannel = AvailableSensor & {
  sampleState: StructuralSampleState;
};

export type RefrigerationStructuralSnapshot = {
  equipment: RefrigerationEquipment;
  activeImage: EquipmentImageMetadata | null;
  layout: RefrigerationLayoutDraft;
  layoutRevision: number;
  placementsCount: number;
  bindings: SensorBinding[];
  channels: StructuralChannel[];
  generatedAt: string;
};

export interface RefrigerationStructuralSnapshotRepository {
  get(equipmentId: string): Promise<RefrigerationStructuralSnapshot>;
  invalidate(equipmentId: string): void;
  clear(): void;
}

type Entry = {
  value: RefrigerationStructuralSnapshot;
  storedAt: number;
  touchedAt: number;
};

type ScopeCache = {
  values: Map<string, Entry>;
  inflight: Map<string, Promise<RefrigerationStructuralSnapshot>>;
  requests: Map<string, number>;
};

const FRESH_TTL_MS = 30_000;
const STALE_TTL_MS = 5 * 60_000;
const MAX_ENTRIES = 32;
const caches = new Map<string, ScopeCache>();

export class HttpRefrigerationStructuralSnapshotRepository implements RefrigerationStructuralSnapshotRepository {
  private readonly apiBaseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly scope: string;

  constructor(options: { apiBaseUrl: string; scope: string; fetchImpl?: typeof fetch }) {
    this.apiBaseUrl = normalizeBaseUrl(options.apiBaseUrl);
    this.fetchImpl = options.fetchImpl ?? fetch.bind(globalThis);
    this.scope = options.scope;
  }

  get(equipmentId: string): Promise<RefrigerationStructuralSnapshot> {
    const cache = getScope(this.scope);
    const now = Date.now();
    const stored = cache.values.get(equipmentId);
    if (stored && now - stored.storedAt <= FRESH_TTL_MS) {
      stored.touchedAt = now;
      return Promise.resolve(stored.value);
    }
    if (stored && now - stored.storedAt <= STALE_TTL_MS) {
      stored.touchedAt = now;
      void this.revalidate(equipmentId);
      return Promise.resolve(stored.value);
    }
    return this.revalidate(equipmentId);
  }

  invalidate(equipmentId: string): void {
    getScope(this.scope).values.delete(equipmentId);
  }

  clear(): void {
    caches.delete(this.scope);
  }

  private revalidate(equipmentId: string): Promise<RefrigerationStructuralSnapshot> {
    const cache = getScope(this.scope);
    const existing = cache.inflight.get(equipmentId);
    if (existing) return existing;

    cache.requests.set(equipmentId, (cache.requests.get(equipmentId) ?? 0) + 1);
    const request = this.load(equipmentId)
      .then((value) => {
        const now = Date.now();
        cache.values.set(equipmentId, { value, storedAt: now, touchedAt: now });
        trim(cache);
        return value;
      })
      .finally(() => {
        cache.inflight.delete(equipmentId);
      });
    cache.inflight.set(equipmentId, request);
    return request;
  }

  private async load(equipmentId: string): Promise<RefrigerationStructuralSnapshot> {
    let response: Response;
    try {
      response = await this.fetchImpl(
        `${this.apiBaseUrl}/api/v1/equipment/${encodeURIComponent(equipmentId)}/structural-snapshot`,
        {
          method: "GET",
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        },
      );
    } catch {
      throw new Error("Не вдалося з’єднатися зі structural snapshot API.");
    }
    const payload: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = asRecord(asRecord(payload)?.detail);
      throw new Error(readString(detail?.message) ?? "Structural snapshot недоступний.");
    }
    return parseSnapshot(payload, equipmentId);
  }
}

export function inspectStructuralSnapshotRequests(scope: string, equipmentId: string): number {
  return caches.get(scope)?.requests.get(equipmentId) ?? 0;
}

export function clearStructuralSnapshotScope(scope: string): void {
  caches.delete(scope);
}

function getScope(scope: string): ScopeCache {
  let cache = caches.get(scope);
  if (!cache) {
    cache = { values: new Map(), inflight: new Map(), requests: new Map() };
    caches.set(scope, cache);
  }
  return cache;
}

function trim(cache: ScopeCache): void {
  if (cache.values.size <= MAX_ENTRIES) return;
  const oldest = [...cache.values.entries()]
    .sort((left, right) => left[1].touchedAt - right[1].touchedAt)
    .slice(0, cache.values.size - MAX_ENTRIES);
  for (const [equipmentId] of oldest) cache.values.delete(equipmentId);
}

function parseSnapshot(value: unknown, equipmentId: string): RefrigerationStructuralSnapshot {
  const record = asRecord(value);
  if (!record || !Array.isArray(record.bindings) || !Array.isArray(record.channels)) {
    throw invalidResponse();
  }
  const generatedAt = readString(record.generated_at);
  const layoutRevision = readPositiveInteger(record.layout_revision);
  const placementsCount = readInteger(record.placements_count);
  if (!generatedAt || layoutRevision === null || placementsCount === null) throw invalidResponse();
  const layout = parseDraft(record.layout, equipmentId);
  return {
    equipment: parseEquipment(record.equipment),
    activeImage: record.active_image === null ? null : parseImage(record.active_image),
    layout,
    layoutRevision,
    placementsCount,
    bindings: record.bindings.map(parseBinding),
    channels: record.channels.map((item) => parseChannel(item, generatedAt)),
    generatedAt,
  };
}

function parseDraft(value: unknown, equipmentId: string): RefrigerationLayoutDraft {
  const record = asRecord(value);
  const id = readString(record?.id);
  const responseEquipmentId = readString(record?.equipment_id);
  const version = readPositiveInteger(record?.version);
  const createdAt = readString(record?.created_at);
  const updatedAt = readString(record?.updated_at);
  if (
    !record ||
    !id ||
    responseEquipmentId !== equipmentId ||
    version === null ||
    !createdAt ||
    !updatedAt ||
    !Array.isArray(record.placements)
  ) {
    throw invalidResponse();
  }
  const image = record.image === null ? null : parseImage(record.image);
  return {
    id,
    equipmentId,
    version,
    etag: draftEtag(version),
    imageId: image?.id ?? null,
    image,
    placements: record.placements.map((item) => {
      const placement = asRecord(item);
      const sensorId = readString(placement?.sensor_id);
      const x = readNumber(placement?.x);
      const y = readNumber(placement?.y);
      if (!sensorId || x === null || y === null) throw invalidResponse();
      return { sensorId, x, y };
    }),
    createdAt,
    updatedAt,
  };
}

function parseImage(value: unknown): EquipmentImageMetadata {
  const record = asRecord(value);
  const id = readString(record?.id);
  const fileName = readString(record?.original_filename);
  const mimeType = readString(record?.media_type);
  const widthPx = readInteger(record?.width_px);
  const heightPx = readInteger(record?.height_px);
  const sizeBytes = readInteger(record?.size_bytes);
  const sourceUrl = readString(record?.content_url);
  const updatedAt = readString(record?.created_at);
  if (
    !id ||
    !fileName ||
    !mimeType ||
    widthPx === null ||
    heightPx === null ||
    sizeBytes === null ||
    !sourceUrl ||
    !updatedAt
  ) {
    throw invalidResponse();
  }
  if (mimeType !== "image/jpeg" && mimeType !== "image/png" && mimeType !== "image/webp") {
    throw invalidResponse();
  }
  return {
    id,
    fileName,
    mimeType,
    widthPx,
    heightPx,
    sizeBytes,
    sourceUrl,
    alt: `Фото холодильного обладнання ${fileName}`,
    updatedAt,
    retiredAt: readOptionalString(record?.retired_at),
    retiredBy: readOptionalString(record?.retired_by),
  };
}

function parseBinding(value: unknown): SensorBinding {
  const record = asRecord(value);
  const side = record?.side;
  const parsed = {
    id: readString(record?.id),
    equipmentId: readString(record?.equipment_id),
    nodeId: readString(record?.node_id),
    channelId: readString(record?.channel_id),
    slotKey: readString(record?.slot_key),
    label: readString(record?.label),
    side,
    shelf: readInteger(record?.shelf),
    position: readInteger(record?.position),
    version: readInteger(record?.version),
    boundBy: readString(record?.bound_by),
    boundAt: readString(record?.bound_at),
    unboundBy: readOptionalString(record?.unbound_by),
    unboundAt: readOptionalString(record?.unbound_at),
  };
  if (
    !parsed.id ||
    !parsed.equipmentId ||
    !parsed.nodeId ||
    !parsed.channelId ||
    !parsed.slotKey ||
    !parsed.label ||
    (side !== "front" && side !== "rear") ||
    parsed.shelf === null ||
    parsed.position === null ||
    parsed.version === null ||
    !parsed.boundBy ||
    !parsed.boundAt
  ) {
    throw invalidResponse();
  }
  return parsed as SensorBinding;
}

function parseChannel(value: unknown, fallbackCapturedAt: string): StructuralChannel {
  const record = asRecord(value);
  const channelId = readString(record?.channel_id);
  const metric = readString(record?.metric);
  const unit = readString(record?.unit);
  const quality = readString(record?.quality);
  const sampleState = record?.sample_state;
  if (
    !channelId ||
    !metric ||
    !unit ||
    !quality ||
    (sampleState !== "known" && sampleState !== "stale" && sampleState !== "unknown")
  ) {
    throw invalidResponse();
  }
  return {
    channelId,
    metric,
    unit,
    latestValue: readNullableNumber(record?.latest_value),
    quality,
    capturedAt: readString(record?.captured_at) ?? fallbackCapturedAt,
    sampleState,
    isBound: record?.is_bound === true,
    boundEquipmentId: readOptionalString(record?.bound_equipment_id),
    boundSlotKey: readOptionalString(record?.bound_slot_key),
  };
}

function normalizeBaseUrl(value: string): string {
  const parsed = new URL(value);
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") throw new Error("Invalid API URL.");
  parsed.hash = "";
  parsed.search = "";
  return parsed.toString().replace(/\/$/, "");
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function readOptionalString(value: unknown): string | null {
  return value === null || value === undefined ? null : readString(value);
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readNullableNumber(value: unknown): number | null {
  return value === null ? null : readNumber(value);
}

function readInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) ? value : null;
}

function readPositiveInteger(value: unknown): number | null {
  const parsed = readInteger(value);
  return parsed !== null && parsed > 0 ? parsed : null;
}

function invalidResponse(): Error {
  return new Error("Structural snapshot API повернув некоректну відповідь.");
}
