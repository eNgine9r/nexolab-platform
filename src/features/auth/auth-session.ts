export type AuthRole = "admin" | "operator" | "viewer";

export type AuthPermission =
  | "telemetry.read"
  | "sessions.read"
  | "sessions.write"
  | "layouts.read"
  | "layouts.write"
  | "layouts.publish"
  | "audit.read";

export type AuthSession = {
  subject: string;
  organizationId: string;
  role: AuthRole;
  permissions: readonly AuthPermission[];
  email: string | null;
  displayName: string | null;
  provider: string;
};

export type AuthSessionErrorCode =
  | "AUTHENTICATION_REQUIRED"
  | "PERMISSION_DENIED"
  | "AUTH_REQUEST_FAILED"
  | "INVALID_AUTH_RESPONSE";

export type AuthSessionError = {
  code: AuthSessionErrorCode;
  message: string;
  status: number | null;
  permission: AuthPermission | null;
};

export type AuthSessionResult =
  | { ok: true; value: AuthSession }
  | { ok: false; error: AuthSessionError };

export const AUTH_TOKEN_STORAGE_KEY = "nexolab.access_token";

const roles = new Set<AuthRole>(["admin", "operator", "viewer"]);
const permissions = new Set<AuthPermission>([
  "telemetry.read",
  "sessions.read",
  "sessions.write",
  "layouts.read",
  "layouts.write",
  "layouts.publish",
  "audit.read",
]);

export function readBrowserAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  const token = window.sessionStorage.getItem(AUTH_TOKEN_STORAGE_KEY)?.trim();
  return token || null;
}

export function writeBrowserAccessToken(token: string): void {
  if (typeof window === "undefined") return;
  const normalized = token.trim();
  if (!normalized) {
    window.sessionStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
    return;
  }
  window.sessionStorage.setItem(AUTH_TOKEN_STORAGE_KEY, normalized);
}

export function clearBrowserAccessToken(): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
}

export function bearerHeaders(token: string | null): Headers {
  const headers = new Headers();
  if (token?.trim()) headers.set("Authorization", `Bearer ${token.trim()}`);
  return headers;
}

export function authenticatedWebSocketProtocols(token: string | null): string[] | undefined {
  const normalized = token?.trim();
  return normalized ? ["nexolab.v1", `nexolab.jwt.${normalized}`] : undefined;
}

export function hasPermission(
  session: AuthSession | null,
  permission: AuthPermission,
): boolean {
  return Boolean(session?.permissions.includes(permission));
}

export async function fetchAuthSession(
  apiBaseUrl: string,
  token: string | null,
  fetchImpl: typeof fetch = fetch.bind(globalThis),
): Promise<AuthSessionResult> {
  if (!token?.trim()) {
    return {
      ok: false,
      error: {
        code: "AUTHENTICATION_REQUIRED",
        message: "Для live-режиму потрібна авторизована операторська сесія.",
        status: 401,
        permission: null,
      },
    };
  }

  const headers = bearerHeaders(token);
  headers.set("Accept", "application/json");

  let response: Response;
  try {
    response = await fetchImpl(`${normalizeBaseUrl(apiBaseUrl)}/api/v1/auth/session`, {
      method: "GET",
      headers,
    });
  } catch {
    return {
      ok: false,
      error: {
        code: "AUTH_REQUEST_FAILED",
        message: "Не вдалося перевірити операторську сесію.",
        status: null,
        permission: null,
      },
    };
  }

  const payload = await readJson(response);
  if (!response.ok) return mapAuthHttpError(response.status, payload);

  const session = parseAuthSession(payload);
  return session
    ? { ok: true, value: session }
    : {
        ok: false,
        error: {
          code: "INVALID_AUTH_RESPONSE",
          message: "Сервер повернув некоректний контракт операторської сесії.",
          status: response.status,
          permission: null,
        },
      };
}

export function demoAuthSession(): AuthSession {
  return {
    subject: "development-admin",
    organizationId: "nexolab-default",
    role: "admin",
    permissions: [...permissions],
    email: "development-admin@nexolab.local",
    displayName: "Demo administrator",
    provider: "development",
  };
}

function parseAuthSession(payload: unknown): AuthSession | null {
  const record = asRecord(payload);
  if (!record) return null;

  const subject = readString(record.subject);
  const organizationId = readString(record.organization_id);
  const role = readString(record.role);
  const provider = readString(record.provider);
  if (!subject || !organizationId || !role || !roles.has(role as AuthRole) || !provider) {
    return null;
  }

  if (!Array.isArray(record.permissions)) return null;
  const parsedPermissions: AuthPermission[] = [];
  for (const item of record.permissions) {
    if (typeof item !== "string" || !permissions.has(item as AuthPermission)) return null;
    parsedPermissions.push(item as AuthPermission);
  }

  return {
    subject,
    organizationId,
    role: role as AuthRole,
    permissions: [...new Set(parsedPermissions)].sort(),
    email: readNullableString(record.email),
    displayName: readNullableString(record.display_name),
    provider,
  };
}

function mapAuthHttpError(status: number, payload: unknown): AuthSessionResult {
  const detail = asRecord(asRecord(payload)?.detail);
  const message = readString(detail?.message);
  const permission = readString(detail?.permission);
  if (status === 401) {
    return {
      ok: false,
      error: {
        code: "AUTHENTICATION_REQUIRED",
        message: message ?? "Операторська сесія відсутня або завершилась.",
        status,
        permission: null,
      },
    };
  }
  if (status === 403) {
    return {
      ok: false,
      error: {
        code: "PERMISSION_DENIED",
        message: message ?? "Оператор не має дозволу на цю дію.",
        status,
        permission: permissions.has(permission as AuthPermission)
          ? (permission as AuthPermission)
          : null,
      },
    };
  }
  return {
    ok: false,
    error: {
      code: "AUTH_REQUEST_FAILED",
      message: message ?? `Auth API повернув HTTP ${status}.`,
      status,
      permission: null,
    },
  };
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
  return new URL(value).toString().replace(/\/$/, "");
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readNullableString(value: unknown): string | null {
  return value === null || value === undefined ? null : readString(value);
}
