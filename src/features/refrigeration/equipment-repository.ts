import {
  getRefrigerationEquipment,
  type EquipmentStatus,
  type RefrigerationEquipment,
} from "@/data/refrigeration";

export type RefrigerationEquipmentCreateInput = {
  code: string;
  name: string;
  location: string;
  type: string;
  manufacturer: string;
  model: string;
  serialNumber: string;
  temperatureClass: string;
  installedAt: string;
  servicedAt: string;
  totalSensors: number;
};

export interface RefrigerationEquipmentRepository {
  list(): Promise<RefrigerationEquipment[]>;
  get(equipmentId: string): Promise<RefrigerationEquipment>;
  create(input: RefrigerationEquipmentCreateInput): Promise<RefrigerationEquipment>;
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
    if (!item) {
      throw new RefrigerationEquipmentRepositoryError(
        "Холодильне обладнання не знайдено.",
        "equipment_not_found",
        404,
      );
    }
    return cloneEquipment(item);
  }

  async create(input: RefrigerationEquipmentCreateInput): Promise<RefrigerationEquipment> {
    const normalizedCode = input.code.trim();
    if (this.items.some((item) => item.code.toLocaleLowerCase("uk-UA") === normalizedCode.toLocaleLowerCase("uk-UA"))) {
      throw new RefrigerationEquipmentRepositoryError(
        "Обладнання з таким кодом уже існує.",
        "equipment_code_conflict",
        409,
      );
    }
    const now = new Date().toISOString();
    const item: RefrigerationEquipment = {
      id: createClientId(),
      code: normalizedCode,
      name: input.name.trim(),
      location: input.location.trim(),
      type: input.type.trim(),
      manufacturer: input.manufacturer.trim(),
      model: input.model.trim(),
      serialNumber: input.serialNumber.trim(),
      temperatureClass: input.temperatureClass.trim(),
      installedAt: input.installedAt,
      servicedAt: input.servicedAt,
      status: "offline",
      averageTemperatureC: 0,
      minTemperatureC: 0,
      maxTemperatureC: 0,
      onlineSensors: 0,
      totalSensors: input.totalSensors,
      activeAlarms: 0,
      lastSeenAt: now,
      version: 1,
      image: null,
      sensors: [],
    };
    this.items = [...this.items, item];
    return cloneEquipment(item);
  }

  async remove(equipmentId: string, expectedVersion: number): Promise<void> {
    const item = this.items.find((candidate) => candidate.id === equipmentId);
    if (!item) {
      throw new RefrigerationEquipmentRepositoryError(
        "Холодильне обладнання не знайдено.",
        "equipment_not_found",
        404,
      );
    }
    if (item.version !== expectedVersion) {
      throw new RefrigerationEquipmentRepositoryError(
        "Запис обладнання вже змінено. Оновіть каталог і повторіть дію.",
        "equipment_version_conflict",
        409,
      );
    }
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
    if (!payload || !Array.isArray(payload.items)) {
      throw invalidResponse();
    }
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
      body: JSON.stringify({
        code: input.code,
        name: input.name,
        location: input.location,
        equipment_type: input.type,
        manufacturer: input.manufacturer,
        model: input.model,
        serial_number: input.serialNumber,
        temperature_class: input.temperatureClass,
        installed_at: input.installedAt || null,
        serviced_at: input.servicedAt || null,
        total_sensors: input.totalSensors,
      }),
    });
    return parseEquipment(await readJson(response));
  }

  async remove(equipmentId: string, expectedVersion: number): Promise<void> {
    await this.request(`/api/v1/equipment/${encodeURIComponent(equipmentId)}`, {
      method: "DELETE",
      headers: {
        "If-Match": `W/\"equipment-v${expectedVersion}\"`,
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
        headers: {
          Accept: "application/json",
          ...init.headers,
        },
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

function parseEquipment(value: unknown): RefrigerationEquipment {
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
  return {
    id,
    code,
    name,
    location,
    type,
    manufacturer,
    model,
    serialNumber,
    temperatureClass,
    installedAt: readOptionalString(record.installed_at) ?? "",
    servicedAt: readOptionalString(record.serviced_at) ?? "",
    status,
    averageTemperatureC,
    minTemperatureC,
    maxTemperatureC,
    onlineSensors,
    totalSensors,
    activeAlarms,
    lastSeenAt: readOptionalString(record.last_seen_at) ?? readString(record.updated_at) ?? new Date(0).toISOString(),
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
