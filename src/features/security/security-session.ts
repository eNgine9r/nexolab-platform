export type SecurityRole =
  "administrator" | "laboratory_manager" | "engineer" | "operator" | "viewer" | "auditor";

export type SecurityPermission =
  | "dashboard.read"
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
  | "alerts.acknowledge";

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
  permissions: SecurityPermission[];
};

export type SecuritySession = {
  authenticated: true;
  identity: SecurityIdentity;
  memberships: SecurityMembership[];
};

export type SecuritySessionResult =
  | { ok: true; value: SecuritySession }
  | {
      ok: false;
      error: {
        code: "AUTHENTICATION_REQUIRED" | "ACCESS_DENIED" | "INVALID_RESPONSE" | "REQUEST_FAILED";
        message: string;
      };
    };

export type SecurityCredentialSnapshot = {
  accessToken: string | null;
  organizationId: string | null;
};

export type SecurityCredentialProvider = () =>
  SecurityCredentialSnapshot | Promise<SecurityCredentialSnapshot>;

export type HttpSecuritySessionClientOptions = {
  apiBaseUrl: string;
  fetchImpl?: typeof fetch;
};

export class HttpSecuritySessionClient {
  private readonly apiBaseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: HttpSecuritySessionClientOptions) {
    this.apiBaseUrl = normalizeBaseUrl(options.apiBaseUrl);
    this.fetchImpl = options.fetchImpl ?? fetch.bind(globalThis);
  }

  async getSession(): Promise<SecuritySessionResult> {
    try {
      const response = await this.fetchImpl(`${this.apiBaseUrl}/api/v1/auth/session`, {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const payload = await readJson(response);
      if (!response.ok) {
        const message = readErrorMessage(payload);
        return {
          ok: false,
          error: {
            code: response.status === 401 ? "AUTHENTICATION_REQUIRED" : "ACCESS_DENIED",
            message:
              message ??
              (response.status === 401
                ? "Потрібна автентифікація оператора."
                : "Поточний користувач не має доступу до вибраної організації."),
          },
        };
      }

      const session = parseSecuritySession(payload);
      return session
        ? { ok: true, value: session }
        : {
            ok: false,
            error: {
              code: "INVALID_RESPONSE",
              message: "Відповідь сервера автентифікації не відповідає контракту.",
            },
          };
    } catch {
      return {
        ok: false,
        error: {
          code: "REQUEST_FAILED",
          message: "Не вдалося отримати захищену сесію NEXOLAB.",
        },
      };
    }
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
  permission: SecurityPermission,
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
    value === "operator" ||
    value === "viewer" ||
    value === "auditor"
  );
}

function isSecurityPermission(value: unknown): value is SecurityPermission {
  return (
    value === "dashboard.read" ||
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
    value === "alerts.acknowledge"
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
