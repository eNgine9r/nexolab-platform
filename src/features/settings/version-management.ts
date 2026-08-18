export type VersionAction = "update" | "rollback";

export type CurrentVersion = {
  bundleId: string;
  release: string;
  sourceCommit: string;
  buildTimestamp: string;
  runtimeMode: string;
  platform: string;
  schemaHead: string;
  deployedAt: string;
  health: string;
  previousBundleId: string | null;
  previousRelease: string | null;
  knownPackagedRelease: boolean;
  runtimeStateKnown: boolean;
};

export type VersionCatalogItem = {
  bundleId: string;
  release: string;
  sourceCommit: string;
  createdAt: string;
  platform: string;
  schemaHead: string;
  upgradeFrom: string[];
  runtimeCompatibleSchemaHeads: string[];
  manifestSha256: string;
};

export type VersionOperationPhase =
  | "verifying_package"
  | "checking_capacity"
  | "creating_backup"
  | "applying_update"
  | "verifying_runtime"
  | "done";

export type VersionOperation = {
  id: string;
  actorSubject: string;
  action: VersionAction;
  sourceRelease: string;
  targetRelease: string;
  targetBundleId: string;
  targetCommit: string;
  status: "queued" | "running" | "succeeded" | "failed";
  startedAt: string;
  endedAt: string | null;
  backupEvidenceId: string | null;
  capacityEvidenceId: string | null;
  resultCode: string | null;
  phase: VersionOperationPhase | null;
  phaseStatus: "running" | "succeeded" | "failed" | null;
  completedPhases: VersionOperationPhase[];
  safeMessage: string | null;
};

export type UpdatePolicy = {
  automaticUpdatesEnabled: boolean;
  scheduleLocalTime: "02:00";
  updatedAt: string | null;
  updatedBy: string | null;
  errorCode: string | null;
};

export type UpdateCheck = {
  status: "checking" | "completed" | "blocked" | "failed";
  source: "manual" | "scheduled" | "host";
  actor: string;
  startedAt: string | null;
  completedAt: string | null;
  resultCode: string | null;
  message: string | null;
  currentCommit: string | null;
  targetCommit: string | null;
  candidateAvailable: boolean;
  candidateBundleId: string | null;
  greenRevisionVerified: boolean;
  activationEligible: boolean;
  automaticActivationOperationId: string | null;
  blockedReason: string | null;
};

export type QueuedUpdateCheck = {
  id: string;
  actorSubject: string;
  source: "manual";
  status: "queued";
  requestedAt: string;
  reason: string | null;
};

export type VersionSnapshot = {
  current: CurrentVersion | null;
  catalog: VersionCatalogItem[];
  history: VersionOperation[];
  activeOperation: VersionOperation | null;
  rejectedPackages: { directory: string; code: string; message: string }[];
  updatePolicy: UpdatePolicy;
  updateCheck: UpdateCheck | null;
  offline: true;
};

export class VersionManagementApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export class VersionManagementClient {
  private readonly base: string;

  constructor(
    apiBaseUrl: string,
    private readonly fetchImpl: typeof fetch,
  ) {
    this.base = new URL(apiBaseUrl).toString().replace(/\/$/, "");
  }

  async read(): Promise<VersionSnapshot> {
    return parseSnapshot(await this.request("", { method: "GET" }));
  }

  async setAutomaticUpdates(enabled: boolean): Promise<UpdatePolicy> {
    return parseUpdatePolicy(
      await this.request("/update/policy", {
        method: "PUT",
        body: JSON.stringify({ automatic_updates_enabled: enabled }),
      }),
    );
  }

  async requestUpdateCheck(reason?: string): Promise<QueuedUpdateCheck> {
    return parseQueuedUpdateCheck(
      await this.request("/update/checks", {
        method: "POST",
        body: JSON.stringify({ reason: reason?.trim() || null }),
      }),
    );
  }

  async requestAction(input: {
    action: VersionAction;
    targetBundleId: string;
    confirmation: string;
    reason?: string;
  }): Promise<VersionOperation> {
    return parseOperation(
      await this.request("/actions", {
        method: "POST",
        body: JSON.stringify({
          action: input.action,
          target_bundle_id: input.targetBundleId,
          confirmation: input.confirmation,
          reason: input.reason?.trim() || null,
        }),
      }),
    );
  }

  private async request(path: string, init: RequestInit): Promise<unknown> {
    const response = await this.fetchImpl(`${this.base}/api/v1/system/version${path}`, {
      ...init,
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
      },
    });
    const payload = await readJson(response);
    if (!response.ok) {
      const detail = record(record(payload)?.detail);
      throw new VersionManagementApiError(
        response.status,
        text(detail?.code) ?? "version_management_error",
        text(detail?.message) ?? `Version API returned HTTP ${response.status}.`,
      );
    }
    return payload;
  }
}

function parseSnapshot(value: unknown): VersionSnapshot {
  const row = record(value);
  if (
    !row ||
    !Array.isArray(row.catalog) ||
    !Array.isArray(row.history) ||
    !Array.isArray(row.rejected_packages) ||
    !record(row.update_policy)
  ) {
    throw invalidResponse();
  }
  return {
    current: row.current === null ? null : parseCurrent(row.current),
    catalog: row.catalog.map(parseCatalog),
    history: row.history.map(parseOperation),
    activeOperation: row.active_operation === null ? null : parseOperation(row.active_operation),
    rejectedPackages: row.rejected_packages.map((item) => {
      const rejected = record(item);
      const directory = text(rejected?.directory);
      const code = text(rejected?.code);
      const message = text(rejected?.message);
      if (!directory || !code || !message) throw invalidResponse();
      return { directory, code, message };
    }),
    updatePolicy: parseUpdatePolicy(row.update_policy),
    updateCheck: row.update_check === null ? null : parseUpdateCheck(row.update_check),
    offline: true,
  };
}

function parseCurrent(value: unknown): CurrentVersion {
  const row = record(value);
  const required = [
    "bundle_id",
    "release",
    "source_commit",
    "build_timestamp",
    "runtime_mode",
    "platform",
    "schema_head",
    "deployed_at",
    "health",
  ] as const;
  if (!row || required.some((key) => !text(row[key])) || typeof row.known_packaged_release !== "boolean") {
    throw invalidResponse();
  }
  return {
    bundleId: text(row.bundle_id)!,
    release: text(row.release)!,
    sourceCommit: text(row.source_commit)!,
    buildTimestamp: text(row.build_timestamp)!,
    runtimeMode: text(row.runtime_mode)!,
    platform: text(row.platform)!,
    schemaHead: text(row.schema_head)!,
    deployedAt: text(row.deployed_at)!,
    health: text(row.health)!,
    previousBundleId: optionalText(row.previous_bundle_id),
    previousRelease: optionalText(row.previous_release),
    knownPackagedRelease: row.known_packaged_release,
    runtimeStateKnown: row.runtime_state_known === true,
  };
}

function parseCatalog(value: unknown): VersionCatalogItem {
  const row = record(value);
  if (!row || !Array.isArray(row.upgrade_from) || !Array.isArray(row.runtime_compatible_schema_heads)) {
    throw invalidResponse();
  }
  const fields = [
    "bundle_id",
    "release",
    "source_commit",
    "created_at",
    "platform",
    "schema_head",
    "manifest_sha256",
  ] as const;
  if (fields.some((key) => !text(row[key]))) throw invalidResponse();
  return {
    bundleId: text(row.bundle_id)!,
    release: text(row.release)!,
    sourceCommit: text(row.source_commit)!,
    createdAt: text(row.created_at)!,
    platform: text(row.platform)!,
    schemaHead: text(row.schema_head)!,
    upgradeFrom: row.upgrade_from.map(requiredText),
    runtimeCompatibleSchemaHeads: row.runtime_compatible_schema_heads.map(requiredText),
    manifestSha256: text(row.manifest_sha256)!,
  };
}

function parseUpdatePolicy(value: unknown): UpdatePolicy {
  const row = record(value);
  if (!row || typeof row.automatic_updates_enabled !== "boolean" || row.schedule_local_time !== "02:00") {
    throw invalidResponse();
  }
  return {
    automaticUpdatesEnabled: row.automatic_updates_enabled,
    scheduleLocalTime: "02:00",
    updatedAt: optionalText(row.updated_at),
    updatedBy: optionalText(row.updated_by),
    errorCode: optionalText(row.error_code),
  };
}

function parseUpdateCheck(value: unknown): UpdateCheck {
  const row = record(value);
  const checkStatus = row?.status;
  const source = row?.source;
  if (
    !row ||
    !["checking", "completed", "blocked", "failed"].includes(String(checkStatus)) ||
    !["manual", "scheduled", "host"].includes(String(source)) ||
    typeof row.candidate_available !== "boolean" ||
    typeof row.activation_eligible !== "boolean"
  ) {
    throw invalidResponse();
  }
  return {
    status: checkStatus as UpdateCheck["status"],
    source: source as UpdateCheck["source"],
    actor: requiredText(row.actor),
    startedAt: optionalText(row.started_at),
    completedAt: optionalText(row.completed_at),
    resultCode: optionalText(row.result_code),
    message: optionalText(row.message),
    currentCommit: optionalText(row.current_commit),
    targetCommit: optionalText(row.target_commit),
    candidateAvailable: row.candidate_available,
    candidateBundleId: optionalText(row.candidate_bundle_id),
    greenRevisionVerified: row.green_revision_verified === true,
    activationEligible: row.activation_eligible,
    automaticActivationOperationId: optionalText(row.automatic_activation_operation_id),
    blockedReason: optionalText(row.blocked_reason),
  };
}

function parseQueuedUpdateCheck(value: unknown): QueuedUpdateCheck {
  const row = record(value);
  if (!row || row.source !== "manual" || row.status !== "queued") {
    throw invalidResponse();
  }
  return {
    id: requiredText(row.id),
    actorSubject: requiredText(row.actor_subject),
    source: "manual",
    status: "queued",
    requestedAt: requiredText(row.requested_at),
    reason: optionalText(row.reason),
  };
}

function parseOperation(value: unknown): VersionOperation {
  const row = record(value);
  const action = row?.action;
  const operationStatus = row?.status;
  if (
    !row ||
    (action !== "update" && action !== "rollback") ||
    !["queued", "running", "succeeded", "failed"].includes(String(operationStatus))
  ) {
    throw invalidResponse();
  }
  const phase = parseOperationPhase(row.phase);
  const phaseStatus = row.phase_status;
  if (row.phase_status != null && !["running", "succeeded", "failed"].includes(String(phaseStatus))) {
    throw invalidResponse();
  }
  const completedPhases = Array.isArray(row.completed_phases)
    ? row.completed_phases.map((item) => {
        const parsed = parseOperationPhase(item);
        if (!parsed) throw invalidResponse();
        return parsed;
      })
    : [];
  return {
    id: requiredText(row.id),
    actorSubject: requiredText(row.actor_subject),
    action,
    sourceRelease: requiredText(row.source_release),
    targetRelease: requiredText(row.target_release),
    targetBundleId: requiredText(row.target_bundle_id),
    targetCommit: requiredText(row.target_commit),
    status: operationStatus as VersionOperation["status"],
    startedAt: requiredText(row.started_at),
    endedAt: optionalText(row.ended_at),
    backupEvidenceId: optionalText(row.backup_evidence_id),
    capacityEvidenceId: optionalText(row.capacity_evidence_id),
    resultCode: optionalText(row.result_code),
    phase,
    phaseStatus: phaseStatus == null ? null : (phaseStatus as VersionOperation["phaseStatus"]),
    completedPhases,
    safeMessage: optionalText(row.safe_message),
  };
}

function parseOperationPhase(value: unknown): VersionOperationPhase | null {
  if (value == null) return null;
  if (
    ![
      "verifying_package",
      "checking_capacity",
      "creating_backup",
      "applying_update",
      "verifying_runtime",
      "done",
    ].includes(String(value))
  ) {
    throw invalidResponse();
  }
  return value as VersionOperationPhase;
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function optionalText(value: unknown): string | null {
  return value == null ? null : text(value);
}

function requiredText(value: unknown): string {
  const valueText = text(value);
  if (!valueText) throw invalidResponse();
  return valueText;
}

async function readJson(response: Response): Promise<unknown> {
  const body = await response.text();
  try {
    return body ? (JSON.parse(body) as unknown) : null;
  } catch {
    return null;
  }
}

function invalidResponse(): VersionManagementApiError {
  return new VersionManagementApiError(
    502,
    "invalid_version_response",
    "Відповідь Version API не відповідає контракту.",
  );
}
