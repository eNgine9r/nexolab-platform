import type { EquipmentImageMetadata, SensorSide } from "@/data/refrigeration";
import { equipmentEtag, parseEquipment, type RefrigerationEquipmentRepositoryError } from "./equipment-repository";
import type { RefrigerationEquipment } from "@/data/refrigeration";

export type EquipmentNodeOption = {
  nodeId: string;
  displayName: string;
  state: string;
  lastSeenAt: string | null;
};

export type SensorBinding = {
  id: string;
  equipmentId: string;
  nodeId: string;
  channelId: string;
  slotKey: string;
  label: string;
  side: SensorSide;
  shelf: number;
  position: number;
  version: number;
  boundBy: string;
  boundAt: string;
  unboundBy: string | null;
  unboundAt: string | null;
};

export type AvailableSensor = {
  channelId: string;
  metric: string;
  unit: string;
  latestValue: number | null;
  quality: string;
  capturedAt: string;
  isBound: boolean;
  boundEquipmentId: string | null;
  boundSlotKey: string | null;
};

export type SensorBindingInput = {
  channelId: string;
  label: string;
  side: SensorSide;
  shelf: number;
  position: number;
};

export type SensorBindingMutation = {
  equipment: RefrigerationEquipment;
  binding: SensorBinding | null;
};

export interface EquipmentLifecycleRepository {
  listNodes(): Promise<EquipmentNodeOption[]>;
  listImages(equipmentId: string): Promise<EquipmentImageMetadata[]>;
  retireImage(
    equipmentId: string,
    imageId: string,
    expectedEquipmentVersion: number,
  ): Promise<EquipmentImageMetadata>;
  listBindings(equipmentId: string, includeHistory?: boolean): Promise<SensorBinding[]>;
  listAvailableSensors(equipmentId: string): Promise<AvailableSensor[]>;
  bindSensor(
    equipmentId: string,
    slotKey: string,
    input: SensorBindingInput,
    expectedEquipmentVersion: number,
  ): Promise<SensorBindingMutation>;
  unbindSensor(
    equipmentId: string,
    slotKey: string,
    expectedEquipmentVersion: number,
  ): Promise<SensorBindingMutation>;
}

export class InMemoryEquipmentLifecycleRepository implements EquipmentLifecycleRepository {
  private readonly bindings = new Map<string, SensorBinding[]>();

  async listNodes(): Promise<EquipmentNodeOption[]> {
    return [
      { nodeId: "edge-lab-01", displayName: "Edge laboratory 01", state: "active", lastSeenAt: null },
      { nodeId: "edge-lab-02", displayName: "Edge laboratory 02", state: "active", lastSeenAt: null },
    ];
  }

  async listImages(): Promise<EquipmentImageMetadata[]> {
    return [];
  }

  async retireImage(): Promise<EquipmentImageMetadata> {
    throw new Error("У demo-режимі немає завантажених історичних фотографій.");
  }

  async listBindings(equipmentId: string, includeHistory = false): Promise<SensorBinding[]> {
    const rows = this.bindings.get(equipmentId) ?? [];
    return rows.filter((item) => includeHistory || item.unboundAt === null).map((item) => ({ ...item }));
  }

  async listAvailableSensors(): Promise<AvailableSensor[]> {
    return Array.from({ length: 48 }, (_, index) => ({
      channelId: `sensor-${index + 1}`,
      metric: "temperature",
      unit: "°C",
      latestValue: Number((1.4 + ((index * 7) % 29) / 10).toFixed(1)),
      quality: "good",
      capturedAt: new Date().toISOString(),
      isBound: false,
      boundEquipmentId: null,
      boundSlotKey: null,
    }));
  }

  async bindSensor(
    equipmentId: string,
    slotKey: string,
    input: SensorBindingInput,
  ): Promise<SensorBindingMutation> {
    const now = new Date().toISOString();
    const current = this.bindings.get(equipmentId) ?? [];
    const history = current.map((item) =>
      item.slotKey === slotKey && item.unboundAt === null
        ? { ...item, version: item.version + 1, unboundAt: now, unboundBy: "demo-operator" }
        : item,
    );
    const binding: SensorBinding = {
      id: globalThis.crypto?.randomUUID?.() ?? `${equipmentId}-${slotKey}-${Date.now()}`,
      equipmentId,
      nodeId: "demo-node",
      channelId: input.channelId,
      slotKey,
      label: input.label,
      side: input.side,
      shelf: input.shelf,
      position: input.position,
      version: 1,
      boundBy: "demo-operator",
      boundAt: now,
      unboundBy: null,
      unboundAt: null,
    };
    this.bindings.set(equipmentId, [...history, binding]);
    throw new Error("Demo binding requires the equipment aggregate supplied by the screen.");
  }

  async unbindSensor(): Promise<SensorBindingMutation> {
    throw new Error("Demo unbind requires the equipment aggregate supplied by the screen.");
  }
}

export class HttpEquipmentLifecycleRepository implements EquipmentLifecycleRepository {
  private readonly apiBaseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: { apiBaseUrl: string; fetchImpl?: typeof fetch }) {
    this.apiBaseUrl = normalizeBaseUrl(options.apiBaseUrl);
    this.fetchImpl = options.fetchImpl ?? fetch.bind(globalThis);
  }

  async listNodes(): Promise<EquipmentNodeOption[]> {
    const payload = asRecord(await this.json("/api/v1/equipment/options/nodes", { method: "GET" }));
    if (!payload || !Array.isArray(payload.items)) throw invalidResponse();
    return payload.items.map(parseNode);
  }

  async listImages(equipmentId: string): Promise<EquipmentImageMetadata[]> {
    const payload = asRecord(
      await this.json(`/api/v1/equipment/${encodeURIComponent(equipmentId)}/images`, { method: "GET" }),
    );
    if (!payload || !Array.isArray(payload.items)) throw invalidResponse();
    return payload.items.map(parseImage);
  }

  async retireImage(
    equipmentId: string,
    imageId: string,
    expectedEquipmentVersion: number,
  ): Promise<EquipmentImageMetadata> {
    return parseImage(
      await this.json(
        `/api/v1/equipment/${encodeURIComponent(equipmentId)}/images/${encodeURIComponent(imageId)}`,
        {
          method: "DELETE",
          headers: {
            "If-Match": equipmentEtag(expectedEquipmentVersion),
            "X-Audit-Reason": "Retired refrigeration equipment image",
          },
        },
      ),
    );
  }

  async listBindings(equipmentId: string, includeHistory = false): Promise<SensorBinding[]> {
    const payload = asRecord(
      await this.json(
        `/api/v1/equipment/${encodeURIComponent(equipmentId)}/sensor-bindings${includeHistory ? "?include_history=true" : ""}`,
        { method: "GET" },
      ),
    );
    if (!payload || !Array.isArray(payload.items)) throw invalidResponse();
    return payload.items.map(parseBinding);
  }

  async listAvailableSensors(equipmentId: string): Promise<AvailableSensor[]> {
    const payload = asRecord(
      await this.json(`/api/v1/equipment/${encodeURIComponent(equipmentId)}/available-sensors`, {
        method: "GET",
      }),
    );
    if (!payload || !Array.isArray(payload.items)) throw invalidResponse();
    return payload.items.map(parseAvailableSensor);
  }

  async bindSensor(
    equipmentId: string,
    slotKey: string,
    input: SensorBindingInput,
    expectedEquipmentVersion: number,
  ): Promise<SensorBindingMutation> {
    return parseMutation(
      await this.json(
        `/api/v1/equipment/${encodeURIComponent(equipmentId)}/sensor-bindings/${encodeURIComponent(slotKey)}`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
            "If-Match": equipmentEtag(expectedEquipmentVersion),
            "X-Audit-Reason": "Bound refrigeration equipment sensor",
          },
          body: JSON.stringify({
            channel_id: input.channelId,
            label: input.label,
            side: input.side,
            shelf: input.shelf,
            position: input.position,
          }),
        },
      ),
    );
  }

  async unbindSensor(
    equipmentId: string,
    slotKey: string,
    expectedEquipmentVersion: number,
  ): Promise<SensorBindingMutation> {
    return parseMutation(
      await this.json(
        `/api/v1/equipment/${encodeURIComponent(equipmentId)}/sensor-bindings/${encodeURIComponent(slotKey)}`,
        {
          method: "DELETE",
          headers: {
            "If-Match": equipmentEtag(expectedEquipmentVersion),
            "X-Audit-Reason": "Unbound refrigeration equipment sensor",
          },
        },
      ),
    );
  }

  private async json(path: string, init: RequestInit): Promise<unknown> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.apiBaseUrl}${path}`, {
        ...init,
        credentials: init.credentials ?? "same-origin",
        headers: { Accept: "application/json", ...init.headers },
      });
    } catch {
      throw new Error("Не вдалося з’єднатися з lifecycle API холодильного обладнання.");
    }
    const payload = await readJson(response);
    if (!response.ok) {
      const detail = asRecord(asRecord(payload)?.detail);
      const error = new Error(readString(detail?.message) ?? "Lifecycle-операцію не виконано.");
      (error as Error & { code?: string; status?: number }).code =
        readString(detail?.code) ?? "request_failed";
      (error as Error & { code?: string; status?: number }).status = response.status;
      throw error;
    }
    return payload;
  }
}

function parseMutation(value: unknown): SensorBindingMutation {
  const record = asRecord(value);
  if (!record) throw invalidResponse();
  return {
    equipment: parseEquipment(record.equipment),
    binding: record.binding === null ? null : parseBinding(record.binding),
  };
}

function parseNode(value: unknown): EquipmentNodeOption {
  const record = asRecord(value);
  const nodeId = readString(record?.node_id);
  const displayName = readString(record?.display_name);
  const state = readString(record?.state);
  if (!nodeId || !displayName || !state) throw invalidResponse();
  return {
    nodeId,
    displayName,
    state,
    lastSeenAt: readOptionalString(record?.last_seen_at),
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
    (mimeType !== "image/jpeg" && mimeType !== "image/png" && mimeType !== "image/webp") ||
    widthPx === null ||
    heightPx === null ||
    sizeBytes === null ||
    !sourceUrl ||
    !updatedAt
  ) {
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
  const id = readString(record?.id);
  const equipmentId = readString(record?.equipment_id);
  const nodeId = readString(record?.node_id);
  const channelId = readString(record?.channel_id);
  const slotKey = readString(record?.slot_key);
  const label = readString(record?.label);
  const side = record?.side;
  const shelf = readInteger(record?.shelf);
  const position = readInteger(record?.position);
  const version = readInteger(record?.version);
  const boundBy = readString(record?.bound_by);
  const boundAt = readString(record?.bound_at);
  if (
    !id ||
    !equipmentId ||
    !nodeId ||
    !channelId ||
    !slotKey ||
    !label ||
    (side !== "front" && side !== "rear") ||
    shelf === null ||
    position === null ||
    version === null ||
    !boundBy ||
    !boundAt
  ) {
    throw invalidResponse();
  }
  return {
    id,
    equipmentId,
    nodeId,
    channelId,
    slotKey,
    label,
    side,
    shelf,
    position,
    version,
    boundBy,
    boundAt,
    unboundBy: readOptionalString(record?.unbound_by),
    unboundAt: readOptionalString(record?.unbound_at),
  };
}

function parseAvailableSensor(value: unknown): AvailableSensor {
  const record = asRecord(value);
  const channelId = readString(record?.channel_id);
  const metric = readString(record?.metric);
  const unit = readString(record?.unit);
  const quality = readString(record?.quality);
  const capturedAt = readString(record?.captured_at);
  if (!channelId || !metric || !unit || !quality || !capturedAt) throw invalidResponse();
  return {
    channelId,
    metric,
    unit,
    latestValue: readNullableNumber(record?.latest_value),
    quality,
    capturedAt,
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

function invalidResponse(): Error {
  return new Error("Сервер повернув некоректні lifecycle-дані холодильного обладнання.");
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readOptionalString(value: unknown): string | null {
  return value === null || value === undefined ? null : readString(value);
}

function readInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function readNullableNumber(value: unknown): number | null {
  return value === null || value === undefined
    ? null
    : typeof value === "number" && Number.isFinite(value)
      ? value
      : null;
}
