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
const PEER_SESSION_WAIT_MS = 150;
const REFRESH_LOCK_NAME = "nexolab.local-auth.refresh";
const SESSION_CHANNEL_NAME = "nexolab.local-auth.session";

export type LocalAuthResult = { ok: true } | { ok: false; message: string };

type LocalTokenPayload = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  refresh_expires_in: number;
};

type TokenPairRequestResult =
  | { ok: true; value: LocalTokenPayload }
  | { ok: false; message: string; terminal: boolean };

type BrowserTokenSnapshot = {
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
};

type LocalAuthChannelMessage =
  | { type: "session-request"; requestId: string }
  | ({ type: "session-response"; requestId: string } & BrowserTokenSnapshot)
  | ({ type: "session-update" } & BrowserTokenSnapshot)
  | { type: "session-clear" };

type LockManagerLike = {
  request<T>(name: string, callback: () => Promise<T>): Promise<T>;
};

let channel: BroadcastChannel | null = null;
let refreshPromise: Promise<SecurityCredentialSnapshot> | null = null;
const pendingPeerRequests = new Map<string, (value: boolean) => void>();

export function createLocalCredentialProvider(
  apiBaseUrl: string,
  organizationId: string | null,
): SecurityCredentialProvider {
  const normalizedBaseUrl = normalizeBaseUrl(apiBaseUrl);

  return async (): Promise<SecurityCredentialSnapshot> => {
    if (typeof window === "undefined") {
      return { accessToken: null, organizationId };
    }

    ensureSessionChannel();
    const current = getSecurityCredentials();
    const resolvedOrganizationId = current.organizationId ?? organizationId;

    if (!readBrowserTokenSnapshot()) {
      await requestPeerSession();
    }

    const fresh = currentBrowserCredentialSnapshot(resolvedOrganizationId);
    if (fresh) return fresh;

    if (!window.sessionStorage.getItem(REFRESH_TOKEN_KEY)) {
      const snapshot = { accessToken: null, organizationId: resolvedOrganizationId };
      setSecurityCredentials(snapshot);
      return snapshot;
    }

    const activeRefresh =
      refreshPromise ??
      withRefreshLock(() =>
        refreshCredentialSnapshot(
          normalizedBaseUrl,
          resolvedOrganizationId,
          current.organizationId,
        ),
      );
    refreshPromise = activeRefresh;
    try {
      return await activeRefresh;
    } finally {
      if (refreshPromise === activeRefresh) {
        refreshPromise = null;
      }
    }
  };
}

export async function signInWithLocalPassword(
  apiBaseUrl: string,
  username: string,
  password: string,
): Promise<LocalAuthResult> {
  ensureSessionChannel();
  const normalizedBaseUrl = normalizeBaseUrl(apiBaseUrl);
  const result = await requestTokenPair(normalizedBaseUrl + "/api/v1/auth/local/login", {
    username: username.trim(),
    password,
  });
  if (!result.ok) {
    clearLocalAuthStorage();
    return { ok: false, message: result.message };
  }
  storeTokenPair(result.value, true);
  const current = getSecurityCredentials();
  setSecurityCredentials({
    accessToken: result.value.access_token,
    organizationId: current.organizationId,
  });
  return { ok: true };
}

export async function signOutLocal(apiBaseUrl: string): Promise<void> {
  const refreshToken =
    typeof window === "undefined" ? null : window.sessionStorage.getItem(REFRESH_TOKEN_KEY);
  try {
    if (refreshToken) {
      await fetch(normalizeBaseUrl(apiBaseUrl) + "/api/v1/auth/local/logout", {
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
    broadcastMessage({ type: "session-clear" });
    setSecurityCredentials({ accessToken: null, organizationId: null });
  }
}

export function clearLocalAuthStorage(): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(ACCESS_TOKEN_KEY);
  window.sessionStorage.removeItem(REFRESH_TOKEN_KEY);
  window.sessionStorage.removeItem(ACCESS_EXPIRES_AT_KEY);
}

async function refreshCredentialSnapshot(
  normalizedBaseUrl: string,
  resolvedOrganizationId: string | null,
  organizationAtStart: string | null,
): Promise<SecurityCredentialSnapshot> {
  await requestPeerSession();

  const peerFresh = currentBrowserCredentialSnapshot(resolvedOrganizationId);
  if (peerFresh) return peerFresh;

  const refreshToken = window.sessionStorage.getItem(REFRESH_TOKEN_KEY);
  if (!refreshToken) {
    const snapshot = { accessToken: null, organizationId: resolvedOrganizationId };
    setSecurityCredentials(snapshot);
    return snapshot;
  }

  const refreshed = await requestTokenPair(normalizedBaseUrl + "/api/v1/auth/local/refresh", {
    refresh_token: refreshToken,
  });

  if (window.sessionStorage.getItem(REFRESH_TOKEN_KEY) !== refreshToken) {
    return currentCredentialSnapshot(getSecurityCredentials().organizationId);
  }

  const latestOrganizationId = getSecurityCredentials().organizationId;
  const refreshedOrganizationId =
    latestOrganizationId === organizationAtStart
      ? resolvedOrganizationId
      : latestOrganizationId;

  if (!refreshed.ok) {
    if (refreshed.terminal) {
      clearLocalAuthStorage();
      broadcastMessage({ type: "session-clear" });
      const snapshot = {
        accessToken: null,
        organizationId: refreshedOrganizationId,
      };
      setSecurityCredentials(snapshot);
      return snapshot;
    }
    return currentCredentialSnapshot(refreshedOrganizationId);
  }

  storeTokenPair(refreshed.value, true);
  const snapshot = {
    accessToken: refreshed.value.access_token,
    organizationId: refreshedOrganizationId,
  };
  setSecurityCredentials(snapshot);
  return snapshot;
}

async function withRefreshLock<T>(callback: () => Promise<T>): Promise<T> {
  if (typeof navigator === "undefined") return callback();
  const locks = (navigator as Navigator & { locks?: LockManagerLike }).locks;
  return locks ? locks.request(REFRESH_LOCK_NAME, callback) : callback();
}

async function requestPeerSession(): Promise<boolean> {
  const activeChannel = ensureSessionChannel();
  if (!activeChannel) return false;

  const requestId =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : String(Date.now()) + "-" + Math.random().toString(16).slice(2);

  return new Promise<boolean>((resolve) => {
    const timer = window.setTimeout(() => {
      pendingPeerRequests.delete(requestId);
      resolve(false);
    }, PEER_SESSION_WAIT_MS);
    pendingPeerRequests.set(requestId, (received) => {
      window.clearTimeout(timer);
      pendingPeerRequests.delete(requestId);
      resolve(received);
    });
    activeChannel.postMessage({
      type: "session-request",
      requestId,
    } satisfies LocalAuthChannelMessage);
  });
}

function ensureSessionChannel(): BroadcastChannel | null {
  if (typeof window === "undefined" || typeof BroadcastChannel === "undefined") return null;
  if (channel) return channel;

  channel = new BroadcastChannel(SESSION_CHANNEL_NAME);
  channel.addEventListener("message", (event: MessageEvent<unknown>) => {
    const message = parseChannelMessage(event.data);
    if (!message) return;

    if (message.type === "session-request") {
      const snapshot = readBrowserTokenSnapshot();
      if (snapshot) {
        channel?.postMessage({
          type: "session-response",
          requestId: message.requestId,
          ...snapshot,
        } satisfies LocalAuthChannelMessage);
      }
      return;
    }

    if (message.type === "session-clear") {
      clearLocalAuthStorage();
      setSecurityCredentials({
        accessToken: null,
        organizationId: getSecurityCredentials().organizationId,
      });
      return;
    }

    const accepted = adoptBrowserTokenSnapshot(message);
    if (message.type === "session-response") {
      pendingPeerRequests.get(message.requestId)?.(accepted);
    }
  });
  return channel;
}

function broadcastMessage(message: LocalAuthChannelMessage): void {
  ensureSessionChannel()?.postMessage(message);
}

function storeTokenPair(payload: LocalTokenPayload, broadcast: boolean): void {
  if (typeof window === "undefined") return;
  const snapshot = {
    accessToken: payload.access_token,
    refreshToken: payload.refresh_token,
    expiresAt: Date.now() + payload.expires_in * 1_000,
  };
  writeBrowserTokenSnapshot(snapshot);
  if (broadcast) {
    broadcastMessage({ type: "session-update", ...snapshot });
  }
}

function adoptBrowserTokenSnapshot(snapshot: BrowserTokenSnapshot): boolean {
  const current = readBrowserTokenSnapshot();
  if (current && current.expiresAt > snapshot.expiresAt) return false;
  writeBrowserTokenSnapshot(snapshot);
  const credentials = getSecurityCredentials();
  setSecurityCredentials({
    accessToken: snapshot.accessToken,
    organizationId: credentials.organizationId,
  });
  return true;
}

function writeBrowserTokenSnapshot(snapshot: BrowserTokenSnapshot): void {
  window.sessionStorage.setItem(ACCESS_TOKEN_KEY, snapshot.accessToken);
  window.sessionStorage.setItem(REFRESH_TOKEN_KEY, snapshot.refreshToken);
  window.sessionStorage.setItem(ACCESS_EXPIRES_AT_KEY, String(snapshot.expiresAt));
}

function readBrowserTokenSnapshot(): BrowserTokenSnapshot | null {
  if (typeof window === "undefined") return null;
  const accessToken = window.sessionStorage.getItem(ACCESS_TOKEN_KEY);
  const refreshToken = window.sessionStorage.getItem(REFRESH_TOKEN_KEY);
  const expiresAt = readExpiresAt();
  return accessToken && refreshToken && expiresAt > 0
    ? { accessToken, refreshToken, expiresAt }
    : null;
}

function currentBrowserCredentialSnapshot(
  organizationId: string | null,
): SecurityCredentialSnapshot | null {
  const snapshot = readBrowserTokenSnapshot();
  if (!snapshot || snapshot.expiresAt <= Date.now() + REFRESH_SKEW_MS) return null;
  const credentials = {
    accessToken: snapshot.accessToken,
    organizationId,
  };
  setSecurityCredentials(credentials);
  return credentials;
}

async function requestTokenPair(
  url: string,
  payload: Record<string, string>,
): Promise<TokenPairRequestResult> {
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
        message: readErrorMessage(body) ?? "Локальну сесію оператора не створено.",
        terminal:
          response.status >= 400 &&
          response.status < 500 &&
          response.status !== 408 &&
          response.status !== 429,
      };
    }
    const tokenPair = parseTokenPair(body);
    return tokenPair
      ? { ok: true, value: tokenPair }
      : {
          ok: false,
          message: "Відповідь локального сервера автентифікації недійсна.",
          terminal: true,
        };
  } catch {
    return {
      ok: false,
      message: "Локальний сервер автентифікації NEXOLAB недоступний.",
      terminal: false,
    };
  }
}

function currentCredentialSnapshot(organizationId: string | null): SecurityCredentialSnapshot {
  const snapshot = {
    accessToken: window.sessionStorage.getItem(ACCESS_TOKEN_KEY),
    organizationId,
  };
  setSecurityCredentials(snapshot);
  return snapshot;
}

function readExpiresAt(): number {
  if (typeof window === "undefined") return 0;
  const value = Number(window.sessionStorage.getItem(ACCESS_EXPIRES_AT_KEY));
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function parseChannelMessage(value: unknown): LocalAuthChannelMessage | null {
  const record = asRecord(value);
  const type = record ? readString(record.type) : null;
  if (type === "session-clear") return { type };
  if (type === "session-request") {
    const requestId = readString(record?.requestId);
    return requestId ? { type, requestId } : null;
  }
  if (type !== "session-response" && type !== "session-update") return null;

  const accessToken = readString(record?.accessToken);
  const refreshToken = readString(record?.refreshToken);
  const expiresAt = record?.expiresAt;
  if (
    !accessToken ||
    !refreshToken ||
    typeof expiresAt !== "number" ||
    !Number.isFinite(expiresAt) ||
    expiresAt <= 0
  ) {
    return null;
  }
  if (type === "session-response") {
    const requestId = readString(record?.requestId);
    return requestId ? { type, requestId, accessToken, refreshToken, expiresAt } : null;
  }
  return { type, accessToken, refreshToken, expiresAt };
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
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : null;
}
