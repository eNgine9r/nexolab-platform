export type SecurityProductRole =
  | "administrator"
  | "laboratory_manager"
  | "engineer"
  | "laboratory_technician";

export type SecurityLegacyRole = "operator" | "viewer" | "auditor";

export type SecurityRole = SecurityProductRole | SecurityLegacyRole;

export type SecurityPermission =
  | "dashboard.read"
  | "live_dashboards.manage"
  | "telemetry.read"
  | "alerts.read"
  | "audit.read"
  | "reports.read"
  | "nodes.read"
  | "reports.generate"
  | "reports.approve"
  | "memberships.manage"
  | "equipment.manage"
  | "nodes.manage"
  | "layout.draft.edit"
  | "layout.publish"
  | "layout.restore"
  | "sessions.manage"
  | "sessions.operate"
  | "alerts.rules.manage"
  | "alerts.acknowledge"
  | "project_versions.manage";

export type SecurityEffectivePermission = SecurityPermission;

export type SecurityIdentity = {
  id: string;
  provider: string;
  subject: string;
  email: string | null;
  displayName: string | null;
};

export type SecurityMembership = {
  organizationId: string;
  organizationSlug: string;
  organizationName: string;
  roles: SecurityRole[];
  permissions: SecurityEffectivePermission[];
};

export type SecuritySession = {
  authenticated: true;
  identity: SecurityIdentity;
  memberships: SecurityMembership[];
};

export type SecuritySessionErrorCode =
  | "AUTHENTICATION_REQUIRED"
  | "ACCESS_DENIED"
  | "INVALID_RESPONSE"
  | "SESSION_API_ERROR"
  | "SESSION_REQUEST_TIMEOUT"
  | "SESSION_MIXED_CONTENT"
  | "SESSION_API_UNREACHABLE_OR_ORIGIN_BLOCKED";

export type SecuritySessionDiagnostics = {
  apiOrigin: string;
  browserOrigin: string | null;
  endpointPath: "/api/v1/auth/session";
  timeoutMs: number;
  httpStatus: number | null;
};

export type SecuritySessionFailure = {
  code: SecuritySessionErrorCode;
  message: string;
  diagnostics: SecuritySessionDiagnostics;
};

export type SecuritySessionResult =
  | { ok: true; value: SecuritySession }
  | {
      ok: false;
      error: SecuritySessionFailure;
    };

export type SecurityCredentialSnapshot = {
  accessToken: string | null;
  organizationId: string | null;
};

export type SecurityCredentialProvider = () =>
  SecurityCredentialSnapshot | Promise<SecurityCredentialSnapshot>;

type BrowserLocationSnapshot = {
  origin: string;
  protocol: string;
};

export type HttpSecuritySessionClientOptions = {
  apiBaseUrl: string;
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
  browserLocation?: BrowserLocationSnapshot | null;
};

const SESSION_ENDPOINT_PATH = "/api/v1/auth/session" as const;
const DEFAULT_SESSION_TIMEOUT_MS = 8_000;

export class HttpSecuritySessionClient {
  private readonly apiBaseUrl: string;
  private readonly apiOrigin: string;
  private readonly browserLocation: BrowserLocationSnapshot | null;
  private readonly fetchImpl: typeof fetch;
  private readonly requestTimeoutMs: number;

  constructor(options: HttpSecuritySessionClientOptions) {
    this.apiBaseUrl = normalizeBaseUrl(options.apiBaseUrl);
    this.apiOrigin = new URL(this.apiBaseUrl).origin;
    this.fetchImpl = options.fetchImpl ?? fetch.bind(globalThis);
    this.requestTimeoutMs = normalizeTimeout(options.requestTimeoutMs);
    this.browserLocation =
      options.browserLocation === undefined ? readBrowserLocation() : options.browserLocation;
  }

  async getSession(): Promise<SecuritySessionResult> {
    if (this.isMixedContentRequest()) {
      return this.failure(
        "SESSION_MIXED_CONTENT",
        "Захищена HTTPS-сторінка не може звертатися до HTTP API NEXOLAB. Використайте HTTPS API або відкрийте dashboard через HTTP у контрольованій локальній мережі.",
      );
    }

    const controller = new AbortController();
    const timeoutId = globalThis.setTimeout(() => controller.abort(), this.requestTimeoutMs);

    try {
      const response = await this.fetchImpl(`${this.apiBaseUrl}${SESSION_ENDPOINT_PATH}`, {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      const payload = await readJson(response);
      if (!response.ok) {
        const message = readErrorMessage(payload);
        if (response.status === 401) {
          return this.failure(
            "AUTHENTICATION_REQUIRED",
            message ?? "Потрібна автентифікація оператора.",
            response.status,
          );
        }
        if (response.status === 403) {
          return this.failure(
            "ACCESS_DENIED",
            message ?? "Поточний користувач не має доступу до вибраної організації.",
            response.status,
          );
        }
        return this.failure(
          "SESSION_API_ERROR",
          message ?? `API захищеної сесії повернув HTTP ${response.status}.`,
          response.status,
        );
      }

      const session = parseSecuritySession(payload);
      return session
        ? { ok: true, value: session }
        : this.failure(
            "INVALID_RESPONSE",
            "Відповідь сервера автентифікації не відповідає контракту.",
            response.status,
          );
    } catch (error) {
      if (controller.signal.aborted || isAbortError(error)) {
        return this.failure(
          "SESSION_REQUEST_TIMEOUT",
          `API NEXOLAB не відповів протягом ${formatTimeout(this.requestTimeoutMs)}. Перевірте стан Telemetry Service та мережевий маршрут до central host.`,
        );
      }
      return this.failure(
        "SESSION_API_UNREACHABLE_OR_ORIGIN_BLOCKED",
        "API NEXOLAB недоступний з цього браузера або поточний browser origin не дозволений CORS. Перевірте адресу central host, порт 8082 і CORS_ALLOWED_ORIGINS.",
      );
    } finally {
      globalThis.clearTimeout(timeoutId);
    }
  }

  private diagnostics(httpStatus: number | null = null): SecuritySessionDiagnostics {
    return {
      apiOrigin: this.apiOrigin,
      browserOrigin: this.browserLocation?.origin ?? null,
      endpointPath: SESSION_ENDPOINT_PATH,
      timeoutMs: this.requestTimeoutMs,
      httpStatus,
    };
  }

  private failure(
    code: SecuritySessionErrorCode,
    message: string,
    httpStatus: number | null = null,
  ): SecuritySessionResult {
    return {
      ok: false,
      error: {
        code,
        message,
        diagnostics: this.diagnostics(httpStatus),
      },
    };
  }

  private isMixedContentRequest(): boolean {
    return this.browserLocation?.protocol === "https:" && new URL(this.apiBaseUrl).protocol === "http:";
  }
}

export function createAuthenticatedFetch(
  fetchImpl: typeof fetch,
  credentials: SecurityCredentialProvider,
): typeof fetch {
  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const snapshot = await credentials();
    const headers = new Headers(init?.headers);
    if (snapshot.accessToken) {
      headers.set("Authorization", `Bearer ${snapshot.accessToken}`);
    }
    if (snapshot.organizationId) {
      headers.set("X-Organization-ID", snapshot.organizationId);
    }
    return fetchImpl(input, {
      ...init,
      credentials: init?.credentials ?? "same-origin",
      headers,
    });
  };
}

let inMemoryCredentials: SecurityCredentialSnapshot = {
  accessToken: null,
  organizationId: null,
};

export function setSecurityCredentials(snapshot: SecurityCredentialSnapshot): void {
  inMemoryCredentials = {
    accessToken: snapshot.accessToken?.trim() || null,
    organizationId: snapshot.organizationId?.trim() || null,
  };
}

export function getSecurityCredentials(): SecurityCredentialSnapshot {
  return { ...inMemoryCredentials };
}

export function hasPermission(
  session: SecuritySession,
  organizationId: string,
  permission: SecurityEffectivePermission,
): boolean {
  const membership = session.memberships.find((item) => item.organizationId === organizationId);
  return membership?.permissions.includes(permission) ?? false;
}

function parseSecuritySession(payload: unknown): SecuritySession | null {
  const root = asRecord(payload);
  const identityRecord = root ? asRecord(root.identity) : null;
  if (!root || root.authenticated !== true || !identityRecord || !Array.isArray(root.memberships)) {
    return null;
  }

  const id = readString(identityRecord.id);
  const provider = readString(identityRecord.provider);
  const subject = readString(identityRecord.subject);
  if (!id || !provider || !subject) return null;

  const memberships: SecurityMembership[] = [];
  for (const item of root.memberships) {
    const record = asRecord(item);
    if (!record || !Array.isArray(record.roles) || !Array.isArray(record.permissions)) {
      return null;
    }
    const organizationId = readString(record.organization_id);
    const organizationSlug = readString(record.organization_slug);
    const organizationName = readString(record.organization_name);
    const roles = record.roles.filter(isSecurityRole);
    const permissions = record.permissions.filter(isSecurityPermission);
    if (
      !organizationId ||
      !organizationSlug ||
      !organizationName ||
      roles.length !== record.roles.length ||
      permissions.length !== record.permissions.length
    ) {
      return null;
    }
    memberships.push({
      organizationId,
      organizationSlug,
      organizationName,
      roles,
      permissions,
    });
  }

  return {
    authenticated: true,
    identity: {
      id,
      provider,
      subject,
      email: readOptionalString(identityRecord.email),
      displayName: readOptionalString(identityRecord.display_name),
    },
    memberships,
  };
}

function isSecurityRole(value: unknown): value is SecurityRole {
  return (
    value === "administrator" ||
    value === "laboratory_manager" ||
    value === "engineer" ||
    value === "laboratory_technician" ||
    value === "operator" ||
    value === "viewer" ||
    value === "auditor"
  );
}

function isSecurityPermission(value: unknown): value is SecurityEffectivePermission {
  return (
    value === "dashboard.read" ||
    value === "live_dashboards.manage" ||
    value === "telemetry.read" ||
    value === "alerts.read" ||
    value === "audit.read" ||
    value === "reports.read" ||
    value === "nodes.read" ||
    value === "reports.generate" ||
    value === "reports.approve" ||
    value === "memberships.manage" ||
    value === "equipment.manage" ||
    value === "nodes.manage" ||
    value === "layout.draft.edit" ||
    value === "layout.publish" ||
    value === "layout.restore" ||
    value === "sessions.manage" ||
    value === "sessions.operate" ||
    value === "alerts.rules.manage" ||
    value === "alerts.acknowledge" ||
    value === "project_versions.manage"
  );
}

function readErrorMessage(payload: unknown): string | null {
  const root = asRecord(payload);
  const detail = root ? asRecord(root.detail) : null;
  return detail ? readString(detail.message) : null;
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

function normalizeBaseUrl(value: string): string {
  const parsed = new URL(value);
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("NEXOLAB API URL must use HTTP or HTTPS.");
  }
  parsed.hash = "";
  parsed.search = "";
  return parsed.toString().replace(/\/$/, "");
}

function normalizeTimeout(value: number | undefined): number {
  if (value === undefined) return DEFAULT_SESSION_TIMEOUT_MS;
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error("Security session request timeout must be a positive finite number.");
  }
  return Math.round(value);
}

function readBrowserLocation(): BrowserLocationSnapshot | null {
  if (typeof window === "undefined") return null;
  return {
    origin: window.location.origin,
    protocol: window.location.protocol,
  };
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function formatTimeout(timeoutMs: number): string {
  return timeoutMs % 1_000 === 0 ? `${timeoutMs / 1_000} с` : `${timeoutMs} мс`;
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
