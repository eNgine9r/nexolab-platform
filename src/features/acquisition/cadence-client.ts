import { createAuthenticatedFetch } from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";

export const ACQUISITION_CADENCE_URL = "/api/device-agent/acquisition-cadence";

export type CadenceFamily = "xjp60d" | "le01mp";

export type CadenceFamilyDefault = {
  busId: string;
  deviceFamily: CadenceFamily;
  intervalSeconds: number;
};

export type CadenceDeviceOverride = {
  deviceId: string;
  intervalSeconds: number;
};

export type EffectiveCadenceDevice = {
  deviceId: string;
  busId: string;
  deviceFamily: CadenceFamily;
  lifecycle: string;
  effectiveIntervalSeconds: number;
  cadenceSource: "family_default" | "device_override";
};

export type CapacityBusSummary = {
  busId: string;
  safe: boolean;
  activeDeviceCount: number;
  activeTargetCount: number;
  estimatedUtilizationPercent: number;
  maximumAllowedUtilizationPercent: number;
  recommendedMinimumIntervalSeconds: number | null;
  requestBudgetSource: string;
};

export type AcquisitionCapacitySummary = {
  safe: boolean;
  maximumAllowedUtilizationPercent: number;
  safetyMarginPercent: number;
  buses: CapacityBusSummary[];
};

export type AcquisitionCadenceConfiguration = {
  schemaVersion: number;
  registryRevision: number;
  updatedAt: string;
  presetsSeconds: number[];
  customMinSeconds: number;
  maximumSeconds: number;
  familyDefaults: CadenceFamilyDefault[];
  deviceOverrides: CadenceDeviceOverride[];
  effectiveDevices: EffectiveCadenceDevice[];
  capacity: AcquisitionCapacitySummary;
};

export type CadenceMutation = {
  expected_revision: number;
  reason: string;
  family_defaults?: Array<{
    bus_id: string;
    device_family: CadenceFamily;
    interval_seconds: number;
  }>;
  device_overrides?: Array<{
    device_id: string;
    interval_seconds: number | null;
  }>;
};

export type CadenceClientErrorCode =
  | "acquisition_capacity_exceeded"
  | "revision_conflict"
  | "access_denied"
  | "device_agent_unavailable"
  | "invalid_response"
  | "request_failed";

export class CadenceClientError extends Error {
  readonly code: CadenceClientErrorCode;
  readonly status: number | null;
  readonly capacity: AcquisitionCapacitySummary | null;

  constructor(
    code: CadenceClientErrorCode,
    message: string,
    options: { status?: number | null; capacity?: AcquisitionCapacitySummary | null } = {},
  ) {
    super(message);
    this.name = "CadenceClientError";
    this.code = code;
    this.status = options.status ?? null;
    this.capacity = options.capacity ?? null;
  }
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function number(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new CadenceClientError("invalid_response", `Некоректне поле ${label} у відповіді cadence API.`);
  }
  return value;
}

function string(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new CadenceClientError("invalid_response", `Некоректне поле ${label} у відповіді cadence API.`);
  }
  return value;
}

function family(value: unknown): CadenceFamily {
  if (value === "xjp60d" || value === "le01mp") return value;
  throw new CadenceClientError("invalid_response", "Cadence API повернув невідому device family.");
}

function parseCapacity(value: unknown): AcquisitionCapacitySummary {
  const root = record(value);
  if (!root || typeof root.safe !== "boolean" || !Array.isArray(root.buses)) {
    throw new CadenceClientError("invalid_response", "Cadence API повернув некоректний capacity summary.");
  }
  return {
    safe: root.safe,
    maximumAllowedUtilizationPercent: number(
      root.maximum_allowed_utilization_percent,
      "capacity.maximum_allowed_utilization_percent",
    ),
    safetyMarginPercent: number(root.safety_margin_percent, "capacity.safety_margin_percent"),
    buses: root.buses.map((item, index) => {
      const bus = record(item);
      if (!bus || typeof bus.safe !== "boolean") {
        throw new CadenceClientError("invalid_response", `Некоректний capacity bus ${index}.`);
      }
      const recommendation = bus.recommended_minimum_interval_seconds;
      return {
        busId: string(bus.bus_id, `capacity.buses[${index}].bus_id`),
        safe: bus.safe,
        activeDeviceCount: number(bus.active_device_count, `capacity.buses[${index}].active_device_count`),
        activeTargetCount: number(bus.active_target_count, `capacity.buses[${index}].active_target_count`),
        estimatedUtilizationPercent: number(
          bus.estimated_utilization_percent,
          `capacity.buses[${index}].estimated_utilization_percent`,
        ),
        maximumAllowedUtilizationPercent: number(
          bus.maximum_allowed_utilization_percent,
          `capacity.buses[${index}].maximum_allowed_utilization_percent`,
        ),
        recommendedMinimumIntervalSeconds:
          recommendation === null || recommendation === undefined
            ? null
            : number(recommendation, `capacity.buses[${index}].recommended_minimum_interval_seconds`),
        requestBudgetSource:
          typeof bus.request_budget_source === "string" ? bus.request_budget_source : "unknown",
      };
    }),
  };
}

export function normalizeCadenceConfiguration(value: unknown): AcquisitionCadenceConfiguration {
  const root = record(value);
  const policy = root ? record(root.policy) : null;
  if (!root || !policy || !Array.isArray(policy.family_defaults) || !Array.isArray(policy.device_overrides)) {
    throw new CadenceClientError(
      "invalid_response",
      "Device Agent повернув некоректну cadence configuration.",
    );
  }
  if (!Array.isArray(policy.presets_seconds) || !Array.isArray(root.effective_devices)) {
    throw new CadenceClientError(
      "invalid_response",
      "Cadence configuration не містить обов’язкових списків.",
    );
  }

  return {
    schemaVersion: number(root.schema_version, "schema_version"),
    registryRevision: number(root.registry_revision, "registry_revision"),
    updatedAt: string(root.updated_at, "updated_at"),
    presetsSeconds: policy.presets_seconds.map((item, index) => number(item, `presets_seconds[${index}]`)),
    customMinSeconds: number(policy.custom_min_seconds, "custom_min_seconds"),
    maximumSeconds: number(policy.maximum_seconds, "maximum_seconds"),
    familyDefaults: policy.family_defaults.map((item, index) => {
      const row = record(item);
      if (!row) throw new CadenceClientError("invalid_response", `Некоректний family default ${index}.`);
      return {
        busId: string(row.bus_id, `family_defaults[${index}].bus_id`),
        deviceFamily: family(row.device_family),
        intervalSeconds: number(row.interval_seconds, `family_defaults[${index}].interval_seconds`),
      };
    }),
    deviceOverrides: policy.device_overrides.map((item, index) => {
      const row = record(item);
      if (!row) throw new CadenceClientError("invalid_response", `Некоректний device override ${index}.`);
      return {
        deviceId: string(row.device_id, `device_overrides[${index}].device_id`),
        intervalSeconds: number(row.interval_seconds, `device_overrides[${index}].interval_seconds`),
      };
    }),
    effectiveDevices: root.effective_devices.map((item, index) => {
      const row = record(item);
      const cadenceSource = row?.cadence_source;
      if (!row || (cadenceSource !== "family_default" && cadenceSource !== "device_override")) {
        throw new CadenceClientError("invalid_response", `Некоректний effective device ${index}.`);
      }
      return {
        deviceId: string(row.device_id, `effective_devices[${index}].device_id`),
        busId: string(row.bus_id, `effective_devices[${index}].bus_id`),
        deviceFamily: family(row.device_family),
        lifecycle: string(row.lifecycle, `effective_devices[${index}].lifecycle`),
        effectiveIntervalSeconds: number(
          row.effective_interval_seconds,
          `effective_devices[${index}].effective_interval_seconds`,
        ),
        cadenceSource,
      };
    }),
    capacity: parseCapacity(root.capacity),
  };
}

function errorMessage(payload: unknown, fallback: string): string {
  const root = record(payload);
  if (!root) return fallback;
  if (typeof root.detail === "string" && root.detail.trim()) return root.detail;
  const detail = record(root.detail);
  if (detail && typeof detail.message === "string" && detail.message.trim()) return detail.message;
  return fallback;
}

async function responsePayload(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export function createCadenceClient(organizationId: string | null) {
  const authenticatedFetch = createAuthenticatedFetch(
    fetch.bind(globalThis),
    createRuntimeCredentialProvider(organizationId),
  );

  async function read(): Promise<AcquisitionCadenceConfiguration> {
    const response = await authenticatedFetch(ACQUISITION_CADENCE_URL, {
      method: "GET",
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    const payload = await responsePayload(response);
    if (!response.ok) {
      throw new CadenceClientError(
        response.status === 403
          ? "access_denied"
          : response.status === 503
            ? "device_agent_unavailable"
            : "request_failed",
        errorMessage(payload, `Не вдалося отримати cadence policy (HTTP ${response.status}).`),
        { status: response.status },
      );
    }
    return normalizeCadenceConfiguration(payload);
  }

  async function mutate(mutation: CadenceMutation): Promise<AcquisitionCadenceConfiguration> {
    const response = await authenticatedFetch(ACQUISITION_CADENCE_URL, {
      method: "PUT",
      cache: "no-store",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(mutation),
    });
    const payload = await responsePayload(response);
    if (!response.ok) {
      const root = record(payload);
      const code = root?.code;
      if (response.status === 422 && code === "acquisition_capacity_exceeded") {
        let capacity: AcquisitionCapacitySummary | null = null;
        try {
          capacity = parseCapacity(root?.capacity);
        } catch {
          capacity = null;
        }
        throw new CadenceClientError(
          "acquisition_capacity_exceeded",
          errorMessage(payload, "Запитаний інтервал перевищує безпечну місткість RS-485 шини."),
          { status: response.status, capacity },
        );
      }
      if (response.status === 409) {
        throw new CadenceClientError(
          "revision_conflict",
          "Cadence policy змінилася в іншій сесії. Оновіть канонічний стан і повторіть зміну.",
          { status: 409 },
        );
      }
      throw new CadenceClientError(
        response.status === 403
          ? "access_denied"
          : response.status === 503
            ? "device_agent_unavailable"
            : "request_failed",
        errorMessage(payload, `Не вдалося зберегти cadence policy (HTTP ${response.status}).`),
        { status: response.status },
      );
    }
    // The mutation response is intentionally not used as browser authority.
    // Re-read canonical persisted state so revision/capacity/rendered values all
    // come from the same post-commit Device Agent snapshot.
    return read();
  }

  return { read, mutate };
}
