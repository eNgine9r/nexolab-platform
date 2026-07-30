import {
  getRefrigerationEquipment,
  type EquipmentLifecycleStatus,
  type EquipmentStatus,
  type RefrigerationEquipment,
} from "@/data/refrigeration";

export type RefrigerationEquipmentCreateInput = {
  code: string;
  name: string;
  location: string;
  laboratory: string;
  zone: string;
  /** Logical climate chamber id. */
  climateChamberId?: string;
  /** Compatibility alias used by the existing passport form; contains a chamber id, not a node id. */
  nodeId: string;
  type: string;
  manufacturer: string;
  model: string;
  serialNumber: string;
  temperatureClass: string;
  installedAt: string;
  servicedAt: string;
  lifecycleStatus: EquipmentLifecycleStatus;
  totalSensors: number;
};

export type RefrigerationEquipmentUpdateInput = RefrigerationEquipmentCreateInput;

export interface RefrigerationEquipmentRepository {
  list(): Promise<RefrigerationEquipment[]>;
  get(equipmentId: string): Promise<RefrigerationEquipment>;
  create(input: RefrigerationEquipmentCreateInput): Promise<RefrigerationEquipment>;
  update(
    equipmentId: string,
    input: RefrigerationEquipmentUpdateInput,
    expectedVersion: number,
  ): Promise<RefrigerationEquipment>;
  remove(equipmentId: string, expectedVersion: number): Promise<void>;
}

export class RefrigerationEquipmentRepositoryError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number | null = null,
  ) {
    super(message);
    this.name = "RefrigerationEquipmentRepositoryError";
  }
}

export class InMemoryRefrigerationEquipmentRepository implements RefrigerationEquipmentRepository {
  private items: RefrigerationEquipment[];

  constructor(initialItems: RefrigerationEquipment[]) {
    this.items = initialItems.map(cloneEquipment);
  }

  async list(): Promise<RefrigerationEquipment[]> {
    return this.items.map(cloneEquipment);
  }

  async get(equipmentId: string): Promise<RefrigerationEquipment> {
    const item = this.items.find((candidate) => candidate.id === equipmentId);
    if (!item) throw notFound();
    return cloneEquipment(item);
  }

  async create(input: RefrigerationEquipmentCreateInput): Promise<RefrigerationEquipment> {
    const normalized = normalizeInput(input);
    assertUniqueCode(this.items, normalized.code);
    const now = new Date().toISOString();
    const chamberId = selectedChamberId(normalized);
    const item: RefrigerationEquipment = {
      id: createClientId(),
      code: normalized.code,
      name: normalized.name,
      location: normalized.location,
      laboratory: normalized.laboratory || null,
      zone: normalized.zone || null,
      climateChamberId: chamberId || null,
      nodeId: chamberId || null,
      transportNodeId: null,
      type: normalized.type,
      manufacturer: normalized.manufacturer,
      model: normalized.model,
      serialNumber: normalized.serialNumber,
      temperatureClass: normalized.temperatureClass,
      installedAt: normalized.installedAt,
      servicedAt: normalized.servicedAt,
      lifecycleStatus: normalized.lifecycleStatus,
      totalSensors: normalized.totalSensors,
      status: "offline",
      averageTemperatureC: 0,
      minTemperatureC: 0,
      maxTemperatureC: 0,
      onlineSensors: 0,
      activeAlarms: 0,
      lastSeenAt: now,
      version: 1,
      image: null,
      sensors: [],
    };
    this.items = [...this.items, item];
    return cloneEquipment(item);
  }

  async update(
    equipmentId: string,
    input: RefrigerationEquipmentUpdateInput,
    expectedVersion: number,
  ): Promise<RefrigerationEquipment> {
    const index = this.items.findIndex((candidate) => candidate.id === equipmentId);
    if (index < 0) throw notFound();
    const current = this.items[index];
    assertVersion(current, expectedVersion);
    if (current.lifecycleStatus === "retired") {
      throw new RefrigerationEquipmentRepositoryError(
        "Обладнання виведено з експлуатації та доступне лише для перегляду.",
        "equipment_lifecycle_conflict",
        409,
      );
    }
    const normalized = normalizeInput(input);
    assertUniqueCode(this.items, normalized.code, equipmentId);
    const chamberId = selectedChamberId(normalized);
    const updated: RefrigerationEquipment = {
      ...current,
      code: normalized.code,
      name: normalized.name,
      location: normalized.location,
      laboratory: normalized.laboratory || null,
      zone: normalized.zone || null,
      climateChamberId: chamberId || null,
      nodeId: chamberId || null,
      transportNodeId: current.transportNodeId,
      type: normalized.type,
      manufacturer: normalized.manufacturer,
      model: normalized.model,
      serialNumber: normalized.serialNumber,
      temperatureClass: normalized.temperatureClass,
      installedAt: normalized.installedAt,
      servicedAt: normalized.servicedAt,
      lifecycleStatus: normalized.lifecycleStatus,
      totalSensors: normalized.totalSensors,
      status: normalized.lifecycleStatus === "retired" ? "offline" : current.status,
      onlineSensors: normalized.lifecycleStatus === "retired" ? 0 : current.onlineSensors,
      activeAlarms: normalized.lifecycleStatus === "retired" ? 0 : current.activeAlarms,
      version: current.version + 1,
    };
    this.items = this.items.map((item) => (item.id === equipmentId ? updated : item));
    return cloneEquipment(updated);
  }

  async remove(equipmentId: string, expectedVersion: number): Promise<void> {
    const item = this.items.find((candidate) => candidate.id === equipmentId);
    if (!item) throw notFound();
    assertVersion(item, expectedVersion);
    this.items = this.items.filter((candidate) => candidate.id !== equipmentId);
  }
}

export type HttpRefrigerationEquipmentRepositoryOptions = {
  apiBaseUrl: string;
  fetchImpl?: typeof fetch;
};

export class HttpRefrigerationEquipmentRepository implements RefrigerationEquipmentRepository {
  private readonly apiBaseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: HttpRefrigerationEquipmentRepositoryOptions) {
    this.apiBaseUrl = normalizeBaseUrl(options.apiBaseUrl);
    this.fetchImpl = options.fetchImpl ?? fetch.bind(globalThis);
  }

  async list(): Promise<RefrigerationEquipment[]> {
    const response = await this.request("/api/v1/equipment", { method: "GET" });
    const payload = asRecord(await readJson(response));
    if (!payload || !Array.isArray(payload.items)) throw invalidResponse();
    return payload.items.map(parseEquipment);
  }

  async get(equipmentId: string): Promise<RefrigerationEquipment> {
    const response = await this.request(`/api/v1/equipment/${encodeURIComponent(equipmentId)}`, {
      method: "GET",
    });
    return parseEquipment(await readJson(response));
  }

  async create(input: RefrigerationEquipmentCreateInput): Promise<RefrigerationEquipment> {
    const response = await this.request("/api/v1/equipment", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toApiPayload(input)),
    });
    return parseEquipment(await readJson(response));
  }

  async update(
    equipmentId: string,
    input: RefrigerationEquipmentUpdateInput,
    expectedVersion: number,
  ): Promise<RefrigerationEquipment> {
    const response = await this.request(`/api/v1/equipment/${encodeURIComponent(equipmentId)}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "If-Match": equipmentEtag(expectedVersion),
        "X-Audit-Reason": "Updated refrigeration equipment passport",
      },
      body: JSON.stringify(toApiPayload(input)),
    });
    return parseEquipment(await readJson(response));
  }

  async remove(equipmentId: string, expectedVersion: number): Promise<void> {
    await this.request(`/api/v1/equipment/${encodeURIComponent(equipmentId)}`, {
      method: "DELETE",
      headers: {
        "If-Match": equipmentEtag(expectedVersion),
        "X-Audit-Reason": "Removed from refrigeration equipment catalog",
      },
    });
  }

  private async request(path: string, init: RequestInit): Promise<Response> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.apiBaseUrl}${path}`, {
        ...init,
        credentials: init.credentials ?? "same-origin",
        headers: { Accept: "application/json", ...init.headers },
      });
    } catch {
      throw new RefrigerationEquipmentRepositoryError(
        "Не вдалося з’єднатися зі сховищем холодильного обладнання.",
        "request_failed",
      );
    }

    if (!response.ok) {
      const payload = await readJson(response);
      const detail = asRecord(asRecord(payload)?.detail);
      throw new RefrigerationEquipmentRepositoryError(
        readString(detail?.message) ?? "Операцію з холодильним обладнанням не виконано.",
        readString(detail?.code) ?? "request_failed",
        response.status,
      );
    }
    return response;
  }
}

function selectedChamberId(input: RefrigerationEquipmentCreateInput): string {
  return (input.climateChamberId ?? input.nodeId).trim();
}

function normalizeInput(input: RefrigerationEquipmentCreateInput): RefrigerationEquipmentCreateInput {
  return {
    code: input.code.trim(),
    name: input.name.trim(),
    location: input.location.trim(),
    laboratory: input.laboratory.trim(),
    zone: input.zone.trim(),
    climateChamberId: input.climateChamberId?.trim(),
    nodeId: input.nodeId.trim(),
    type: input.type.trim(),
    manufacturer: input.manufacturer.trim(),
    model: input.model.trim(),
    serialNumber: input.serialNumber.trim(),
    temperatureClass: input.temperatureClass.trim(),
    installedAt: input.installedAt,
    servicedAt: input.servicedAt,
    lifecycleStatus: input.lifecycleStatus,
    totalSensors: input.totalSensors,
  };
}

function toApiPayload(input: RefrigerationEquipmentCreateInput) {
  const normalized = normalizeInput(input);
  return {
    code: normalized.code,
    name: normalized.name,
    location: normalized.location,
    laboratory: normalized.laboratory || null,
    zone: normalized.zone || null,
    climate_chamber_id: selectedChamberId(normalized) || null,
    equipment_type: normalized.type,
    manufacturer: normalized.manufacturer,
    model: normalized.model,
    serial_number: normalized.serialNumber,
    temperature_class: normalized.temperatureClass,
    installed_at: normalized.installedAt || null,
    serviced_at: normalized.servicedAt || null,
    lifecycle_status: normalized.lifecycleStatus,
    total_sensors: normalized.totalSensors,
  };
}

export function equipmentEtag(version: number): string {
  return `W/"equipment-v${version}"`;
}

function assertUniqueCode(
  items: RefrigerationEquipment[],
  code: string,
  excludedId: string | null = null,
): void {
  if (
    items.some(
      (item) =>
        item.id !== excludedId &&
        item.code.toLocaleLowerCase("uk-UA") === code.toLocaleLowerCase("uk-UA"),
    )
  ) {
    throw new RefrigerationEquipmentRepositoryError(
      "Обладнання з таким кодом уже існує.",
      "equipment_code_conflict",
      409,
    );
  }
}

function assertVersion(item: RefrigerationEquipment, expectedVersion: number): void {
  if (item.version !== expectedVersion) {
    throw new RefrigerationEquipmentRepositoryError(
      "Запис обладнання вже змінено. Оновіть каталог і повторіть дію.",
      "equipment_version_conflict",
      409,
    );
  }
}

function notFound(): RefrigerationEquipmentRepositoryError {
  return new RefrigerationEquipmentRepositoryError(
    "Холодильне обладнання не знайдено.",
    "equipment_not_found",
    404,
  );
}

export function parseEquipment(value: unknown): RefrigerationEquipment {
  const record = asRecord(value);
  if (!record) throw invalidResponse();

  const id = readString(record.id);
  const code = readString(record.code);
  const name = readString(record.name);
  const location = readString(record.location);
  const type = readString(record.equipment_type);
  const manufacturer = readString(record.manufacturer);
  const model = readString(record.model);
  const serialNumber = readString(record.serial_number);
  const temperatureClass = readString(record.temperature_class);
  const lifecycleStatus = readLifecycleStatus(record.lifecycle_status);
  const status = readStatus(record.status);
  const version = readInteger(record.version);
  const totalSensors = readInteger(record.total_sensors);
  const onlineSensors = readInteger(record.online_sensors);
  const activeAlarms = readInteger(record.active_alarms);
  const averageTemperatureC = readNumber(record.average_temperature_c);
  const minTemperatureC = readNumber(record.min_temperature_c);
  const maxTemperatureC = readNumber(record.max_temperature_c);

  if (
    !id ||
    !code ||
    !name ||
    !location ||
    !type ||
    !manufacturer ||
    !model ||
    !serialNumber ||
    !temperatureClass ||
    !lifecycleStatus ||
    !status ||
    version === null ||
    totalSensors === null ||
    onlineSensors === null ||
    activeAlarms === null ||
    averageTemperatureC === null ||
    minTemperatureC === null ||
    maxTemperatureC === null
  ) {
    throw invalidResponse();
  }

  const fixture = getRefrigerationEquipment(id);
  const climateChamberId = readOptionalString(record.climate_chamber_id);
  return {
    id,
    code,
    name,
    location,
    laboratory: readOptionalString(record.laboratory),
    zone: readOptionalString(record.zone),
    climateChamberId,
    nodeId: climateChamberId,
    transportNodeId: readOptionalString(record.node_id),
    type,
    manufacturer,
    model,
    serialNumber,
    temperatureClass,
    installedAt: readOptionalString(record.installed_at) ?? "",
    servicedAt: readOptionalString(record.serviced_at) ?? "",
    lifecycleStatus,
    status,
    averageTemperatureC,
    minTemperatureC,
    maxTemperatureC,
    onlineSensors,
    totalSensors,
    activeAlarms,
    lastSeenAt:
      readOptionalString(record.last_seen_at) ?? readString(record.updated_at) ?? new Date(0).toISOString(),
    version,
    image: fixture?.image ?? null,
    sensors: fixture?.sensors.map((sensor) => ({ ...sensor, trend: [...sensor.trend] })) ?? [],
  };
}

function cloneEquipment(item: RefrigerationEquipment): RefrigerationEquipment {
  return {
    ...item,
    image: item.image ? { ...item.image } : null,
    sensors: item.sensors.map((sensor) => ({ ...sensor, trend: [...sensor.trend] })),
  };
}

function invalidResponse(): RefrigerationEquipmentRepositoryError {
  return new RefrigerationEquipmentRepositoryError(
    "Сервер повернув некоректний каталог холодильного обладнання.",
    "invalid_response",
  );
}

function normalizeBaseUrl(value: string): string {
  const parsed = new URL(value);
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("NEXOLAB API URL must use HTTP or HTTPS.");
  }
  parsed.hash = "";
  parsed.search = "";
  return parsed.toString().replace(/\/$/, "");
}

function createClientId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `equipment-${Date.now()}-${Math.random().toString(16).slice(2)}`;
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

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function readStatus(value: unknown): EquipmentStatus | null {
  return value === "normal" || value === "warning" || value === "alarm" || value === "offline"
    ? value
    : null;
}

function readLifecycleStatus(value: unknown): EquipmentLifecycleStatus | null {
  return value === "active" || value === "maintenance" || value === "retired" ? value : null;
}
