import {
  getSecurityCredentials,
  notifySecurityCredentialsInvalidated,
  notifySecurityCredentialsUpdated,
  setSecurityCredentials,
  type SecurityCredentialProvider,
  type SecurityCredentialSnapshot,
} from "./security-session";

const ACCESS_TOKEN_KEY = "nexolab.local-auth.access-token";
const REFRESH_TOKEN_KEY = "nexolab.local-auth.refresh-token";
const ACCESS_EXPIRES_AT_KEY = "nexolab.local-auth.access-expires-at";
const SUBJECT_KEY = "nexolab.local-auth.subject";
const SESSION_ID_KEY = "nexolab.local-auth.session-id";
const LOGGED_OUT_SESSION_IDS_KEY = "nexolab.local-auth.logged-out-session-ids";
const PEER_ADOPTION_BLOCKED_KEY = "nexolab.local-auth.peer-adoption-blocked";
const REFRESH_SKEW_MS = 30_000;
const PEER_SESSION_WAIT_MS = 150;
const PEER_SESSION_LATE_WAIT_MS = 500;
const AUTH_REQUEST_TIMEOUT_MS = 10_000;
const REFRESH_LOCK_NAME = "nexolab.local-auth.refresh";
const SESSION_CHANNEL_NAME = "nexolab.local-auth.session";

export type LocalAuthResult = { ok: true } | { ok: false; message: string };

type LocalTokenPayload = {
  access_token: string;
  refresh_token: string;
  subject: string;
  session_id: string;
  expires_in: number;
  refresh_expires_in: number;
};

type TokenPairRequestResult =
  { ok: true; value: LocalTokenPayload } | { ok: false; message: string; terminal: boolean };

type BrowserTokenSnapshot = {
  accessToken: string;
  refreshToken: string;
  subject: string;
  sessionId: string;
  expiresAt: number;
};

type LocalAuthChannelMessage =
  | { type: "session-request"; requestId: string }
  | ({ type: "session-response"; requestId: string } & BrowserTokenSnapshot)
  | ({ type: "session-update" } & BrowserTokenSnapshot)
  | { type: "session-clear"; refreshToken?: string; sessionId?: string };

type LockManagerLike = {
  request<T>(name: string, callback: () => Promise<T>): Promise<T>;
};

type PendingPeerRequest = {
  resolve: (value: boolean) => void;
  candidate: BrowserTokenSnapshot | null;
  ambiguous: boolean;
  settled: boolean;
  timer: number;
};

let channel: BroadcastChannel | null = null;
let refreshPromise: Promise<SecurityCredentialSnapshot> | null = null;
const pendingPeerRequests = new Map<string, PendingPeerRequest>();

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

    const peerOrganizationId = reconcileOrganization(resolvedOrganizationId, current.organizationId);
    const fresh = currentBrowserCredentialSnapshot(peerOrganizationId);
    if (fresh) return fresh;

    if (!window.sessionStorage.getItem(REFRESH_TOKEN_KEY)) {
      const snapshot = {
        accessToken: null,
        organizationId: peerOrganizationId,
      };
      setSecurityCredentials(snapshot);
      return snapshot;
    }

    const activeRefresh =
      refreshPromise ??
      withRefreshLock(() =>
        refreshCredentialSnapshot(
          normalizedBaseUrl,
          peerOrganizationId,
          getSecurityCredentials().organizationId,
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
  allowPeerAdoption();
  storeTokenPair(result.value, true);
  const current = getSecurityCredentials();
  setSecurityCredentials({
    accessToken: result.value.access_token,
    organizationId: current.organizationId,
  });
  return { ok: true };
}

export async function signOutLocal(apiBaseUrl: string): Promise<void> {
  if (typeof window === "undefined") return;

  let logoutSessionId = readBrowserTokenSnapshot()?.sessionId ?? null;
  try {
    if (refreshPromise) {
      await refreshPromise.catch(() => undefined);
    }
    await withRefreshLock(async () => {
      if (ensureSessionChannel()) {
        await requestPeerSession();
      }
      const current = readBrowserTokenSnapshot();
      logoutSessionId ??= current?.sessionId ?? null;
      const refreshToken = current?.refreshToken ?? null;
      if (refreshToken) {
        await requestLogout(normalizeBaseUrl(apiBaseUrl), refreshToken);
      }
    });
  } finally {
    if (logoutSessionId) {
      markLoggedOutSession(logoutSessionId);
    }
    blockPeerAdoption();
    clearLocalAuthStorage();
    broadcastMessage({
      type: "session-clear",
      ...(logoutSessionId ? { sessionId: logoutSessionId } : {}),
    });
    setSecurityCredentials({ accessToken: null, organizationId: null });
  }
}

export function clearLocalAuthStorage(): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(ACCESS_TOKEN_KEY);
  window.sessionStorage.removeItem(REFRESH_TOKEN_KEY);
  window.sessionStorage.removeItem(ACCESS_EXPIRES_AT_KEY);
  window.sessionStorage.removeItem(SUBJECT_KEY);
  window.sessionStorage.removeItem(SESSION_ID_KEY);
}

async function refreshCredentialSnapshot(
  normalizedBaseUrl: string,
  resolvedOrganizationId: string | null,
  organizationAtStart: string | null,
): Promise<SecurityCredentialSnapshot> {
  if (ensureSessionChannel()) {
    await requestPeerSession();
  }

  let effectiveOrganizationId = reconcileOrganization(resolvedOrganizationId, organizationAtStart);
  const peerFresh = currentBrowserCredentialSnapshot(effectiveOrganizationId);
  if (peerFresh) return peerFresh;

  const refreshToken = window.sessionStorage.getItem(REFRESH_TOKEN_KEY);
  if (!refreshToken) {
    const snapshot = {
      accessToken: null,
      organizationId: effectiveOrganizationId,
    };
    setSecurityCredentials(snapshot);
    return snapshot;
  }

  let refreshed = await requestTokenPair(normalizedBaseUrl + "/api/v1/auth/local/refresh", {
    refresh_token: refreshToken,
  });
  if (!refreshed.ok && !refreshed.terminal) {
    refreshed = await requestTokenPair(normalizedBaseUrl + "/api/v1/auth/local/refresh", {
      refresh_token: refreshToken,
    });
  }

  if (window.sessionStorage.getItem(REFRESH_TOKEN_KEY) !== refreshToken) {
    return currentCredentialSnapshot(getSecurityCredentials().organizationId);
  }

  effectiveOrganizationId = reconcileOrganization(effectiveOrganizationId, organizationAtStart);

  if (!refreshed.ok) {
    if (refreshed.terminal) {
      if (ensureSessionChannel()) {
        await requestPeerSession();
      }
      if (window.sessionStorage.getItem(REFRESH_TOKEN_KEY) !== refreshToken) {
        return currentCredentialSnapshot(getSecurityCredentials().organizationId);
      }
      const rejectedSnapshot = readBrowserTokenSnapshot();
      if (rejectedSnapshot?.sessionId) {
        markLoggedOutSession(rejectedSnapshot.sessionId);
      }
      blockPeerAdoption();
      clearLocalAuthStorage();
      broadcastMessage({
        type: "session-clear",
        refreshToken,
        ...(rejectedSnapshot?.sessionId ? { sessionId: rejectedSnapshot.sessionId } : {}),
      });
      const snapshot = {
        accessToken: null,
        organizationId: effectiveOrganizationId,
      };
      setSecurityCredentials(snapshot);
      return snapshot;
    }
    return currentCredentialSnapshot(effectiveOrganizationId);
  }

  storeTokenPair(refreshed.value, true);
  const snapshot = {
    accessToken: refreshed.value.access_token,
    organizationId: effectiveOrganizationId,
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
  if (isPeerAdoptionBlocked()) return false;
  const activeChannel = ensureSessionChannel();
  if (!activeChannel) return false;

  const requestId =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : String(Date.now()) + "-" + Math.random().toString(16).slice(2);

  return new Promise<boolean>((resolve) => {
    const pending: PendingPeerRequest = {
      resolve,
      candidate: null,
      ambiguous: false,
      settled: false,
      timer: 0,
    };
    pending.timer = window.setTimeout(() => {
      if (pending.candidate || pending.ambiguous) {
        finalizePendingPeerRequest(requestId);
        return;
      }

      pending.settled = true;
      resolve(false);
      pending.timer = window.setTimeout(() => {
        finalizePendingPeerRequest(requestId);
      }, PEER_SESSION_LATE_WAIT_MS);
    }, PEER_SESSION_WAIT_MS);
    pendingPeerRequests.set(requestId, pending);
    activeChannel.postMessage({
      type: "session-request",
      requestId,
    } satisfies LocalAuthChannelMessage);
  });
}

function ensureSessionChannel(): BroadcastChannel | null {
  if (typeof window === "undefined" || typeof BroadcastChannel === "undefined") {
    return null;
  }
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
      const current = readBrowserTokenSnapshot();
      if (message.sessionId) {
        markLoggedOutSession(message.sessionId);
      }
      if (!current) return;
      if (message.sessionId && current.sessionId !== message.sessionId) return;
      if (message.refreshToken && current.refreshToken !== message.refreshToken) return;
      markLoggedOutSession(current.sessionId);
      blockPeerAdoption();
      clearLocalAuthStorage();
      setSecurityCredentials({
        accessToken: null,
        organizationId: getSecurityCredentials().organizationId,
      });
      notifySecurityCredentialsInvalidated();
      return;
    }

    if (message.type === "session-response") {
      const pending = pendingPeerRequests.get(message.requestId);
      if (pending) {
        recordPendingPeerResponse(pending, message);
      }
      return;
    }

    const current = readBrowserTokenSnapshot();
    if (!current) return;
    const accepted = adoptBrowserTokenSnapshot(message);
    if (accepted && browserTokenSnapshotChanged(current, message)) {
      notifySecurityCredentialsUpdated();
    }
  });
  return channel;
}

function recordPendingPeerResponse(pending: PendingPeerRequest, snapshot: BrowserTokenSnapshot): void {
  const current = readBrowserTokenSnapshot();
  if (current && (current.subject !== snapshot.subject || current.sessionId !== snapshot.sessionId)) {
    return;
  }

  if (pending.ambiguous) return;
  const candidate = pending.candidate;
  if (!candidate) {
    pending.candidate = snapshot;
    return;
  }
  if (candidate.subject !== snapshot.subject || candidate.sessionId !== snapshot.sessionId) {
    pending.candidate = null;
    pending.ambiguous = true;
    return;
  }
  if (snapshot.expiresAt > candidate.expiresAt) {
    pending.candidate = snapshot;
  }
}

function finalizePendingPeerRequest(requestId: string): boolean {
  const pending = pendingPeerRequests.get(requestId);
  if (!pending) return false;

  window.clearTimeout(pending.timer);
  pendingPeerRequests.delete(requestId);

  if (pending.ambiguous || !pending.candidate) {
    if (!pending.settled) pending.resolve(false);
    return false;
  }

  const previous = readBrowserTokenSnapshot();
  const accepted = adoptBrowserTokenSnapshot(pending.candidate);
  if (!pending.settled) {
    pending.resolve(accepted);
  } else if (accepted && browserTokenSnapshotChanged(previous, pending.candidate)) {
    notifySecurityCredentialsUpdated();
  }
  return accepted;
}

function browserTokenSnapshotChanged(
  previous: BrowserTokenSnapshot | null,
  next: BrowserTokenSnapshot,
): boolean {
  return (
    !previous ||
    previous.accessToken !== next.accessToken ||
    previous.refreshToken !== next.refreshToken ||
    previous.subject !== next.subject ||
    previous.sessionId !== next.sessionId ||
    previous.expiresAt !== next.expiresAt
  );
}

function broadcastMessage(message: LocalAuthChannelMessage): void {
  ensureSessionChannel()?.postMessage(message);
}

function storeTokenPair(payload: LocalTokenPayload, broadcast: boolean): void {
  if (typeof window === "undefined") return;
  const snapshot = {
    accessToken: payload.access_token,
    refreshToken: payload.refresh_token,
    subject: payload.subject,
    sessionId: payload.session_id,
    expiresAt: Date.now() + payload.expires_in * 1_000,
  };
  writeBrowserTokenSnapshot(snapshot);
  if (broadcast) {
    broadcastMessage({ type: "session-update", ...snapshot });
  }
}

function adoptBrowserTokenSnapshot(snapshot: BrowserTokenSnapshot): boolean {
  if (isPeerAdoptionBlocked() || isLoggedOutSession(snapshot.sessionId)) return false;
  const current = readBrowserTokenSnapshot();
  if (current && (current.subject !== snapshot.subject || current.sessionId !== snapshot.sessionId)) {
    return false;
  }
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
  window.sessionStorage.setItem(SUBJECT_KEY, snapshot.subject);
  window.sessionStorage.setItem(SESSION_ID_KEY, snapshot.sessionId);
}

function readBrowserTokenSnapshot(): BrowserTokenSnapshot | null {
  if (typeof window === "undefined") return null;
  const accessToken = window.sessionStorage.getItem(ACCESS_TOKEN_KEY);
  const refreshToken = window.sessionStorage.getItem(REFRESH_TOKEN_KEY);
  const expiresAt = readExpiresAt();
  if (!accessToken || !refreshToken || expiresAt <= 0) return null;

  const accessIdentity = readAccessTokenIdentity(accessToken);
  const subject = window.sessionStorage.getItem(SUBJECT_KEY) ?? accessIdentity?.subject ?? null;
  const sessionId = window.sessionStorage.getItem(SESSION_ID_KEY) ?? accessIdentity?.sessionId ?? null;
  if (!subject || !sessionId) return null;
  if (isLoggedOutSession(sessionId)) {
    clearLocalAuthStorage();
    return null;
  }
  window.sessionStorage.setItem(SUBJECT_KEY, subject);
  window.sessionStorage.setItem(SESSION_ID_KEY, sessionId);
  return { accessToken, refreshToken, subject, sessionId, expiresAt };
}

function currentBrowserCredentialSnapshot(organizationId: string | null): SecurityCredentialSnapshot | null {
  const snapshot = readBrowserTokenSnapshot();
  if (!snapshot || snapshot.expiresAt <= Date.now() + REFRESH_SKEW_MS) {
    return null;
  }
  const credentials = {
    accessToken: snapshot.accessToken,
    organizationId,
  };
  setSecurityCredentials(credentials);
  return credentials;
}

function reconcileOrganization(
  fallbackOrganizationId: string | null,
  organizationAtStart: string | null,
): string | null {
  const latestOrganizationId = getSecurityCredentials().organizationId;
  return latestOrganizationId === organizationAtStart ? fallbackOrganizationId : latestOrganizationId;
}

async function requestTokenPair(
  url: string,
  payload: Record<string, string>,
): Promise<TokenPairRequestResult> {
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), AUTH_REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
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
  } finally {
    globalThis.clearTimeout(timeout);
  }
}

async function requestLogout(normalizedBaseUrl: string, refreshToken: string): Promise<void> {
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), AUTH_REQUEST_TIMEOUT_MS);
  try {
    await fetch(normalizedBaseUrl + "/api/v1/auth/local/logout", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ refresh_token: refreshToken }),
      signal: controller.signal,
    });
  } catch {
    // Browser state still clears. The backend also accepts the immediately prior
    // deterministic refresh generation for bounded logout recovery.
  } finally {
    globalThis.clearTimeout(timeout);
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
  if (type === "session-clear") {
    const refreshToken = readString(record?.refreshToken);
    const sessionId = readString(record?.sessionId);
    return {
      type,
      ...(refreshToken ? { refreshToken } : {}),
      ...(sessionId ? { sessionId } : {}),
    };
  }
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
  const accessIdentity = readAccessTokenIdentity(accessToken);
  const subject = readString(record?.subject) ?? accessIdentity?.subject ?? null;
  const sessionId = readString(record?.sessionId) ?? accessIdentity?.sessionId ?? null;
  if (!subject || !sessionId) return null;
  if (type === "session-response") {
    const requestId = readString(record?.requestId);
    return requestId ? { type, requestId, accessToken, refreshToken, subject, sessionId, expiresAt } : null;
  }
  return { type, accessToken, refreshToken, subject, sessionId, expiresAt };
}

function parseTokenPair(value: unknown): LocalTokenPayload | null {
  const record = asRecord(value);
  if (!record) return null;
  const accessToken = readString(record.access_token);
  const refreshToken = readString(record.refresh_token);
  const accessIdentity = readAccessTokenIdentity(accessToken);
  const subject = readString(record.subject) ?? accessIdentity?.subject ?? null;
  const sessionId = readString(record.session_id) ?? accessIdentity?.sessionId ?? null;
  const expiresIn = readPositiveInteger(record.expires_in);
  const refreshExpiresIn = readPositiveInteger(record.refresh_expires_in);
  if (!accessToken || !refreshToken || !subject || !sessionId || !expiresIn || !refreshExpiresIn) {
    return null;
  }
  return {
    access_token: accessToken,
    refresh_token: refreshToken,
    subject,
    session_id: sessionId,
    expires_in: expiresIn,
    refresh_expires_in: refreshExpiresIn,
  };
}

type AccessTokenIdentity = {
  subject: string;
  sessionId: string;
};

function readAccessTokenIdentity(accessToken: string | null): AccessTokenIdentity | null {
  if (!accessToken) return null;
  const parts = accessToken.split(".");
  if (parts.length !== 3 || typeof atob !== "function") return null;
  try {
    const encoded = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = encoded.padEnd(Math.ceil(encoded.length / 4) * 4, "=");
    const payload = asRecord(JSON.parse(atob(padded)) as unknown);
    const subject = payload ? readString(payload.sub) : null;
    const sessionId = payload ? readString(payload.sid) : null;
    return subject && sessionId ? { subject, sessionId } : null;
  } catch {
    return null;
  }
}

function readLoggedOutSessionIds(): string[] {
  if (typeof window === "undefined") return [];
  const raw = window.sessionStorage.getItem(LOGGED_OUT_SESSION_IDS_KEY);
  if (!raw) return [];
  try {
    const value = JSON.parse(raw) as unknown;
    return Array.isArray(value)
      ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim()))
      : [];
  } catch {
    return [];
  }
}

function markLoggedOutSession(sessionId: string): void {
  if (typeof window === "undefined" || !sessionId.trim()) return;
  const next = [sessionId, ...readLoggedOutSessionIds().filter((item) => item !== sessionId)].slice(0, 8);
  window.sessionStorage.setItem(LOGGED_OUT_SESSION_IDS_KEY, JSON.stringify(next));
}

function isLoggedOutSession(sessionId: string): boolean {
  return readLoggedOutSessionIds().includes(sessionId);
}

function blockPeerAdoption(): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(PEER_ADOPTION_BLOCKED_KEY, "1");
}

function allowPeerAdoption(): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(PEER_ADOPTION_BLOCKED_KEY);
}

function isPeerAdoptionBlocked(): boolean {
  return typeof window !== "undefined" && window.sessionStorage.getItem(PEER_ADOPTION_BLOCKED_KEY) === "1";
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
