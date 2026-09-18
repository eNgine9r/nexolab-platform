export type RegistryLifecycleState = "active" | "inactive" | "retired";
export type PressureReference = "absolute" | "gauge";
export type RegistryJsonValue =
  | null
  | boolean
  | number
  | string
  | RegistryJsonValue[]
  | { [key: string]: RegistryJsonValue };

export type InstrumentRegistryRecord = {
  id: string;
  inventoryKey: string;
  displayName: string;
  instrumentKind: string;
  manufacturer: string | null;
  model: string | null;
  serialNumber: string | null;
  pressureReference: PressureReference | null;
  lifecycleState: RegistryLifecycleState;
  metadata: Record<string, RegistryJsonValue>;
  version: number;
  createdBy: string;
  updatedBy: string;
  createdAt: string;
  updatedAt: string;
};

export type SignalRegistryRecord = {
  id: string;
  instrumentId: string;
  businessKey: string;
  displayName: string;
  physicalQuantity: string;
  engineeringUnit: string;
  lifecycleState: RegistryLifecycleState;
  metadata: Record<string, RegistryJsonValue>;
  version: number;
  createdBy: string;
  updatedBy: string;
  createdAt: string;
  updatedAt: string;
};

export type InstrumentAcceptanceRecord = {
  id: string;
  instrumentId: string;
  acceptedForCalculation: boolean;
  stateLabel: string | null;
  effectiveFrom: string;
  effectiveTo: string | null;
  revision: number;
  recordedBy: string;
  recordedAt: string;
};

export type InstrumentWriteInput = {
  inventoryKey: string;
  displayName: string;
  instrumentKind: string;
  manufacturer: string | null;
  model: string | null;
  serialNumber: string | null;
  pressureReference: PressureReference | null;
  lifecycleState: RegistryLifecycleState;
  metadata?: Record<string, RegistryJsonValue>;
};

export type SignalWriteInput = {
  businessKey: string;
  displayName: string;
  physicalQuantity: string;
  engineeringUnit: string;
  lifecycleState: RegistryLifecycleState;
  metadata?: Record<string, RegistryJsonValue>;
};

export type AcceptanceAppendInput = {
  acceptedForCalculation: boolean;
  effectiveFrom: Date;
  stateLabel: string | null;
};

export interface InstrumentationRegistryRepository {
  listInstruments(signal?: AbortSignal): Promise<InstrumentRegistryRecord[]>;
  getInstrument(instrumentId: string, signal?: AbortSignal): Promise<InstrumentRegistryRecord>;
  createInstrument(input: InstrumentWriteInput, signal?: AbortSignal): Promise<InstrumentRegistryRecord>;
  updateInstrument(
    instrumentId: string,
    input: InstrumentWriteInput,
    expectedVersion: number,
    signal?: AbortSignal,
  ): Promise<InstrumentRegistryRecord>;
  listSignals(instrumentId: string, signal?: AbortSignal): Promise<SignalRegistryRecord[]>;
  createSignal(
    instrumentId: string,
    input: SignalWriteInput,
    signal?: AbortSignal,
  ): Promise<SignalRegistryRecord>;
  updateSignal(
    instrumentId: string,
    signalId: string,
    input: SignalWriteInput,
    expectedVersion: number,
    signal?: AbortSignal,
  ): Promise<SignalRegistryRecord>;
  listAcceptanceHistory(
    instrumentId: string,
    signal?: AbortSignal,
  ): Promise<InstrumentAcceptanceRecord[]>;
  appendAcceptance(
    instrumentId: string,
    input: AcceptanceAppendInput,
    signal?: AbortSignal,
  ): Promise<InstrumentAcceptanceRecord>;
}

export class InstrumentationRegistryRepositoryError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number | null = null,
    readonly expectedVersion: number | null = null,
    readonly actualVersion: number | null = null,
  ) {
    super(message);
    this.name = "InstrumentationRegistryRepositoryError";
  }
}

export class HttpInstrumentationRegistryRepository implements InstrumentationRegistryRepository {
  private readonly apiBaseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(apiBaseUrl: string, fetchImpl: typeof fetch = fetch.bind(globalThis)) {
    this.apiBaseUrl = normalizeBaseUrl(apiBaseUrl);
    this.fetchImpl = fetchImpl;
  }

  async listInstruments(signal?: AbortSignal): Promise<InstrumentRegistryRecord[]> {
    const payload = await this.request("/api/v1/instrumentation/instruments", { signal });
    return readItems(payload, parseInstrument);
  }

  async getInstrument(
    instrumentId: string,
    signal?: AbortSignal,
  ): Promise<InstrumentRegistryRecord> {
    return parseInstrument(
      await this.request(
        `/api/v1/instrumentation/instruments/${encodeURIComponent(instrumentId)}`,
        { signal },
      ),
    );
  }

  async createInstrument(
    input: InstrumentWriteInput,
    signal?: AbortSignal,
  ): Promise<InstrumentRegistryRecord> {
    return parseInstrument(
      await this.request("/api/v1/instrumentation/instruments", {
        method: "POST",
        signal,
        body: instrumentPayload(input),
        auditReason: "Created from Instrumentation Registry",
      }),
    );
  }

  async updateInstrument(
    instrumentId: string,
    input: InstrumentWriteInput,
    expectedVersion: number,
    signal?: AbortSignal,
  ): Promise<InstrumentRegistryRecord> {
    return parseInstrument(
      await this.request(
        `/api/v1/instrumentation/instruments/${encodeURIComponent(instrumentId)}`,
        {
          method: "PUT",
          signal,
          body: instrumentPayload(input),
          headers: { "If-Match": instrumentEtag(expectedVersion) },
          auditReason: "Updated from Instrumentation Registry",
        },
      ),
    );
  }

  async listSignals(instrumentId: string, signal?: AbortSignal): Promise<SignalRegistryRecord[]> {
    const payload = await this.request(
      `/api/v1/instrumentation/instruments/${encodeURIComponent(instrumentId)}/signals`,
      { signal },
    );
    return readItems(payload, parseSignal);
  }

  async createSignal(
    instrumentId: string,
    input: SignalWriteInput,
    signal?: AbortSignal,
  ): Promise<SignalRegistryRecord> {
    return parseSignal(
      await this.request(
        `/api/v1/instrumentation/instruments/${encodeURIComponent(instrumentId)}/signals`,
        {
          method: "POST",
          signal,
          body: signalPayload(input),
          auditReason: "Created from Instrumentation Registry",
        },
      ),
    );
  }

  async updateSignal(
    instrumentId: string,
    signalId: string,
    input: SignalWriteInput,
    expectedVersion: number,
    signal?: AbortSignal,
  ): Promise<SignalRegistryRecord> {
    return parseSignal(
      await this.request(
        `/api/v1/instrumentation/instruments/${encodeURIComponent(instrumentId)}/signals/${encodeURIComponent(signalId)}`,
        {
          method: "PUT",
          signal,
          body: signalPayload(input),
          headers: { "If-Match": signalEtag(expectedVersion) },
          auditReason: "Updated from Instrumentation Registry",
        },
      ),
    );
  }

  async listAcceptanceHistory(
    instrumentId: string,
    signal?: AbortSignal,
  ): Promise<InstrumentAcceptanceRecord[]> {
    const payload = await this.request(
      `/api/v1/instrumentation/instruments/${encodeURIComponent(instrumentId)}/acceptance-history`,
      { signal },
    );
    return readItems(payload, parseAcceptance);
  }

  async appendAcceptance(
    instrumentId: string,
    input: AcceptanceAppendInput,
    signal?: AbortSignal,
  ): Promise<InstrumentAcceptanceRecord> {
    return parseAcceptance(
      await this.request(
        `/api/v1/instrumentation/instruments/${encodeURIComponent(instrumentId)}/acceptance-history`,
        {
          method: "POST",
          signal,
          body: {
            accepted_for_calculation: input.acceptedForCalculation,
            effective_from: input.effectiveFrom.toISOString(),
            state_label: optionalTrim(input.stateLabel),
          },
          auditReason: "Changed calculation acceptance from Instrumentation Registry",
        },
      ),
    );
  }

  private async request(
    path: string,
    options: {
      method?: "GET" | "POST" | "PUT";
      body?: Record<string, unknown>;
      headers?: Record<string, string>;
      auditReason?: string;
      signal?: AbortSignal;
    } = {},
  ): Promise<unknown> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.apiBaseUrl}${path}`, {
        method: options.method ?? "GET",
        credentials: "same-origin",
        signal: options.signal,
        headers: {
          Accept: "application/json",
          ...(options.body ? { "Content-Type": "application/json" } : {}),
          ...(options.auditReason ? { "X-Audit-Reason": options.auditReason } : {}),
          ...options.headers,
        },
        body: options.body ? JSON.stringify(options.body) : undefined,
      });
    } catch (cause) {
      if (options.signal?.aborted) throw cause;
      throw new InstrumentationRegistryRepositoryError(
        "Не вдалося з’єднатися з канонічним реєстром приладів.",
        "request_failed",
      );
    }

    const payload = await readJson(response);
    if (!response.ok) {
      const detail = asRecord(asRecord(payload)?.detail);
      throw new InstrumentationRegistryRepositoryError(
        readString(detail?.message) ?? "Операцію з реєстром приладів відхилено.",
        readString(detail?.code) ?? "instrumentation_request_failed",
        response.status,
        readInteger(detail?.expected_version),
        readInteger(detail?.actual_version),
      );
    }
    return payload;
  }
}

export function instrumentEtag(version: number): string {
  return `W/"instrument-v${version}"`;
}

export function signalEtag(version: number): string {
  return `W/"signal-v${version}"`;
}

function instrumentPayload(input: InstrumentWriteInput): Record<string, unknown> {
  return {
    inventory_key: input.inventoryKey.trim(),
    display_name: input.displayName.trim(),
    instrument_kind: input.instrumentKind.trim(),
    manufacturer: optionalTrim(input.manufacturer),
    model: optionalTrim(input.model),
    serial_number: optionalTrim(input.serialNumber),
    pressure_reference: input.pressureReference,
    lifecycle_state: input.lifecycleState,
    metadata: input.metadata ?? {},
  };
}

function signalPayload(input: SignalWriteInput): Record<string, unknown> {
  return {
    business_key: input.businessKey.trim(),
    display_name: input.displayName.trim(),
    physical_quantity: input.physicalQuantity.trim(),
    engineering_unit: input.engineeringUnit.trim(),
    lifecycle_state: input.lifecycleState,
    metadata: input.metadata ?? {},
  };
}

function parseInstrument(value: unknown): InstrumentRegistryRecord {
  const row = asRecord(value);
  if (!row) throw invalidResponse();
  return {
    id: requiredString(row.id),
    inventoryKey: requiredString(row.inventory_key),
    displayName: requiredString(row.display_name),
    instrumentKind: requiredString(row.instrument_kind),
    manufacturer: optionalString(row.manufacturer),
    model: optionalString(row.model),
    serialNumber: optionalString(row.serial_number),
    pressureReference: readPressureReference(row.pressure_reference),
    lifecycleState: requiredLifecycle(row.lifecycle_state),
    metadata: readJsonObject(row.metadata),
    version: requiredPositiveInteger(row.version),
    createdBy: requiredString(row.created_by),
    updatedBy: requiredString(row.updated_by),
    createdAt: requiredTimestamp(row.created_at),
    updatedAt: requiredTimestamp(row.updated_at),
  };
}

function parseSignal(value: unknown): SignalRegistryRecord {
  const row = asRecord(value);
  if (!row) throw invalidResponse();
  return {
    id: requiredString(row.id),
    instrumentId: requiredString(row.instrument_id),
    businessKey: requiredString(row.business_key),
    displayName: requiredString(row.display_name),
    physicalQuantity: requiredString(row.physical_quantity),
    engineeringUnit: requiredString(row.engineering_unit),
    lifecycleState: requiredLifecycle(row.lifecycle_state),
    metadata: readJsonObject(row.metadata),
    version: requiredPositiveInteger(row.version),
    createdBy: requiredString(row.created_by),
    updatedBy: requiredString(row.updated_by),
    createdAt: requiredTimestamp(row.created_at),
    updatedAt: requiredTimestamp(row.updated_at),
  };
}

function parseAcceptance(value: unknown): InstrumentAcceptanceRecord {
  const row = asRecord(value);
  if (!row) throw invalidResponse();
  if (row.accepted_for_calculation !== true && row.accepted_for_calculation !== false) {
    throw invalidResponse();
  }
  return {
    id: requiredString(row.id),
    instrumentId: requiredString(row.instrument_id),
    acceptedForCalculation: row.accepted_for_calculation,
    stateLabel: optionalString(row.state_label),
    effectiveFrom: requiredTimestamp(row.effective_from),
    effectiveTo: optionalTimestamp(row.effective_to),
    revision: requiredPositiveInteger(row.revision),
    recordedBy: requiredString(row.recorded_by),
    recordedAt: requiredTimestamp(row.recorded_at),
  };
}

function readItems<T>(payload: unknown, parser: (value: unknown) => T): T[] {
  const root = asRecord(payload);
  if (!root || !Array.isArray(root.items)) throw invalidResponse();
  return root.items.map(parser);
}

function invalidResponse(): InstrumentationRegistryRepositoryError {
  return new InstrumentationRegistryRepositoryError(
    "Сервер повернув некоректний контракт Instrumentation Registry.",
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

function requiredString(value: unknown): string {
  const result = readString(value);
  if (!result) throw invalidResponse();
  return result;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function optionalString(value: unknown): string | null {
  return value === null || value === undefined ? null : requiredString(value);
}

function optionalTrim(value: string | null): string | null {
  const normalized = value?.trim();
  return normalized ? normalized : null;
}

function requiredPositiveInteger(value: unknown): number {
  const result = readInteger(value);
  if (result === null || result < 1) throw invalidResponse();
  return result;
}

function readInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function requiredLifecycle(value: unknown): RegistryLifecycleState {
  if (value === "active" || value === "inactive" || value === "retired") return value;
  throw invalidResponse();
}

function readPressureReference(value: unknown): PressureReference | null {
  if (value === null || value === undefined) return null;
  if (value === "absolute" || value === "gauge") return value;
  throw invalidResponse();
}

function requiredTimestamp(value: unknown): string {
  const result = requiredString(value);
  if (!Number.isFinite(new Date(result).getTime())) throw invalidResponse();
  return result;
}

function optionalTimestamp(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  return requiredTimestamp(value);
}

function readJsonObject(value: unknown): Record<string, RegistryJsonValue> {
  const record = asRecord(value);
  if (!record) throw invalidResponse();
  const result: Record<string, RegistryJsonValue> = {};
  for (const [key, item] of Object.entries(record)) {
    if (!isJsonValue(item)) throw invalidResponse();
    result[key] = item;
  }
  return result;
}

function isJsonValue(value: unknown): value is RegistryJsonValue {
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(isJsonValue);
  const record = asRecord(value);
  return record !== null && Object.values(record).every(isJsonValue);
}
