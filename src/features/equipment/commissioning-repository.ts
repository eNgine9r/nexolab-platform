export type CommissioningLifecycle =
  "draft" | "ready_for_preflight" | "blocked" | "unsupported" | "cancelled";

export type SupportedDeviceProfile = {
  id: string;
  version: string;
  deviceFamily: string;
  deviceClass: string;
  manufacturer: string;
  models: string[];
  displayName: string;
  transportKind: "modbus_rtu";
  capabilityStatus: "repository_supported" | "repository_supported_hardware_evidenced";
  evidenceNote: string;
  readOnly: true;
};

export type CommissioningSession = {
  id: string;
  lifecycle: CommissioningLifecycle;
  deviceClass: string;
  manufacturer: string;
  model: string;
  profileId: string | null;
  profileVersion: string | null;
  transportKind: string | null;
  nodeId: string | null;
  busId: string | null;
  stableTransportIdentifier: string | null;
  unitId: number | null;
  ipAddress: string | null;
  targetEquipmentKey: string | null;
  blockedReason: string | null;
  unsupportedReason: string | null;
  version: number;
  createdBy: string;
  updatedBy: string;
  createdAt: string;
  updatedAt: string;
  cancelledAt: string | null;
};

export type CommissioningSessionWrite = {
  deviceClass: string;
  manufacturer: string;
  model: string;
  profileId: string | null;
  nodeId: string | null;
  busId: string | null;
  stableTransportIdentifier: string | null;
  unitId: number | null;
  ipAddress: string | null;
  targetEquipmentKey: string | null;
};

export type CommissioningSessionPatch = Partial<CommissioningSessionWrite>;

export function createCommissioningIdempotencyKey(source?: {
  randomUUID?: () => string;
  getRandomValues?: (bytes: Uint8Array) => Uint8Array;
}): string {
  let random: string | undefined;
  try {
    random = source ? source.randomUUID?.() : globalThis.crypto?.randomUUID?.();
  } catch {
    random = undefined;
  }
  const bytes = new Uint8Array(16);
  if (!random && source?.getRandomValues) {
    random = Array.from(source.getRandomValues(bytes), hexadecimalByte).join("");
  } else if (!random && globalThis.crypto?.getRandomValues) {
    random = Array.from(globalThis.crypto.getRandomValues(bytes), hexadecimalByte).join("");
  }
  random ??= `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `commissioning-${random}`;
}

export interface CommissioningRepository {
  listProfiles(signal?: AbortSignal): Promise<SupportedDeviceProfile[]>;
  getProfile(profileId: string, signal?: AbortSignal): Promise<SupportedDeviceProfile>;
  listSessions(signal?: AbortSignal): Promise<CommissioningSession[]>;
  getSession(sessionId: string, signal?: AbortSignal): Promise<CommissioningSession>;
  createSession(input: CommissioningSessionWrite, idempotencyKey: string): Promise<CommissioningSession>;
  updateSession(
    sessionId: string,
    input: CommissioningSessionPatch,
    expectedVersion: number,
  ): Promise<CommissioningSession>;
  cancelSession(sessionId: string, expectedVersion: number): Promise<CommissioningSession>;
}

export class CommissioningRepositoryError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number | null = null,
  ) {
    super(message);
    this.name = "CommissioningRepositoryError";
  }
}

export class HttpCommissioningRepository implements CommissioningRepository {
  private readonly apiBaseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: { apiBaseUrl: string; fetchImpl?: typeof fetch }) {
    this.apiBaseUrl = options.apiBaseUrl.replace(/\/+$/, "");
    this.fetchImpl = options.fetchImpl ?? fetch.bind(globalThis);
  }

  async listProfiles(signal?: AbortSignal): Promise<SupportedDeviceProfile[]> {
    const value = record(await this.request("/api/v1/equipment/commissioning/profiles", { signal }));
    if (!value || !Array.isArray(value.items)) throw invalidResponse();
    return value.items.map(parseProfile);
  }

  async getProfile(profileId: string, signal?: AbortSignal): Promise<SupportedDeviceProfile> {
    return parseProfile(
      await this.request(`/api/v1/equipment/commissioning/profiles/${encodeURIComponent(profileId)}`, {
        signal,
      }),
    );
  }

  async listSessions(signal?: AbortSignal): Promise<CommissioningSession[]> {
    const value = record(await this.request("/api/v1/equipment/commissioning/sessions", { signal }));
    if (!value || !Array.isArray(value.items)) throw invalidResponse();
    return value.items.map(parseSession);
  }

  async getSession(sessionId: string, signal?: AbortSignal): Promise<CommissioningSession> {
    return parseSession(
      await this.request(`/api/v1/equipment/commissioning/sessions/${encodeURIComponent(sessionId)}`, {
        signal,
      }),
    );
  }

  async createSession(
    input: CommissioningSessionWrite,
    idempotencyKey: string,
  ): Promise<CommissioningSession> {
    return parseSession(
      await this.request("/api/v1/equipment/commissioning/sessions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey,
          "X-Audit-Reason": "Create operator commissioning draft",
        },
        body: JSON.stringify(writePayload(input)),
      }),
    );
  }

  async updateSession(
    sessionId: string,
    input: CommissioningSessionPatch,
    expectedVersion: number,
  ): Promise<CommissioningSession> {
    return parseSession(
      await this.request(`/api/v1/equipment/commissioning/sessions/${encodeURIComponent(sessionId)}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "If-Match": etag(expectedVersion),
          "X-Audit-Reason": "Update operator commissioning draft",
        },
        body: JSON.stringify(writePayload(input)),
      }),
    );
  }

  async cancelSession(sessionId: string, expectedVersion: number): Promise<CommissioningSession> {
    return parseSession(
      await this.request(`/api/v1/equipment/commissioning/sessions/${encodeURIComponent(sessionId)}/cancel`, {
        method: "POST",
        headers: {
          "If-Match": etag(expectedVersion),
          "X-Audit-Reason": "Cancel operator commissioning draft",
        },
      }),
    );
  }

  private async request(path: string, init: RequestInit = {}): Promise<unknown> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.apiBaseUrl}${path}`, {
        ...init,
        credentials: init.credentials ?? "same-origin",
        headers: { Accept: "application/json", ...init.headers },
      });
    } catch {
      throw new CommissioningRepositoryError(
        "Не вдалося з’єднатися з локальним сервісом комісіонування.",
        "request_failed",
      );
    }
    const payload = await readJson(response);
    if (!response.ok) {
      const detail = record(record(payload)?.detail);
      throw new CommissioningRepositoryError(
        typeof detail?.message === "string" ? detail.message : "Чернетку комісіонування не збережено.",
        typeof detail?.code === "string" ? detail.code : "request_failed",
        response.status,
      );
    }
    return payload;
  }
}

function etag(version: number): string {
  return `W/"commissioning-session-v${version}"`;
}

function hexadecimalByte(value: number): string {
  return value.toString(16).padStart(2, "0");
}

function writePayload(input: CommissioningSessionPatch): Record<string, unknown> {
  const mapping: Record<keyof CommissioningSessionWrite, string> = {
    deviceClass: "device_class",
    manufacturer: "manufacturer",
    model: "model",
    profileId: "profile_id",
    nodeId: "node_id",
    busId: "bus_id",
    stableTransportIdentifier: "stable_transport_identifier",
    unitId: "unit_id",
    ipAddress: "ip_address",
    targetEquipmentKey: "target_equipment_key",
  };
  return Object.fromEntries(
    (Object.keys(mapping) as (keyof CommissioningSessionWrite)[])
      .filter((key) => Object.prototype.hasOwnProperty.call(input, key))
      .map((key) => [mapping[key], input[key]]),
  );
}

function parseProfile(value: unknown): SupportedDeviceProfile {
  const item = record(value);
  if (
    !item ||
    typeof item.id !== "string" ||
    typeof item.version !== "string" ||
    typeof item.device_family !== "string" ||
    typeof item.device_class !== "string" ||
    typeof item.manufacturer !== "string" ||
    !Array.isArray(item.models) ||
    !item.models.every((model) => typeof model === "string") ||
    typeof item.display_name !== "string" ||
    item.transport_kind !== "modbus_rtu" ||
    (item.capability_status !== "repository_supported" &&
      item.capability_status !== "repository_supported_hardware_evidenced") ||
    typeof item.evidence_note !== "string" ||
    item.read_only !== true
  ) {
    throw invalidResponse();
  }
  return {
    id: item.id,
    version: item.version,
    deviceFamily: item.device_family,
    deviceClass: item.device_class,
    manufacturer: item.manufacturer,
    models: item.models as string[],
    displayName: item.display_name,
    transportKind: "modbus_rtu",
    capabilityStatus: item.capability_status,
    evidenceNote: item.evidence_note,
    readOnly: true,
  };
}

function parseSession(value: unknown): CommissioningSession {
  const item = record(value);
  const lifecycle = item?.lifecycle;
  if (
    !item ||
    typeof item.id !== "string" ||
    !["draft", "ready_for_preflight", "blocked", "unsupported", "cancelled"].includes(String(lifecycle)) ||
    typeof item.device_class !== "string" ||
    typeof item.manufacturer !== "string" ||
    typeof item.model !== "string" ||
    typeof item.version !== "number" ||
    typeof item.created_by !== "string" ||
    typeof item.updated_by !== "string" ||
    typeof item.created_at !== "string" ||
    typeof item.updated_at !== "string"
  ) {
    throw invalidResponse();
  }
  return {
    id: item.id,
    lifecycle: lifecycle as CommissioningLifecycle,
    deviceClass: item.device_class,
    manufacturer: item.manufacturer,
    model: item.model,
    profileId: nullableString(item.profile_id),
    profileVersion: nullableString(item.profile_version),
    transportKind: nullableString(item.transport_kind),
    nodeId: nullableString(item.node_id),
    busId: nullableString(item.bus_id),
    stableTransportIdentifier: nullableString(item.stable_transport_identifier),
    unitId: item.unit_id === null ? null : number(item.unit_id),
    ipAddress: nullableString(item.ip_address),
    targetEquipmentKey: nullableString(item.target_equipment_key),
    blockedReason: nullableString(item.blocked_reason),
    unsupportedReason: nullableString(item.unsupported_reason),
    version: item.version,
    createdBy: item.created_by,
    updatedBy: item.updated_by,
    createdAt: item.created_at,
    updatedAt: item.updated_at,
    cancelledAt: nullableString(item.cancelled_at),
  };
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function nullableString(value: unknown): string | null {
  if (value === null) return null;
  if (typeof value !== "string") throw invalidResponse();
  return value;
}

function number(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) throw invalidResponse();
  return value;
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function invalidResponse(): CommissioningRepositoryError {
  return new CommissioningRepositoryError(
    "Локальний сервіс повернув некоректний контракт комісіонування.",
    "invalid_response",
  );
}
