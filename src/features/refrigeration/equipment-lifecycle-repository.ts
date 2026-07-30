import type { EquipmentImageMetadata, RefrigerationEquipment, SensorSide } from "@/data/refrigeration";

import { equipmentEtag, parseEquipment } from "./equipment-repository";
import { draftEtag, type RefrigerationLayoutDraft } from "./layout-repository";

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

export type SensorConfigurationItem = SensorBindingInput & {
  slotKey: string;
  x: number;
  y: number;
};

export type SensorConfigurationMutation = {
  equipment: RefrigerationEquipment;
  bindings: SensorBinding[];
  draft: RefrigerationLayoutDraft;
};

export interface EquipmentLifecycleRepository {
  listNodes(): Promise<EquipmentNodeOption[]>;
  listClimateChamberChannels(climateChamberId: string): Promise<AvailableSensor[]>;
  listImages(equipmentId: string): Promise<EquipmentImageMetadata[]>;
  retireImage(
    equipmentId: string,
    imageId: string,
    expectedEquipmentVersion: number,
  ): Promise<EquipmentImageMetadata>;
  listBindings(equipmentId: string, includeHistory?: boolean): Promise<SensorBinding[]>;
  listAvailableSensors(equipmentId: string): Promise<AvailableSensor[]>;
  replaceSensorConfiguration(
    equipmentId: string,
    expectedEquipmentVersion: number,
    expectedDraftVersion: number,
    bindings: readonly SensorConfigurationItem[],
  ): Promise<SensorConfigurationMutation>;
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

export class HttpEquipmentLifecycleRepository implements EquipmentLifecycleRepository {
  private readonly apiBaseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: { apiBaseUrl: string; fetchImpl?: typeof fetch }) {
    this.apiBaseUrl = normalizeBaseUrl(options.apiBaseUrl);
    this.fetchImpl = options.fetchImpl ?? fetch.bind(globalThis);
  }

  async listNodes(): Promise<EquipmentNodeOption[]> {
    const payload = asRecord(
      await this.json("/api/v1/equipment/options/nodes", { method: "GET" }),
    );
    if (!payload || !Array.isArray(payload.items)) throw invalidResponse();
    return payload.items.map(parseNode);
  }

  async listClimateChamberChannels(
    climateChamberId: string,
  ): Promise<AvailableSensor[]> {
    const payload = asRecord(
      await this.json(
        `/api/v1/equipment/options/nodes/${encodeURIComponent(climateChamberId)}/channels`,
        { method: "GET" },
      ),
    );
    // The URL is scoped by the logical climate-chamber identifier. The response
    // deliberately exposes the physical edge node that owns the chamber's bus,
    // so node_id must be valid but must not equal the chamber UUID.
    if (
      !payload ||
      !Array.isArray(payload.items) ||
      !readString(payload.node_id)
    ) {
      throw invalidResponse();
    }
    return payload.items.map(parseAvailableSensor);
  }

  async listImages(equipmentId: string): Promise<EquipmentImageMetadata[]> {
    const payload = asRecord(
      await this.json(`/api/v1/equipment/${encodeURIComponent(equipmentId)}/images`, {
        method: "GET",
      }),
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

  async listBindings(
    equipmentId: string,
    includeHistory = false,
  ): Promise<SensorBinding[]> {
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
      await this.json(
        `/api/v1/equipment/${encodeURIComponent(equipmentId)}/available-sensors`,
        { method: "GET" },
      ),
    );
    if (!payload || !Array.isArray(payload.items)) throw invalidResponse();
    return payload.items.map(parseAvailableSensor);
  }

  async replaceSensorConfiguration(
    equipmentId: string,
    expectedEquipmentVersion: number,
    expectedDraftVersion: number,
    bindings: readonly SensorConfigurationItem[],
  ): Promise<SensorConfigurationMutation> {
    const payload = asRecord(
      await this.json(
        `/api/v1/equipment/${encodeURIComponent(equipmentId)}/sensor-configuration`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
            "If-Match": equipmentEtag(expectedEquipmentVersion),
            "X-Audit-Reason": "Updated climate chamber sensor configuration",
          },
          body: JSON.stringify({
            expected_draft_version: expectedDraftVersion,
            bindings: bindings.map((item) => ({
              slot_key: item.slotKey,
              channel_id: item.channelId,
              label: item.label,
              side: item.side,
              shelf: item.shelf,
              position: item.position,
              x: item.x,
              y: item.y,
            })),
          }),
        },
      ),
    );
    if (!payload || !Array.isArray(payload.bindings)) throw invalidResponse();
    return {
      equipment: parseEquipment(payload.equipment),
      bindings: payload.bindings.map(parseBinding),
      draft: parseDraft(payload.draft, equipmentId),
    };
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
      const error = new Error(
        readString(detail?.message) ?? "Lifecycle-операцію не виконано.",
      );
      (
        error as Error & {
          code?: string;
          status?: number;
          expectedVersion?: number;
          actualVersion?: number;
        }
      ).code = readString(detail?.code) ?? "request_failed";
      (error as Error & { code?: string; status?: number }).status = response.status;
      (error as Error & { expectedVersion?: number }).expectedVersion =
        readInteger(detail?.expected_version) ?? undefined;
      (error as Error & { actualVersion?: number }).actualVersion =
        readInteger(detail?.actual_version) ?? undefined;
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
    (mimeType !== "image/jpeg" &&
      mimeType !== "image/png" &&
      mimeType !== "image/webp") ||
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

function parseDraft(value: unknown, equipmentId: string): RefrigerationLayoutDraft {
  const record = asRecord(value);
  const id = readString(record?.id);
  const responseEquipmentId = readString(record?.equipment_id);
  const version = readPositiveInteger(record?.version);
  const createdAt = readString(record?.created_at);
  const updatedAt = readString(record?.updated_at);
  const image = record?.image === null ? null : parseImage(record?.image);
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
  const sensorIds = new Set<string>();
  const placements = record.placements.map((value) => {
    const placement = asRecord(value);
    const sensorId = readString(placement?.sensor_id);
    const x = readNormalizedNumber(placement?.x);
    const y = readNormalizedNumber(placement?.y);
    if (!sensorId || x === null || y === null || sensorIds.has(sensorId)) {
      throw invalidResponse();
    }
    sensorIds.add(sensorId);
    return { sensorId, x, y };
  });
  return {
    id,
    equipmentId,
    version,
    etag: draftEtag(version),
    imageId: image?.id ?? null,
    image,
    placements,
    createdAt,
    updatedAt,
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
  if (!channelId || !metric || !unit || !quality || !capturedAt) {
    throw invalidResponse();
  }
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
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("Invalid API URL.");
  }
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
  return typeof value === "number" && Number.isInteger(value) && value >= 0
    ? value
    : null;
}

function readPositiveInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 1
    ? value
    : null;
}

function readNormalizedNumber(value: unknown): number | null {
  return typeof value === "number" &&
    Number.isFinite(value) &&
    value >= 0 &&
    value <= 1
    ? value
    : null;
}

function readNullableNumber(value: unknown): number | null {
  return value === null || value === undefined
    ? null
    : typeof value === "number" && Number.isFinite(value)
      ? value
      : null;
}
