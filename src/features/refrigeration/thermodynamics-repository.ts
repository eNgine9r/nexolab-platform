export const DERIVED_THERMODYNAMIC_METRICS = [
  "refrigeration.temperature.evaporation_saturation",
  "refrigeration.temperature.condensation_saturation",
  "refrigeration.superheat",
  "refrigeration.subcooling",
] as const;

export type DerivedThermodynamicMetric = (typeof DERIVED_THERMODYNAMIC_METRICS)[number];

export type RefrigerationCircuitSummary = {
  id: string;
  equipmentId: string;
  businessKey: string;
  displayName: string;
};

export type DerivedThermodynamicValue = {
  metric: DerivedThermodynamicMetric;
  availability: "available" | "unavailable";
  value: number | null;
  unit: "degC" | "K";
  reasonCodes: string[];
  observationAt: string;
  effectiveAt: string | null;
  computedAt: string;
};

export type CircuitThermodynamicsSnapshot = {
  circuit: RefrigerationCircuitSummary;
  observationAt: string;
  metrics: DerivedThermodynamicValue[];
};
export interface RefrigerationThermodynamicsRepository {
  listForEquipment(equipmentId: string, signal?: AbortSignal): Promise<RefrigerationCircuitSummary[]>;
  readDerived(
    circuit: RefrigerationCircuitSummary,
    observationAt: Date,
    signal?: AbortSignal,
  ): Promise<CircuitThermodynamicsSnapshot>;
}

const expectedUnits: Record<DerivedThermodynamicMetric, "degC" | "K"> = {
  "refrigeration.temperature.evaporation_saturation": "degC",
  "refrigeration.temperature.condensation_saturation": "degC",
  "refrigeration.superheat": "K",
  "refrigeration.subcooling": "K",
};

const metricSet = new Set<string>(DERIVED_THERMODYNAMIC_METRICS);

export class HttpRefrigerationThermodynamicsRepository implements RefrigerationThermodynamicsRepository {
  constructor(
    private readonly apiBaseUrl: string,
    private readonly fetchImpl: typeof fetch = fetch.bind(globalThis),
  ) {}

  async listForEquipment(equipmentId: string, signal?: AbortSignal): Promise<RefrigerationCircuitSummary[]> {
    const payload = await this.readJson(
      `${this.apiBaseUrl}/api/v1/refrigeration/circuits`,
      signal,
      "Не вдалося отримати холодильні контури.",
    );
    const record = asRecord(payload);
    if (!record || !Array.isArray(record.items)) throw invalidContract();

    return record.items
      .map(parseCircuit)
      .filter((circuit) => circuit.equipmentId === equipmentId)
      .sort((left, right) => left.businessKey.localeCompare(right.businessKey));
  }

  async readDerived(
    circuit: RefrigerationCircuitSummary,
    observationAt: Date,
    signal?: AbortSignal,
  ): Promise<CircuitThermodynamicsSnapshot> {
    if (!Number.isFinite(observationAt.getTime())) throw new Error("Некоректний час спостереження.");
    const url = new URL(
      `${this.apiBaseUrl}/api/v1/refrigeration/circuits/${encodeURIComponent(circuit.id)}/derived`,
    );
    url.searchParams.set("observation_at", observationAt.toISOString());

    const payload = await this.readJson(
      url.toString(),
      signal,
      "Не вдалося отримати термодинаміку холодильного контуру.",
    );
    return parseDerivedSnapshot(payload, circuit);
  }
  private async readJson(url: string, signal: AbortSignal | undefined, message: string): Promise<unknown> {
    let response: Response;
    try {
      response = await this.fetchImpl(url, {
        method: "GET",
        headers: { Accept: "application/json" },
        credentials: "same-origin",
        signal,
      });
    } catch {
      throw new Error(message);
    }

    const payload: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = asRecord(asRecord(payload)?.detail);
      throw new Error(readString(detail?.message) ?? message);
    }
    return payload;
  }
}

function parseCircuit(value: unknown): RefrigerationCircuitSummary {
  const record = asRecord(value);
  const id = readString(record?.id);
  const equipmentId = readString(record?.equipment_id);
  const businessKey = readString(record?.business_key);
  const displayName = readString(record?.display_name);
  if (!id || !equipmentId || !businessKey || !displayName) throw invalidContract();
  return { id, equipmentId, businessKey, displayName };
}

function parseDerivedSnapshot(
  value: unknown,
  circuit: RefrigerationCircuitSummary,
): CircuitThermodynamicsSnapshot {
  const record = asRecord(value);
  const responseCircuitId = readString(record?.circuit_id);
  const observationAt = readTimestamp(record?.observation_at);
  if (responseCircuitId !== circuit.id || !observationAt || !Array.isArray(record?.metrics)) {
    throw invalidContract();
  }

  const parsed = new Map<DerivedThermodynamicMetric, DerivedThermodynamicValue>();
  for (const candidate of record.metrics) {
    const item = parseDerivedValue(candidate);
    if (parsed.has(item.metric)) throw invalidContract();
    parsed.set(item.metric, item);
  }

  if (parsed.size !== DERIVED_THERMODYNAMIC_METRICS.length) throw invalidContract();
  return {
    circuit,
    observationAt,
    metrics: DERIVED_THERMODYNAMIC_METRICS.map((metric) => parsed.get(metric)!),
  };
}
function parseDerivedValue(value: unknown): DerivedThermodynamicValue {
  const record = asRecord(value);
  if (!record) throw invalidContract();
  const metricValue = readString(record.metric);
  if (!metricValue || !metricSet.has(metricValue)) throw invalidContract();
  const metric = metricValue as DerivedThermodynamicMetric;
  const availability = record?.availability;
  if (availability !== "available" && availability !== "unavailable") throw invalidContract();
  const reasonCodes = readStringArray(record.reason_codes);
  const observationAt = readTimestamp(record.observation_at);
  const computedAt = readTimestamp(record.computed_at);
  if (!reasonCodes || !observationAt || !computedAt) throw invalidContract();

  const kernel = record.kernel_result === null ? null : asRecord(record.kernel_result);
  if (record.kernel_result !== null && !kernel) throw invalidContract();

  let effectiveAt: string | null = null;
  let valueNumber: number | null = null;
  if (kernel) {
    const kernelMetric = readString(kernel.metric);
    const kernelAvailability = kernel.availability;
    const unit = readString(kernel.unit);
    if (kernelMetric !== metric || kernelAvailability !== availability || unit !== expectedUnits[metric]) {
      throw invalidContract();
    }
    effectiveAt = kernel.effective_at === null ? null : readTimestamp(kernel.effective_at);
    if (kernel.effective_at !== null && !effectiveAt) throw invalidContract();
    if (kernel.value !== null) {
      if (typeof kernel.value !== "number" || !Number.isFinite(kernel.value)) throw invalidContract();
      valueNumber = kernel.value;
    }
  }

  if (availability === "available" && (kernel === null || valueNumber === null)) {
    throw invalidContract();
  }

  return {
    metric,
    availability,
    value: availability === "available" ? valueNumber : null,
    unit: expectedUnits[metric],
    reasonCodes,
    observationAt,
    effectiveAt,
    computedAt,
  };
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
function readString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

function readTimestamp(value: unknown): string | null {
  const text = readString(value);
  return text && Number.isFinite(Date.parse(text)) ? text : null;
}

function readStringArray(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) return null;
  return value as string[];
}

function invalidContract(): Error {
  return new Error("Некоректний контракт термодинаміки холодильного контуру.");
}
