export type RefrigerationControllerBinding = {
  id: string;
  equipmentId: string;
  nodeId: string;
  controllerFamily: "embraco";
  controllerEquipmentId: string;
  unitId: number;
  profileVersion: string;
  boundAt: string;
  verifiedFromTelemetry: boolean;
};

export type RefrigerationControllerSummary = {
  equipmentId: string;
  controllerFamily: "embraco";
  controllerEquipmentId: string;
  unitId: number;
  profileVersion: string;
  controlState: number | null;
  compressorSpeedRpm: number | null;
  lastSeenAt: string | null;
};

export interface RefrigerationControllerBindingRepository {
  get(equipmentId: string, signal?: AbortSignal): Promise<RefrigerationControllerBinding | null>;
  listSummaries(signal?: AbortSignal): Promise<RefrigerationControllerSummary[]>;
}

export class HttpRefrigerationControllerBindingRepository implements RefrigerationControllerBindingRepository {
  constructor(
    private readonly apiBaseUrl: string,
    private readonly fetchImpl: typeof fetch = fetch.bind(globalThis),
  ) {}

  async listSummaries(signal?: AbortSignal): Promise<RefrigerationControllerSummary[]> {
    const response = await this.fetchImpl(`${this.apiBaseUrl}/api/v1/equipment/controller-summaries`, {
      method: "GET",
      headers: { Accept: "application/json" },
      credentials: "same-origin",
      signal,
    });
    if (!response.ok) throw new Error("Не вдалося отримати стани контролерів.");
    const payload = await response.json();
    if (!payload || typeof payload !== "object" || !Array.isArray((payload as { items?: unknown }).items)) {
      throw new Error("Некоректна відповідь станів контролерів.");
    }
    return (payload as { items: unknown[] }).items.map(parseSummary);
  }

  async get(equipmentId: string, signal?: AbortSignal): Promise<RefrigerationControllerBinding | null> {
    const response = await this.fetchImpl(
      `${this.apiBaseUrl}/api/v1/equipment/${encodeURIComponent(equipmentId)}/controller-binding`,
      { method: "GET", headers: { Accept: "application/json" }, credentials: "same-origin", signal },
    );
    if (response.status === 404) return null;
    if (!response.ok) throw new Error("Не вдалося отримати прив’язку контролера.");
    return parseBinding(await response.json());
  }
}

function parseBinding(value: unknown): RefrigerationControllerBinding {
  if (!value || typeof value !== "object") throw new Error("Некоректна відповідь прив’язки контролера.");
  const item = value as Record<string, unknown>;
  if (
    typeof item.id !== "string" ||
    typeof item.equipment_id !== "string" ||
    typeof item.node_id !== "string" ||
    item.controller_family !== "embraco" ||
    typeof item.controller_equipment_id !== "string" ||
    typeof item.unit_id !== "number" ||
    typeof item.profile_version !== "string" ||
    typeof item.bound_at !== "string" ||
    typeof item.verified_from_telemetry !== "boolean"
  ) {
    throw new Error("Некоректний контракт прив’язки контролера.");
  }
  return {
    id: item.id,
    equipmentId: item.equipment_id,
    nodeId: item.node_id,
    controllerFamily: "embraco",
    controllerEquipmentId: item.controller_equipment_id,
    unitId: item.unit_id,
    profileVersion: item.profile_version,
    boundAt: item.bound_at,
    verifiedFromTelemetry: item.verified_from_telemetry,
  };
}

function parseSummary(value: unknown): RefrigerationControllerSummary {
  if (!value || typeof value !== "object") throw new Error("Некоректний стан контролера.");
  const item = value as Record<string, unknown>;
  if (
    typeof item.equipment_id !== "string" ||
    item.controller_family !== "embraco" ||
    typeof item.controller_equipment_id !== "string" ||
    typeof item.unit_id !== "number" ||
    typeof item.profile_version !== "string" ||
    (item.control_state !== null && typeof item.control_state !== "number") ||
    (item.compressor_speed_rpm !== null && typeof item.compressor_speed_rpm !== "number") ||
    (item.last_seen_at !== null && typeof item.last_seen_at !== "string")
  ) {
    throw new Error("Некоректний контракт стану контролера.");
  }
  return {
    equipmentId: item.equipment_id,
    controllerFamily: "embraco",
    controllerEquipmentId: item.controller_equipment_id,
    unitId: item.unit_id,
    profileVersion: item.profile_version,
    controlState: item.control_state as number | null,
    compressorSpeedRpm: item.compressor_speed_rpm as number | null,
    lastSeenAt: item.last_seen_at as string | null,
  };
}
