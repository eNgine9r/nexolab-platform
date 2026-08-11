import type { SecurityEffectivePermission, SecurityProductRole } from "@/features/security/security-session";

export type LocalUserAdminUser = {
  id: string;
  identityId: string;
  username: string;
  email: string | null;
  displayName: string | null;
  isActive: boolean;
  role: SecurityProductRole | null;
  legacyRoles: string[];
  migrationRequired: boolean;
  grantedPermissions: SecurityEffectivePermission[];
  effectivePermissions: SecurityEffectivePermission[];
  createdAt: string;
  passwordChangedAt: string;
  lastAuthenticatedAt: string;
  lockedUntil: string | null;
};

export type LocalUserRoleOption = {
  value: SecurityProductRole;
  label: string;
  fullAccess: boolean;
  permissionsEditable: boolean;
};

export type LocalUserPermissionOption = {
  value: SecurityEffectivePermission;
  grantable: boolean;
  administratorOnly: boolean;
};

export type LocalUserCreateInput = {
  username: string;
  password: string;
  role: SecurityProductRole;
  permissions: SecurityEffectivePermission[];
  email?: string | null;
  displayName?: string | null;
  reason?: string | null;
};

export type LocalUserUpdateInput = {
  role?: SecurityProductRole;
  isActive?: boolean;
  reason?: string | null;
};

export class LocalUserAdminApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "LocalUserAdminApiError";
  }
}

export class LocalUserAdminClient {
  private readonly apiBaseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: { apiBaseUrl: string; fetchImpl: typeof fetch }) {
    this.apiBaseUrl = normalizeBaseUrl(options.apiBaseUrl);
    this.fetchImpl = options.fetchImpl;
  }

  async listUsers(): Promise<LocalUserAdminUser[]> {
    const payload = await this.request("/api/v1/admin/users");
    const record = asRecord(payload);
    if (!record || !Array.isArray(record.items)) throw invalidResponse();
    return record.items.map(parseUser);
  }

  async roles(): Promise<LocalUserRoleOption[]> {
    const payload = await this.request("/api/v1/admin/roles");
    const record = asRecord(payload);
    if (!record || !Array.isArray(record.items)) throw invalidResponse();
    return record.items.map((item) => {
      const row = asRecord(item);
      const value = row ? readProductRole(row.value) : null;
      const label = row ? readString(row.label) : null;
      if (!row || !value || !label) throw invalidResponse();
      return {
        value,
        label,
        fullAccess: row.full_access === true,
        permissionsEditable: row.permissions_editable === true,
      };
    });
  }

  async permissions(): Promise<LocalUserPermissionOption[]> {
    const payload = await this.request("/api/v1/admin/permissions");
    const record = asRecord(payload);
    if (!record || !Array.isArray(record.items)) throw invalidResponse();
    return record.items.map((item) => {
      const row = asRecord(item);
      const value = row ? readPermission(row.value) : null;
      if (!row || !value) throw invalidResponse();
      return {
        value,
        grantable: row.grantable === true,
        administratorOnly: row.administrator_only === true,
      };
    });
  }

  async createUser(input: LocalUserCreateInput): Promise<LocalUserAdminUser> {
    const payload = await this.request("/api/v1/admin/users", {
      method: "POST",
      body: JSON.stringify({
        username: input.username,
        password: input.password,
        role: input.role,
        permissions: input.permissions,
        email: input.email ?? null,
        display_name: input.displayName ?? null,
        reason: input.reason ?? null,
      }),
    });
    return parseUser(payload);
  }

  async updateUser(userId: string, input: LocalUserUpdateInput): Promise<LocalUserAdminUser> {
    const payload = await this.request(`/api/v1/admin/users/${encodeURIComponent(userId)}`, {
      method: "PATCH",
      body: JSON.stringify({
        role: input.role,
        is_active: input.isActive,
        reason: input.reason ?? null,
      }),
    });
    return parseUser(payload);
  }

  async setPermissions(
    userId: string,
    permissions: SecurityEffectivePermission[],
    reason?: string | null,
  ): Promise<LocalUserAdminUser> {
    const payload = await this.request(`/api/v1/admin/users/${encodeURIComponent(userId)}/permissions`, {
      method: "PUT",
      body: JSON.stringify({ permissions, reason: reason ?? null }),
    });
    return parseUser(payload);
  }

  async resetPassword(userId: string, password: string, reason?: string | null): Promise<void> {
    await this.request(`/api/v1/admin/users/${encodeURIComponent(userId)}/reset-password`, {
      method: "POST",
      body: JSON.stringify({ password, reason: reason ?? null }),
    });
  }

  async revokeSessions(userId: string, reason?: string | null): Promise<number> {
    const payload = await this.request(`/api/v1/admin/users/${encodeURIComponent(userId)}/revoke-sessions`, {
      method: "POST",
      body: JSON.stringify({ reason: reason ?? null }),
    });
    const record = asRecord(payload);
    const count = record?.revoked_session_count;
    if (typeof count !== "number") throw invalidResponse();
    return count;
  }

  private async request(path: string, init?: RequestInit): Promise<unknown> {
    const headers = new Headers(init?.headers);
    headers.set("Accept", "application/json");
    if (init?.body !== undefined) headers.set("Content-Type", "application/json");
    const response = await this.fetchImpl(`${this.apiBaseUrl}${path}`, {
      ...init,
      cache: "no-store",
      headers,
    });
    const payload = await readJson(response);
    if (!response.ok) {
      const detail = asRecord(asRecord(payload)?.detail);
      throw new LocalUserAdminApiError(
        response.status,
        readString(detail?.code) ?? "local_user_admin_api_error",
        readString(detail?.message) ?? `User administration API returned HTTP ${response.status}.`,
      );
    }
    return payload;
  }
}

function parseUser(value: unknown): LocalUserAdminUser {
  const row = asRecord(value);
  if (!row) throw invalidResponse();
  const id = readString(row.id);
  const identityId = readString(row.identity_id);
  const username = readString(row.username);
  const role = row.role === null ? null : readProductRole(row.role);
  const legacyRoles = readStringArray(row.legacy_roles);
  const grantedPermissions = readPermissionArray(row.granted_permissions);
  const effectivePermissions = readPermissionArray(row.effective_permissions);
  const createdAt = readString(row.created_at);
  const passwordChangedAt = readString(row.password_changed_at);
  const lastAuthenticatedAt = readString(row.last_authenticated_at);
  if (
    !id ||
    !identityId ||
    !username ||
    (row.is_active !== true && row.is_active !== false) ||
    !legacyRoles ||
    !grantedPermissions ||
    !effectivePermissions ||
    !createdAt ||
    !passwordChangedAt ||
    !lastAuthenticatedAt ||
    (row.role !== null && !role)
  ) {
    throw invalidResponse();
  }
  return {
    id,
    identityId,
    username,
    email: readOptionalString(row.email),
    displayName: readOptionalString(row.display_name),
    isActive: row.is_active,
    role,
    legacyRoles,
    migrationRequired: row.migration_required === true,
    grantedPermissions,
    effectivePermissions,
    createdAt,
    passwordChangedAt,
    lastAuthenticatedAt,
    lockedUntil: readOptionalString(row.locked_until),
  };
}

function readProductRole(value: unknown): SecurityProductRole | null {
  return value === "administrator" ||
    value === "laboratory_manager" ||
    value === "engineer" ||
    value === "laboratory_technician"
    ? value
    : null;
}

function readPermission(value: unknown): SecurityEffectivePermission | null {
  return typeof value === "string" ? (value as SecurityEffectivePermission) : null;
}

function readPermissionArray(value: unknown): SecurityEffectivePermission[] | null {
  if (!Array.isArray(value)) return null;
  const permissions = value.map(readPermission);
  return permissions.some((item) => item === null) ? null : (permissions as SecurityEffectivePermission[]);
}

function readStringArray(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) return null;
  return value as string[];
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

function invalidResponse(): LocalUserAdminApiError {
  return new LocalUserAdminApiError(
    502,
    "invalid_local_user_admin_response",
    "Відповідь API керування користувачами не відповідає контракту.",
  );
}
