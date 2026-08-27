import { CHART_MINIMUM_SOURCE_GAP_MS, CHART_SOURCE_GAP_MULTIPLIER } from "@/features/charts/continuity";

const ENERGY_DEVICE_FAMILY = "le01mp";
const ENERGY_DEVICE_PREFIX = "le01mp-";

type UnknownRecord = Record<string, unknown>;

type EnergyRegistryDevice = {
  unitId: number;
  deviceId: string;
  busId: string;
};

type CadencePolicyState = {
  familyDefaults: Map<string, number>;
  deviceOverrides: Map<string, number>;
};

type AuditRecord = {
  revision: number;
  changedAtMs: number;
  changes: UnknownRecord[];
};

type CadenceCheckpoint = {
  revision: number;
  atMs: number;
  intervalMsByUnitId: Map<number, number>;
};

export interface EnergyCadenceAuthority {
  revision: number;
  updatedAt: string;
  fingerprint: string;
  coverageStartsAtMs: number;
  intervalMsAt: (unitId: number, capturedAtMs: number) => number | null;
  maximumSourceGapMs: (unitId: number, previousAtMs: number, capturedAtMs: number) => number | null;
}

function record(value: unknown): UnknownRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as UnknownRecord)
    : null;
}

function finitePositiveNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

function positiveInteger(value: unknown): number | null {
  return Number.isInteger(value) && typeof value === "number" && value > 0 ? value : null;
}

function timestampMs(value: unknown): number | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function familyKey(busId: string, deviceFamily: string): string {
  return `${busId}/${deviceFamily}`;
}

function clonePolicy(policy: CadencePolicyState): CadencePolicyState {
  return {
    familyDefaults: new Map(policy.familyDefaults),
    deviceOverrides: new Map(policy.deviceOverrides),
  };
}

function parseDevices(root: UnknownRecord): EnergyRegistryDevice[] | null {
  if (!Array.isArray(root.devices)) return null;
  const devices: EnergyRegistryDevice[] = [];

  for (const value of root.devices) {
    const item = record(value);
    if (!item || item.device_family !== ENERGY_DEVICE_FAMILY) continue;
    const unitId = positiveInteger(item.unit_id);
    const deviceId = typeof item.device_id === "string" ? item.device_id.trim() : "";
    const busId = typeof item.bus_id === "string" ? item.bus_id.trim() : "";
    if (unitId === null || !deviceId.startsWith(ENERGY_DEVICE_PREFIX) || !busId) return null;
    devices.push({ unitId, deviceId, busId });
  }

  return devices.length > 0 ? devices : null;
}

function parseCurrentPolicy(root: UnknownRecord): CadencePolicyState | null {
  const cadence = record(root.cadence);
  if (!cadence || !Array.isArray(cadence.family_defaults) || !Array.isArray(cadence.device_overrides)) {
    return null;
  }

  const familyDefaults = new Map<string, number>();
  for (const value of cadence.family_defaults) {
    const item = record(value);
    if (!item) return null;
    const busId = typeof item.bus_id === "string" ? item.bus_id.trim() : "";
    const deviceFamily = typeof item.device_family === "string" ? item.device_family.trim() : "";
    const intervalSeconds = finitePositiveNumber(item.interval_seconds);
    if (!busId || !deviceFamily || intervalSeconds === null) return null;
    familyDefaults.set(familyKey(busId, deviceFamily), intervalSeconds * 1_000);
  }

  const deviceOverrides = new Map<string, number>();
  for (const value of cadence.device_overrides) {
    const item = record(value);
    if (!item) return null;
    const deviceId = typeof item.device_id === "string" ? item.device_id.trim() : "";
    const intervalSeconds = finitePositiveNumber(item.interval_seconds);
    if (!deviceId || intervalSeconds === null) return null;
    deviceOverrides.set(deviceId, intervalSeconds * 1_000);
  }

  return { familyDefaults, deviceOverrides };
}

function effectiveIntervals(
  policy: CadencePolicyState,
  devices: readonly EnergyRegistryDevice[],
): Map<number, number> | null {
  const result = new Map<number, number>();
  for (const device of devices) {
    const intervalMs =
      policy.deviceOverrides.get(device.deviceId) ??
      policy.familyDefaults.get(familyKey(device.busId, ENERGY_DEVICE_FAMILY));
    if (intervalMs === undefined || !Number.isFinite(intervalMs) || intervalMs <= 0) return null;
    result.set(device.unitId, intervalMs);
  }
  return result;
}

function parseAudit(root: UnknownRecord): AuditRecord[] | null {
  if (!Array.isArray(root.recent_audit)) return null;
  const result: AuditRecord[] = [];
  for (const value of root.recent_audit) {
    const item = record(value);
    if (!item || !Array.isArray(item.changes)) return null;
    const revision = positiveInteger(item.revision);
    const changedAtMs = timestampMs(item.changed_at);
    const changes = item.changes.map(record);
    if (revision === null || changedAtMs === null || changes.some((change) => change === null)) return null;
    result.push({ revision, changedAtMs, changes: changes as UnknownRecord[] });
  }
  return result.sort((left, right) => right.revision - left.revision || right.changedAtMs - left.changedAtMs);
}

function numericAuditSeconds(value: unknown): number | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function reverseRelevantAudit(policy: CadencePolicyState, audit: AuditRecord): boolean {
  for (const change of audit.changes) {
    const entity = change.entity;
    const id = typeof change.id === "string" ? change.id.trim() : "";
    if (entity === "cadence_family_default" && id.endsWith(`/${ENERGY_DEVICE_FAMILY}`)) {
      const previousSeconds = numericAuditSeconds(change.from);
      if (previousSeconds === null) return false;
      policy.familyDefaults.set(id, previousSeconds * 1_000);
      continue;
    }
    if (entity === "cadence_device_override" && id.startsWith(ENERGY_DEVICE_PREFIX)) {
      const previousSeconds = numericAuditSeconds(change.from);
      if (previousSeconds !== null) {
        policy.deviceOverrides.set(id, previousSeconds * 1_000);
        continue;
      }
      if (
        typeof change.from === "string" &&
        (change.from.startsWith("inherited:") || change.from === "absent")
      ) {
        policy.deviceOverrides.delete(id);
        continue;
      }
      return false;
    }
  }
  return true;
}

function maximumPiecewiseSourceGapMs(
  checkpoints: readonly CadenceCheckpoint[],
  intervalMsAt: (unitId: number, capturedAtMs: number) => number | null,
  unitId: number,
  previousAtMs: number,
  capturedAtMs: number,
): number | null {
  if (!Number.isFinite(previousAtMs) || !Number.isFinite(capturedAtMs) || capturedAtMs < previousAtMs) {
    return null;
  }

  let intervalMs = intervalMsAt(unitId, previousAtMs);
  if (intervalMs === null) return null;

  let cursorMs = previousAtMs;
  let remainingIntervals = CHART_SOURCE_GAP_MULTIPLIER;
  for (const checkpoint of checkpoints) {
    if (checkpoint.atMs <= previousAtMs) continue;
    if (checkpoint.atMs > capturedAtMs) break;

    const segmentMs = checkpoint.atMs - cursorMs;
    const consumedIntervals = segmentMs / intervalMs;
    if (consumedIntervals >= remainingIntervals) {
      const thresholdMs = cursorMs - previousAtMs + remainingIntervals * intervalMs;
      return Math.max(CHART_MINIMUM_SOURCE_GAP_MS, thresholdMs);
    }

    remainingIntervals -= consumedIntervals;
    cursorMs = checkpoint.atMs;
    intervalMs = checkpoint.intervalMsByUnitId.get(unitId) ?? NaN;
    if (!Number.isFinite(intervalMs) || intervalMs <= 0) return null;
  }

  const thresholdMs = cursorMs - previousAtMs + remainingIntervals * intervalMs;
  return Math.max(CHART_MINIMUM_SOURCE_GAP_MS, thresholdMs);
}

export function buildEnergyCadenceAuthority(value: unknown): EnergyCadenceAuthority | null {
  const root = record(value);
  if (!root) return null;
  const revision = positiveInteger(root.revision);
  const updatedAtMs = timestampMs(root.updated_at);
  const updatedAt = typeof root.updated_at === "string" ? root.updated_at : "";
  const devices = parseDevices(root);
  const currentPolicy = parseCurrentPolicy(root);
  const audit = parseAudit(root);
  if (revision === null || updatedAtMs === null || !devices || !currentPolicy || audit === null) return null;

  const currentIntervals = effectiveIntervals(currentPolicy, devices);
  if (!currentIntervals) return null;

  const checkpoints: CadenceCheckpoint[] = [];
  let coverageStartsAtMs = updatedAtMs;
  let workingPolicy = clonePolicy(currentPolicy);

  if (audit.length === 0) {
    checkpoints.push({ revision, atMs: updatedAtMs, intervalMsByUnitId: currentIntervals });
  } else {
    for (const item of audit) {
      const afterIntervals = effectiveIntervals(workingPolicy, devices);
      if (!afterIntervals) break;
      checkpoints.push({
        revision: item.revision,
        atMs: item.changedAtMs,
        intervalMsByUnitId: afterIntervals,
      });
      coverageStartsAtMs = item.changedAtMs;

      const previousPolicy = clonePolicy(workingPolicy);
      if (!reverseRelevantAudit(previousPolicy, item)) break;
      workingPolicy = previousPolicy;
    }
  }

  const chronological = checkpoints.sort(
    (left, right) => left.atMs - right.atMs || left.revision - right.revision,
  );
  if (chronological.length === 0) return null;
  coverageStartsAtMs = chronological[0].atMs;

  const intervalMsAt = (unitId: number, capturedAtMs: number): number | null => {
    if (!Number.isFinite(capturedAtMs) || capturedAtMs < coverageStartsAtMs) return null;
    let selected: CadenceCheckpoint | null = null;
    for (const checkpoint of chronological) {
      if (checkpoint.atMs > capturedAtMs) break;
      selected = checkpoint;
    }
    return selected?.intervalMsByUnitId.get(unitId) ?? null;
  };

  return {
    revision,
    updatedAt,
    fingerprint: `${revision}:${updatedAt}:${coverageStartsAtMs}`,
    coverageStartsAtMs,
    intervalMsAt,
    maximumSourceGapMs: (unitId, previousAtMs, capturedAtMs) =>
      maximumPiecewiseSourceGapMs(chronological, intervalMsAt, unitId, previousAtMs, capturedAtMs),
  };
}

export const ENERGY_CADENCE_AUTHORITY_URL = "/api/device-agent/acquisition-registry";

export type EnergyCadenceAuthorityFetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export async function readEnergyCadenceAuthority(
  authenticatedFetch: EnergyCadenceAuthorityFetch,
  signal?: AbortSignal,
): Promise<EnergyCadenceAuthority | null> {
  try {
    const response = await authenticatedFetch(ENERGY_CADENCE_AUTHORITY_URL, {
      method: "GET",
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal,
    });
    if (!response.ok) return null;
    return buildEnergyCadenceAuthority(await response.json());
  } catch (error) {
    if (signal?.aborted) throw error;
    return null;
  }
}
