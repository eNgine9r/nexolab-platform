export const CIRCUIT_PROCESS_ROLES = [
  "suction_pressure",
  "condensing_pressure",
  "suction_line_temperature",
  "liquid_line_temperature",
  "atmospheric_pressure",
  "relative_humidity",
] as const;

export type CircuitProcessRole = (typeof CIRCUIT_PROCESS_ROLES)[number];
export type CircuitLifecycleState = "active" | "inactive" | "retired";
export type PressureReference = "absolute" | "gauge";
export const CANONICAL_PROPERTY_PROVIDER_PROFILE = "coolprop-heos/8.0.0";

export type RefrigerationCircuitRecord = {
  id: string;
  equipmentId: string;
  businessKey: string;
  displayName: string;
  createdBy: string;
  createdAt: string;
};

export type CircuitLifecycleRecord = {
  id: string;
  circuitId: string;
  state: CircuitLifecycleState;
  calculationEnabled: boolean;
  validFrom: string;
  validTo: string | null;
  revision: number;
  recordedBy: string;
  recordedAt: string;
};

export type CircuitConfigurationRecord = {
  id: string;
  circuitId: string;
  refrigerantCode: string;
  calculationPolicyVersion: string;
  propertyProviderProfile: string | null;
  validFrom: string;
  validTo: string | null;
  revision: number;
  recordedBy: string;
  recordedAt: string;
};

export type CircuitBindingRecord = {
  id: string;
  circuitId: string;
  signalId: string;
  role: CircuitProcessRole;
  physicalQuantity: string;
  engineeringUnit: string;
  instrumentKind: string;
  pressureReference: PressureReference | null;
  validFrom: string;
  validTo: string | null;
  revision: number;
  recordedBy: string;
  recordedAt: string;
  endedBy: string | null;
  endedAt: string | null;
};

export type CircuitBindingCandidate = {
  signalId: string;
  instrumentId: string;
  signalDisplayName: string;
  instrumentDisplayName: string;
  physicalQuantity: string;
  engineeringUnit: string;
  instrumentKind: string;
  pressureReference: PressureReference | null;
};

export type CalculationPolicyRecord = {
  id: string;
  version: string;
  maximumAgeMs: number;
  maximumFutureClockSkewMs: number;
  maximumCrossInputSkewMs: number;
  acceptedCalibrationStates: string[];
  requireCalibrationAtObservation: boolean;
  calibrationRequiredRoles: string[];
  createdBy: string;
  createdAt: string;
};

export type CreateCircuitInput = {
  equipmentId: string;
  businessKey: string;
  displayName: string;
  initialState: CircuitLifecycleState;
  validFrom: Date;
};

export type AppendLifecycleInput = {
  state: CircuitLifecycleState;
  validFrom: Date;
};

export type AppendConfigurationInput = {
  refrigerantCode: string;
  calculationPolicyVersion: string;
  propertyProviderProfile: string;
  validFrom: Date;
};

export type AppendBindingInput = {
  role: CircuitProcessRole;
  signalId: string;
  validFrom: Date;
};

export interface RefrigerationCircuitConfigurationRepository {
  listCircuits(equipmentId: string, signal?: AbortSignal): Promise<RefrigerationCircuitRecord[]>;
  createCircuit(input: CreateCircuitInput, signal?: AbortSignal): Promise<RefrigerationCircuitRecord>;
  listLifecycle(circuitId: string, signal?: AbortSignal): Promise<CircuitLifecycleRecord[]>;
  appendLifecycle(
    circuitId: string,
    input: AppendLifecycleInput,
    signal?: AbortSignal,
  ): Promise<CircuitLifecycleRecord>;
  listConfigurations(circuitId: string, signal?: AbortSignal): Promise<CircuitConfigurationRecord[]>;
  appendConfiguration(
    circuitId: string,
    input: AppendConfigurationInput,
    signal?: AbortSignal,
  ): Promise<CircuitConfigurationRecord>;
  listBindings(
    circuitId: string,
    includeHistory?: boolean,
    signal?: AbortSignal,
  ): Promise<CircuitBindingRecord[]>;
  appendBinding(
    circuitId: string,
    input: AppendBindingInput,
    signal?: AbortSignal,
  ): Promise<CircuitBindingRecord>;
  endBinding(
    circuitId: string,
    role: CircuitProcessRole,
    validTo: Date,
    signal?: AbortSignal,
  ): Promise<CircuitBindingRecord>;
  listPolicies(signal?: AbortSignal): Promise<CalculationPolicyRecord[]>;
  listBindingCandidates(
    role: CircuitProcessRole,
    at: Date,
    signal?: AbortSignal,
  ): Promise<CircuitBindingCandidate[]>;
}

export class HttpRefrigerationCircuitConfigurationRepository
  implements RefrigerationCircuitConfigurationRepository
{
  constructor(
    private readonly apiBaseUrl: string,
    private readonly fetchImpl: typeof fetch = fetch.bind(globalThis),
  ) {}

  async listCircuits(
    equipmentId: string,
    signal?: AbortSignal,
  ): Promise<RefrigerationCircuitRecord[]> {
    const payload = await this.request("/api/v1/refrigeration/circuits", { signal });
    return readItems(payload, parseCircuit)
      .filter((item) => item.equipmentId === equipmentId)
      .sort((left, right) => left.displayName.localeCompare(right.displayName));
  }

  async createCircuit(
    input: CreateCircuitInput,
    signal?: AbortSignal,
  ): Promise<RefrigerationCircuitRecord> {
    return parseCircuit(
      await this.request("/api/v1/refrigeration/circuits", {
        method: "POST",
        signal,
        body: {
          equipment_id: input.equipmentId,
          business_key: input.businessKey,
          display_name: input.displayName,
          initial_state: input.initialState,
          valid_from: iso(input.validFrom),
        },
      }),
    );
  }

  async listLifecycle(circuitId: string, signal?: AbortSignal): Promise<CircuitLifecycleRecord[]> {
    const payload = await this.request(
      `/api/v1/refrigeration/circuits/${encodeURIComponent(circuitId)}/lifecycle-history`,
      { signal },
    );
    return readItems(payload, parseLifecycle);
  }

  async appendLifecycle(
    circuitId: string,
    input: AppendLifecycleInput,
    signal?: AbortSignal,
  ): Promise<CircuitLifecycleRecord> {
    return parseLifecycle(
      await this.request(
        `/api/v1/refrigeration/circuits/${encodeURIComponent(circuitId)}/lifecycle-history`,
        {
          method: "POST",
          signal,
          body: { state: input.state, valid_from: iso(input.validFrom) },
        },
      ),
    );
  }

  async listConfigurations(
    circuitId: string,
    signal?: AbortSignal,
  ): Promise<CircuitConfigurationRecord[]> {
    const payload = await this.request(
      `/api/v1/refrigeration/circuits/${encodeURIComponent(circuitId)}/configuration-history`,
      { signal },
    );
    return readItems(payload, parseConfiguration);
  }

  async appendConfiguration(
    circuitId: string,
    input: AppendConfigurationInput,
    signal?: AbortSignal,
  ): Promise<CircuitConfigurationRecord> {
    return parseConfiguration(
      await this.request(
        `/api/v1/refrigeration/circuits/${encodeURIComponent(circuitId)}/configuration-history`,
        {
          method: "POST",
          signal,
          body: {
            schema_version: "refrigeration-circuit-configuration/v1",
            refrigerant_code: input.refrigerantCode,
            calculation_policy_version: input.calculationPolicyVersion,
            property_provider_profile: input.propertyProviderProfile,
            valid_from: iso(input.validFrom),
          },
        },
      ),
    );
  }

  async listBindings(
    circuitId: string,
    includeHistory = true,
    signal?: AbortSignal,
  ): Promise<CircuitBindingRecord[]> {
    const suffix = includeHistory ? "?include_history=true" : "";
    const payload = await this.request(
      `/api/v1/refrigeration/circuits/${encodeURIComponent(circuitId)}/bindings${suffix}`,
      { signal },
    );
    return readItems(payload, parseBinding);
  }

  async appendBinding(
    circuitId: string,
    input: AppendBindingInput,
    signal?: AbortSignal,
  ): Promise<CircuitBindingRecord> {
    return parseBinding(
      await this.request(
        `/api/v1/refrigeration/circuits/${encodeURIComponent(circuitId)}/bindings`,
        {
          method: "POST",
          signal,
          body: {
            role: input.role,
            signal_id: input.signalId,
            valid_from: iso(input.validFrom),
          },
        },
      ),
    );
  }

  async endBinding(
    circuitId: string,
    role: CircuitProcessRole,
    validTo: Date,
    signal?: AbortSignal,
  ): Promise<CircuitBindingRecord> {
    return parseBinding(
      await this.request(
        `/api/v1/refrigeration/circuits/${encodeURIComponent(circuitId)}/bindings/${encodeURIComponent(role)}/end`,
        {
          method: "POST",
          signal,
          body: { valid_to: iso(validTo) },
        },
      ),
    );
  }

  async listPolicies(signal?: AbortSignal): Promise<CalculationPolicyRecord[]> {
    const payload = await this.request("/api/v1/refrigeration/calculation-policies", { signal });
    return readItems(payload, parsePolicy);
  }

  async listBindingCandidates(
    role: CircuitProcessRole,
    at: Date,
    signal?: AbortSignal,
  ): Promise<CircuitBindingCandidate[]> {
    const query = new URLSearchParams({ role, at: iso(at) });
    const payload = await this.request(
      `/api/v1/refrigeration/circuits/binding-candidates?${query.toString()}`,
      { signal },
    );
    return readItems(payload, parseCandidate);
  }

  private async request(
    path: string,
    options: {
      method?: "GET" | "POST";
      body?: Record<string, unknown>;
      signal?: AbortSignal;
    } = {},
  ): Promise<unknown> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.apiBaseUrl}${path}`, {
        method: options.method ?? "GET",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          ...(options.body ? { "Content-Type": "application/json" } : {}),
        },
        body: options.body ? JSON.stringify(options.body) : undefined,
        signal: options.signal,
      });
    } catch {
      throw new Error("Не вдалося з’єднатися з API конфігурації холодильного контуру.");
    }
    const payload: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = asRecord(asRecord(payload)?.detail);
      const code = readString(detail?.code);
      const message = readString(detail?.message);
      throw new Error(message ?? code ?? "Операцію конфігурації холодильного контуру відхилено.");
    }
    return payload;
  }
}

function parseCircuit(value: unknown): RefrigerationCircuitRecord {
  const row = requiredRecord(value);
  return {
    id: requiredString(row.id),
    equipmentId: requiredString(row.equipment_id),
    businessKey: requiredString(row.business_key),
    displayName: requiredString(row.display_name),
    createdBy: requiredString(row.created_by),
    createdAt: requiredTimestamp(row.created_at),
  };
}

function parseLifecycle(value: unknown): CircuitLifecycleRecord {
  const row = requiredRecord(value);
  const state = row.state;
  if (state !== "active" && state !== "inactive" && state !== "retired") throw invalidContract();
  return {
    id: requiredString(row.id),
    circuitId: requiredString(row.circuit_id),
    state,
    calculationEnabled: requiredBoolean(row.calculation_enabled),
    validFrom: requiredTimestamp(row.valid_from),
    validTo: optionalTimestamp(row.valid_to),
    revision: requiredInteger(row.revision),
    recordedBy: requiredString(row.recorded_by),
    recordedAt: requiredTimestamp(row.recorded_at),
  };
}

function parseConfiguration(value: unknown): CircuitConfigurationRecord {
  const row = requiredRecord(value);
  if (row.schema_version !== "refrigeration-circuit-configuration/v1") throw invalidContract();
  return {
    id: requiredString(row.id),
    circuitId: requiredString(row.circuit_id),
    refrigerantCode: requiredString(row.refrigerant_code),
    calculationPolicyVersion: requiredString(row.calculation_policy_version),
    propertyProviderProfile:
      row.property_provider_profile === null ? null : requiredString(row.property_provider_profile),
    validFrom: requiredTimestamp(row.valid_from),
    validTo: optionalTimestamp(row.valid_to),
    revision: requiredInteger(row.revision),
    recordedBy: requiredString(row.recorded_by),
    recordedAt: requiredTimestamp(row.recorded_at),
  };
}

function parseBinding(value: unknown): CircuitBindingRecord {
  const row = requiredRecord(value);
  const role = readRole(row.role);
  return {
    id: requiredString(row.id),
    circuitId: requiredString(row.circuit_id),
    signalId: requiredString(row.signal_id),
    role,
    physicalQuantity: requiredString(row.physical_quantity),
    engineeringUnit: requiredString(row.engineering_unit),
    instrumentKind: requiredString(row.instrument_kind),
    pressureReference: readPressureReference(row.pressure_reference),
    validFrom: requiredTimestamp(row.valid_from),
    validTo: optionalTimestamp(row.valid_to),
    revision: requiredInteger(row.revision),
    recordedBy: requiredString(row.recorded_by),
    recordedAt: requiredTimestamp(row.recorded_at),
    endedBy: optionalString(row.ended_by),
    endedAt: optionalTimestamp(row.ended_at),
  };
}

function parseCandidate(value: unknown): CircuitBindingCandidate {
  const row = requiredRecord(value);
  return {
    signalId: requiredString(row.signal_id),
    instrumentId: requiredString(row.instrument_id),
    signalDisplayName: requiredString(row.signal_display_name),
    instrumentDisplayName: requiredString(row.instrument_display_name),
    physicalQuantity: requiredString(row.physical_quantity),
    engineeringUnit: requiredString(row.engineering_unit),
    instrumentKind: requiredString(row.instrument_kind),
    pressureReference: readPressureReference(row.pressure_reference),
  };
}

function parsePolicy(value: unknown): CalculationPolicyRecord {
  const row = requiredRecord(value);
  if (row.schema_version !== "refrigeration-calculation-policy/v1") throw invalidContract();
  if (row.calibration_vocabulary_version !== "calibration-state/v1") throw invalidContract();
  return {
    id: requiredString(row.id),
    version: requiredString(row.version),
    maximumAgeMs: requiredInteger(row.maximum_age_ms),
    maximumFutureClockSkewMs: requiredInteger(row.maximum_future_clock_skew_ms),
    maximumCrossInputSkewMs: requiredInteger(row.maximum_cross_input_skew_ms),
    acceptedCalibrationStates: requiredStringArray(row.accepted_calibration_states),
    requireCalibrationAtObservation: requiredBoolean(row.require_calibration_at_observation),
    calibrationRequiredRoles: requiredStringArray(row.calibration_required_roles),
    createdBy: requiredString(row.created_by),
    createdAt: requiredTimestamp(row.created_at),
  };
}

function readItems<T>(value: unknown, parser: (item: unknown) => T): T[] {
  const row = requiredRecord(value);
  if (!Array.isArray(row.items)) throw invalidContract();
  return row.items.map(parser);
}

function readRole(value: unknown): CircuitProcessRole {
  if (typeof value !== "string" || !CIRCUIT_PROCESS_ROLES.includes(value as CircuitProcessRole)) {
    throw invalidContract();
  }
  return value as CircuitProcessRole;
}

function readPressureReference(value: unknown): PressureReference | null {
  if (value === null) return null;
  if (value !== "absolute" && value !== "gauge") throw invalidContract();
  return value;
}

function iso(value: Date): string {
  if (!(value instanceof Date) || !Number.isFinite(value.getTime())) {
    throw new Error("Потрібен коректний час із часовою зоною.");
  }
  return value.toISOString();
}

function requiredRecord(value: unknown): Record<string, unknown> {
  const row = asRecord(value);
  if (!row) throw invalidContract();
  return row;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function requiredString(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) throw invalidContract();
  return value;
}

function optionalString(value: unknown): string | null {
  return value === null ? null : requiredString(value);
}

function requiredBoolean(value: unknown): boolean {
  if (typeof value !== "boolean") throw invalidContract();
  return value;
}

function requiredInteger(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) throw invalidContract();
  return value;
}

function requiredTimestamp(value: unknown): string {
  if (typeof value !== "string" || !Number.isFinite(Date.parse(value))) throw invalidContract();
  return value;
}

function optionalTimestamp(value: unknown): string | null {
  return value === null ? null : requiredTimestamp(value);
}

function requiredStringArray(value: unknown): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) throw invalidContract();
  return value as string[];
}

function invalidContract(): Error {
  return new Error("API конфігурації холодильного контуру повернув некоректний контракт.");
}
