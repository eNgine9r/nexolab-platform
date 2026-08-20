export type EquipmentDiscoveryScanStatus = "running" | "completed" | "cancelled" | "failed";
export type EquipmentDiscoveryCandidateLifecycle =
  "new" | "reviewed" | "matched_existing" | "adopted" | "ignored" | "disappeared";

export type EquipmentDiscoveryServiceEvidence = {
  port: number;
  transport: "tcp";
  service: string;
  evidence: "connect_succeeded";
};

export type EquipmentDiscoveryScan = {
  id: string;
  status: EquipmentDiscoveryScanStatus;
  requestedCidrs: string[];
  requestedPorts: number[];
  hostBudget: number;
  probeBudget: number;
  hostsConsidered: number;
  probesAttempted: number;
  responsiveHosts: number;
  durationMs: number;
  processCpuMs: number;
  networkConnectAttempts: number;
  networkPayloadBytes: number;
  trigger: "manual" | "scheduled";
  newCandidates: number;
  changedCandidates: number;
  disappearedCandidates: number;
  cancelRequested: boolean;
  requestedBy: string;
  startedAt: string;
  completedAt: string | null;
  errorCode: string | null;
  errorMessage: string | null;
};

export type EquipmentDiscoveryCandidate = {
  id: string;
  candidateKey: string;
  ipAddress: string;
  macAddress: string | null;
  hostname: string | null;
  sourceInterface: string | null;
  sourceSubnet: string;
  lifecycle: EquipmentDiscoveryCandidateLifecycle;
  present: boolean;
  firstSeenAt: string;
  lastSeenAt: string;
  lastScanId: string;
  linkedEquipmentKey: string | null;
  version: number;
  services: EquipmentDiscoveryServiceEvidence[];
  evidence: Record<string, unknown>;
  changedSincePreviousScan: boolean;
};

export type EquipmentNetworkAsset = {
  id: string;
  assetKey: string;
  displayName: string;
  ipAddress: string;
  macAddress: string | null;
  manufacturer: string | null;
  model: string | null;
  sourceCandidateId: string;
  status: "active" | "inactive";
  version: number;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
};

export type EquipmentDiscoveryPolicy = {
  enabled: boolean;
  allowedCidrs: string[];
  allowedPorts: number[];
  maxHosts: number;
  maxPorts: number;
  connectTimeoutSeconds: number;
  concurrency: number;
  scheduleIntervalSeconds: number;
  probeMode: "tcp-connect-only";
  payloadBytesSentPerProbe: 0;
};

export type EquipmentDiscoveryOverview = {
  policy: EquipmentDiscoveryPolicy;
  activeScan: EquipmentDiscoveryScan | null;
  lastScan: EquipmentDiscoveryScan | null;
  candidates: EquipmentDiscoveryCandidate[];
  networkAssets: EquipmentNetworkAsset[];
};

export type EquipmentDiscoveryCandidateAction =
  | { action: "review" | "ignore" }
  | { action: "link_existing"; linkedEquipmentKey: string }
  | { action: "adopt"; displayName: string };

export interface EquipmentDiscoveryRepository {
  getOverview(): Promise<EquipmentDiscoveryOverview>;
  startScan(input: { cidrs: string[]; ports: number[] }): Promise<EquipmentDiscoveryScan>;
  cancelScan(scanId: string): Promise<EquipmentDiscoveryScan>;
  actOnCandidate(
    candidateId: string,
    input: EquipmentDiscoveryCandidateAction,
    expectedVersion: number,
  ): Promise<{ candidate: EquipmentDiscoveryCandidate; networkAsset: EquipmentNetworkAsset | null }>;
}

export class EquipmentDiscoveryRepositoryError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number | null = null,
  ) {
    super(message);
    this.name = "EquipmentDiscoveryRepositoryError";
  }
}

export class HttpEquipmentDiscoveryRepository implements EquipmentDiscoveryRepository {
  private readonly apiBaseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: { apiBaseUrl: string; fetchImpl?: typeof fetch }) {
    this.apiBaseUrl = normalizeBaseUrl(options.apiBaseUrl);
    this.fetchImpl = options.fetchImpl ?? fetch.bind(globalThis);
  }

  async getOverview(): Promise<EquipmentDiscoveryOverview> {
    return parseOverview(await this.request("/api/v1/equipment-discovery", { method: "GET" }));
  }

  async startScan(input: { cidrs: string[]; ports: number[] }): Promise<EquipmentDiscoveryScan> {
    const payload = await this.request("/api/v1/equipment-discovery/scans", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cidrs: input.cidrs, ports: input.ports }),
    });
    return parseScan(payload);
  }

  async cancelScan(scanId: string): Promise<EquipmentDiscoveryScan> {
    return parseScan(
      await this.request(`/api/v1/equipment-discovery/scans/${encodeURIComponent(scanId)}/cancel`, {
        method: "POST",
      }),
    );
  }

  async actOnCandidate(
    candidateId: string,
    input: EquipmentDiscoveryCandidateAction,
    expectedVersion: number,
  ): Promise<{ candidate: EquipmentDiscoveryCandidate; networkAsset: EquipmentNetworkAsset | null }> {
    const body: Record<string, unknown> = { action: input.action };
    if (input.action === "link_existing") body.linked_equipment_key = input.linkedEquipmentKey;
    if (input.action === "adopt") body.display_name = input.displayName;
    const payload = asRecord(
      await this.request(`/api/v1/equipment-discovery/candidates/${encodeURIComponent(candidateId)}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "If-Match": `W/"equipment-discovery-candidate-v${expectedVersion}"`,
          "X-Audit-Reason": candidateAuditReason(input.action),
        },
        body: JSON.stringify(body),
      }),
    );
    if (!payload) throw invalidResponse();
    return {
      candidate: parseCandidate(payload.candidate),
      networkAsset: payload.network_asset === null ? null : parseNetworkAsset(payload.network_asset),
    };
  }

  private async request(path: string, init: RequestInit): Promise<unknown> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.apiBaseUrl}${path}`, {
        ...init,
        credentials: init.credentials ?? "same-origin",
        headers: { Accept: "application/json", ...init.headers },
      });
    } catch {
      throw new EquipmentDiscoveryRepositoryError(
        "Не вдалося з’єднатися з локальним сервісом виявлення обладнання.",
        "request_failed",
      );
    }
    const payload = await readJson(response);
    if (!response.ok) {
      const detail = asRecord(asRecord(payload)?.detail);
      throw new EquipmentDiscoveryRepositoryError(
        readString(detail?.message) ?? "Операція виявлення обладнання не виконана.",
        readString(detail?.code) ?? "request_failed",
        response.status,
      );
    }
    return payload;
  }
}

function parseOverview(value: unknown): EquipmentDiscoveryOverview {
  const record = asRecord(value);
  if (!record) throw invalidResponse();
  return {
    policy: parsePolicy(record.policy),
    activeScan: record.active_scan === null ? null : parseScan(record.active_scan),
    lastScan: record.last_scan === null ? null : parseScan(record.last_scan),
    candidates: readArray(record.candidates).map(parseCandidate),
    networkAssets: readArray(record.network_assets).map(parseNetworkAsset),
  };
}

function parsePolicy(value: unknown): EquipmentDiscoveryPolicy {
  const record = asRecord(value);
  const enabled = record?.enabled;
  const maxHosts = readPositiveInteger(record?.max_hosts);
  const maxPorts = readPositiveInteger(record?.max_ports);
  const timeout = readPositiveNumber(record?.connect_timeout_seconds);
  const concurrency = readPositiveInteger(record?.concurrency);
  const scheduleIntervalSeconds = readNonNegativeInteger(record?.schedule_interval_seconds);
  if (
    typeof enabled !== "boolean" ||
    maxHosts === null ||
    maxPorts === null ||
    timeout === null ||
    concurrency === null ||
    scheduleIntervalSeconds === null ||
    record?.probe_mode !== "tcp-connect-only" ||
    record?.payload_bytes_sent_per_probe !== 0
  ) {
    throw invalidResponse();
  }
  return {
    enabled,
    allowedCidrs: readStringArray(record.allowed_cidrs),
    allowedPorts: readIntegerArray(record.allowed_ports),
    maxHosts,
    maxPorts,
    connectTimeoutSeconds: timeout,
    concurrency,
    scheduleIntervalSeconds,
    probeMode: "tcp-connect-only",
    payloadBytesSentPerProbe: 0,
  };
}

function parseScan(value: unknown): EquipmentDiscoveryScan {
  const record = asRecord(value);
  if (!record) throw invalidResponse();
  const id = readString(record?.id);
  const status = record?.status;
  const requestedBy = readString(record?.requested_by);
  const startedAt = readString(record?.started_at);
  const trigger = record?.trigger;
  if (
    !id ||
    (status !== "running" && status !== "completed" && status !== "cancelled" && status !== "failed") ||
    !requestedBy ||
    !startedAt ||
    (trigger !== "manual" && trigger !== "scheduled")
  ) {
    throw invalidResponse();
  }
  return {
    id,
    status,
    requestedCidrs: readStringArray(record.requested_cidrs),
    requestedPorts: readIntegerArray(record.requested_ports),
    hostBudget: requiredInteger(record.host_budget),
    probeBudget: requiredInteger(record.probe_budget),
    hostsConsidered: requiredInteger(record.hosts_considered),
    probesAttempted: requiredInteger(record.probes_attempted),
    responsiveHosts: requiredInteger(record.responsive_hosts),
    durationMs: requiredInteger(record.duration_ms),
    processCpuMs: requiredInteger(record.process_cpu_ms),
    networkConnectAttempts: requiredInteger(record.network_connect_attempts),
    networkPayloadBytes: requiredInteger(record.network_payload_bytes),
    trigger,
    newCandidates: requiredInteger(record.new_candidates),
    changedCandidates: requiredInteger(record.changed_candidates),
    disappearedCandidates: requiredInteger(record.disappeared_candidates),
    cancelRequested: Boolean(record.cancel_requested),
    requestedBy,
    startedAt,
    completedAt: readOptionalString(record.completed_at),
    errorCode: readOptionalString(record.error_code),
    errorMessage: readOptionalString(record.error_message),
  };
}

function parseCandidate(value: unknown): EquipmentDiscoveryCandidate {
  const record = asRecord(value);
  if (!record) throw invalidResponse();
  const id = readString(record?.id);
  const candidateKey = readString(record?.candidate_key);
  const ipAddress = readString(record?.ip_address);
  const sourceSubnet = readString(record?.source_subnet);
  const lifecycle = record?.lifecycle;
  const firstSeenAt = readString(record?.first_seen_at);
  const lastSeenAt = readString(record?.last_seen_at);
  const lastScanId = readString(record?.last_scan_id);
  const version = readPositiveInteger(record?.version);
  if (
    !id ||
    !candidateKey ||
    !ipAddress ||
    !sourceSubnet ||
    !isLifecycle(lifecycle) ||
    !firstSeenAt ||
    !lastSeenAt ||
    !lastScanId ||
    version === null
  ) {
    throw invalidResponse();
  }
  return {
    id,
    candidateKey,
    ipAddress,
    macAddress: readOptionalString(record.mac_address),
    hostname: readOptionalString(record.hostname),
    sourceInterface: readOptionalString(record.source_interface),
    sourceSubnet,
    lifecycle,
    present: Boolean(record.present),
    firstSeenAt,
    lastSeenAt,
    lastScanId,
    linkedEquipmentKey: readOptionalString(record.linked_equipment_key),
    version,
    services: readArray(record.services).map(parseServiceEvidence),
    evidence: asRecord(record.evidence) ?? {},
    changedSincePreviousScan: Boolean(record.changed_since_previous_scan),
  };
}

function parseServiceEvidence(value: unknown): EquipmentDiscoveryServiceEvidence {
  const record = asRecord(value);
  const port = readPositiveInteger(record?.port);
  const service = readString(record?.service);
  if (port === null || !service || record?.transport !== "tcp" || record?.evidence !== "connect_succeeded") {
    throw invalidResponse();
  }
  return { port, transport: "tcp", service, evidence: "connect_succeeded" };
}

function parseNetworkAsset(value: unknown): EquipmentNetworkAsset {
  const record = asRecord(value);
  if (!record) throw invalidResponse();
  const id = readString(record?.id);
  const assetKey = readString(record?.asset_key);
  const displayName = readString(record?.display_name);
  const ipAddress = readString(record?.ip_address);
  const sourceCandidateId = readString(record?.source_candidate_id);
  const status = record?.status;
  const version = readPositiveInteger(record?.version);
  const createdBy = readString(record?.created_by);
  const createdAt = readString(record?.created_at);
  const updatedAt = readString(record?.updated_at);
  if (
    !id ||
    !assetKey ||
    !displayName ||
    !ipAddress ||
    !sourceCandidateId ||
    (status !== "active" && status !== "inactive") ||
    version === null ||
    !createdBy ||
    !createdAt ||
    !updatedAt
  ) {
    throw invalidResponse();
  }
  return {
    id,
    assetKey,
    displayName,
    ipAddress,
    macAddress: readOptionalString(record.mac_address),
    manufacturer: readOptionalString(record.manufacturer),
    model: readOptionalString(record.model),
    sourceCandidateId,
    status,
    version,
    createdBy,
    createdAt,
    updatedAt,
  };
}

function isLifecycle(value: unknown): value is EquipmentDiscoveryCandidateLifecycle {
  return (
    value === "new" ||
    value === "reviewed" ||
    value === "matched_existing" ||
    value === "adopted" ||
    value === "ignored" ||
    value === "disappeared"
  );
}

function candidateAuditReason(action: EquipmentDiscoveryCandidateAction["action"]): string {
  if (action === "review") return "Reviewed LOCAL_LAN discovery evidence";
  if (action === "ignore") return "Ignored LOCAL_LAN discovery candidate";
  if (action === "link_existing") return "Linked LOCAL_LAN discovery candidate to canonical equipment";
  return "Adopted LOCAL_LAN discovery candidate as administrative network asset";
}

function normalizeBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw invalidResponse();
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readArray(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw invalidResponse();
  return value;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function readOptionalString(value: unknown): string | null {
  return value === null || value === undefined ? null : readString(value);
}

function readStringArray(value: unknown): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || !item.trim())) {
    throw invalidResponse();
  }
  return value.map((item) => String(item));
}

function readIntegerArray(value: unknown): number[] {
  if (!Array.isArray(value) || value.some((item) => !Number.isInteger(item))) throw invalidResponse();
  return value.map(Number);
}

function readNonNegativeInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function readPositiveInteger(value: unknown): number | null {
  return Number.isInteger(value) && Number(value) > 0 ? Number(value) : null;
}

function readPositiveNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

function requiredInteger(value: unknown): number {
  if (!Number.isInteger(value) || Number(value) < 0) throw invalidResponse();
  return Number(value);
}

function invalidResponse(): EquipmentDiscoveryRepositoryError {
  return new EquipmentDiscoveryRepositoryError(
    "Сервіс виявлення обладнання повернув некоректну відповідь.",
    "invalid_response",
  );
}
