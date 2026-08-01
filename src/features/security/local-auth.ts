import {
  getSecurityCredentials,
  setSecurityCredentials,
  type SecurityCredentialProvider,
  type SecurityCredentialSnapshot,
} from "./security-session";

const ACCESS_TOKEN_KEY = "nexolab.local-auth.access-token";
const REFRESH_TOKEN_KEY = "nexolab.local-auth.refresh-token";
const ACCESS_EXPIRES_AT_KEY = "nexolab.local-auth.access-expires-at";
const REFRESH_SKEW_MS = 30_000;

export type LocalAuthResult = { ok: true } | { ok: false; message: string };

type LocalTokenPayload = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  refresh_expires_in: number;
};

export function createLocalCredentialProvider(
  apiBaseUrl: string,
  organizationId: string | null,
): SecurityCredentialProvider {
  const normalizedBaseUrl = normalizeBaseUrl(apiBaseUrl);
  return async (): Promise<SecurityCredentialSnapshot> => {
    if (typeof window === "undefined") {
      return { accessToken: null, organizationId };
    }
    const current = getSecurityCredentials();
    const resolvedOrganizationId = current.organizationId ?? organizationId;
    const accessToken = window.sessionStorage.getItem(ACCESS_TOKEN_KEY);
    const expiresAt = readExpiresAt();
    if (accessToken && expiresAt > Date.now() + REFRESH_SKEW_MS) {
      const snapshot = { accessToken, organizationId: resolvedOrganizationId };
      setSecurityCredentials(snapshot);
      return snapshot;
    }

    const refreshToken = window.sessionStorage.getItem(REFRESH_TOKEN_KEY);
    if (!refreshToken) {
      clearLocalAuthStorage();
      const snapshot = {
        accessToken: null,
        organizationId: resolvedOrganizationId,
      };
      setSecurityCredentials(snapshot);
      return snapshot;
    }

    const refreshed = await requestTokenPair(
      `${normalizedBaseUrl}/api/v1/auth/local/refresh`,
      {
        refresh_token: refreshToken,
      },
    );
    if (!refreshed.ok) {
      clearLocalAuthStorage();
      const snapshot = {
        accessToken: null,
        organizationId: resolvedOrganizationId,
      };
      setSecurityCredentials(snapshot);
      return snapshot;
    }
    storeTokenPair(refreshed.value);
    const snapshot = {
      accessToken: refreshed.value.access_token,
      organizationId: resolvedOrganizationId,
    };
    setSecurityCredentials(snapshot);
    return snapshot;
  };
}

export async function signInWithLocalPassword(
  apiBaseUrl: string,
  username: string,
  password: string,
): Promise<LocalAuthResult> {
  const normalizedBaseUrl = normalizeBaseUrl(apiBaseUrl);
  const result = await requestTokenPair(
    `${normalizedBaseUrl}/api/v1/auth/local/login`,
    {
      username: username.trim(),
      password,
    },
  );
  if (!result.ok) {
    clearLocalAuthStorage();
    return { ok: false, message: result.message };
  }
  storeTokenPair(result.value);
  const current = getSecurityCredentials();
  setSecurityCredentials({
    accessToken: result.value.access_token,
    organizationId: current.organizationId,
  });
  return { ok: true };
}

export async function signOutLocal(apiBaseUrl: string): Promise<void> {
  const refreshToken =
    typeof window === "undefined"
      ? null
      : window.sessionStorage.getItem(REFRESH_TOKEN_KEY);
  try {
    if (refreshToken) {
      await fetch(`${normalizeBaseUrl(apiBaseUrl)}/api/v1/auth/local/logout`, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
    }
  } finally {
    clearLocalAuthStorage();
    setSecurityCredentials({ accessToken: null, organizationId: null });
  }
}

export function clearLocalAuthStorage(): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(ACCESS_TOKEN_KEY);
  window.sessionStorage.removeItem(REFRESH_TOKEN_KEY);
  window.sessionStorage.removeItem(ACCESS_EXPIRES_AT_KEY);
}

async function requestTokenPair(
  url: string,
  payload: Record<string, string>,
): Promise<
  { ok: true; value: LocalTokenPayload } | { ok: false; message: string }
> {
  try {
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    const body = await readJson(response);
    if (!response.ok) {
      return {
        ok: false,
        message:
          readErrorMessage(body) ??
          "Локальну сесію оператора не створено.",
      };
    }
    const tokenPair = parseTokenPair(body);
    return tokenPair
      ? { ok: true, value: tokenPair }
      : {
          ok: false,
          message:
            "Відповідь локального сервера автентифікації недійсна.",
        };
  } catch {
    return {
      ok: false,
      message: "Локальний сервер автентифікації NEXOLAB недоступний.",
    };
  }
}

function storeTokenPair(payload: LocalTokenPayload): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(ACCESS_TOKEN_KEY, payload.access_token);
  window.sessionStorage.setItem(REFRESH_TOKEN_KEY, payload.refresh_token);
  window.sessionStorage.setItem(
    ACCESS_EXPIRES_AT_KEY,
    String(Date.now() + payload.expires_in * 1_000),
  );
}

function readExpiresAt(): number {
  if (typeof window === "undefined") return 0;
  const value = Number(window.sessionStorage.getItem(ACCESS_EXPIRES_AT_KEY));
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function parseTokenPair(value: unknown): LocalTokenPayload | null {
  const record = asRecord(value);
  if (!record) return null;
  const accessToken = readString(record.access_token);
  const refreshToken = readString(record.refresh_token);
  const expiresIn = readPositiveInteger(record.expires_in);
  const refreshExpiresIn = readPositiveInteger(record.refresh_expires_in);
  if (!accessToken || !refreshToken || !expiresIn || !refreshExpiresIn) {
    return null;
  }
  return {
    access_token: accessToken,
    refresh_token: refreshToken,
    expires_in: expiresIn,
    refresh_expires_in: refreshExpiresIn,
  };
}

function readErrorMessage(value: unknown): string | null {
  const record = asRecord(value);
  const detail = record ? asRecord(record.detail) : null;
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

function readPositiveInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value > 0
    ? value
    : null;
}
