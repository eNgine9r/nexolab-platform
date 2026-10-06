import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createLocalCredentialProvider, signInWithLocalPassword, signOutLocal } from "./local-auth";
import {
  getSecurityCredentials,
  SECURITY_CREDENTIALS_INVALIDATED_EVENT,
  SECURITY_CREDENTIALS_UPDATED_EVENT,
  setSecurityCredentials,
} from "./security-session";

const API_BASE_URL = "http://127.0.0.1:8082";
const ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111";
const LOCAL_AUTH_CREDENTIAL_STORAGE_KEYS = [
  "nexolab.local-auth.access-token",
  "nexolab.local-auth.refresh-token",
  "nexolab.local-auth.access-expires-at",
  "nexolab.local-auth.subject",
  "nexolab.local-auth.session-id",
] as const;
const BROWSER_SESSION_BINDING_KEY = "nexolab.local-auth.browser-session-binding";

function expectNoPersistentLocalAuthSecrets(): void {
  expect(window.localStorage.getItem("nexolab.local-auth.access-token")).toBeNull();
  expect(window.localStorage.getItem("nexolab.local-auth.refresh-token")).toBeNull();
}

function expectLocalAuthCredentialsCleared(): void {
  for (const key of LOCAL_AUTH_CREDENTIAL_STORAGE_KEYS) {
    expect(window.sessionStorage.getItem(key)).toBeNull();
  }
  expect(window.sessionStorage.getItem("nexolab.local-auth.peer-adoption-blocked")).toBe("1");
  expect(window.sessionStorage.getItem("nexolab.local-auth.logged-out-session-ids")).toBeTruthy();
}

type PeerListener = (event: MessageEvent<unknown>) => void;
let peerListener: PeerListener | null = null;
let peerRequestHandler: ((message: unknown) => void) | null = null;

class TestPeerSessionChannel {
  addEventListener(_type: "message", listener: PeerListener): void {
    peerListener = listener;
  }

  postMessage(message: unknown): void {
    peerRequestHandler?.(message);
  }
}

function usePeerChannel(handler?: (message: unknown) => void): void {
  peerRequestHandler = handler ?? null;
  vi.stubGlobal("BroadcastChannel", TestPeerSessionChannel);
}

function emitPeerMessage(data: unknown): void {
  if (!peerListener) throw new Error("peer channel listener was not initialized");
  peerListener({ data } as MessageEvent<unknown>);
}

function tokenResponse(
  accessToken: string,
  refreshToken: string,
  expiresIn = 300,
  subject = "subject-1",
  sessionId = "session-1",
): Response {
  return new Response(
    JSON.stringify({
      token_type: "Bearer",
      access_token: accessToken,
      refresh_token: refreshToken,
      subject,
      session_id: sessionId,
      expires_in: expiresIn,
      refresh_expires_in: 3600,
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

beforeEach(() => {
  vi.stubGlobal("BroadcastChannel", undefined);
  vi.stubGlobal("navigator", { locks: undefined });
  window.sessionStorage.clear();
  window.localStorage.clear();
  setSecurityCredentials({ accessToken: null, organizationId: ORGANIZATION_ID });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.sessionStorage.clear();
  window.localStorage.clear();
  setSecurityCredentials({ accessToken: null, organizationId: null });
});

describe("local browser authentication", () => {
  it("keeps local auth secrets out of persistent localStorage", async () => {
    const fetchMock = vi.fn(async () => tokenResponse("access-1", "refresh-1"));
    vi.stubGlobal("fetch", fetchMock);

    const result = await signInWithLocalPassword(API_BASE_URL, "operator", "valid-password");
    const credentials = await createLocalCredentialProvider(API_BASE_URL, ORGANIZATION_ID)();

    expect(result).toEqual({ ok: true });
    expect(credentials).toEqual({ accessToken: "access-1", organizationId: ORGANIZATION_ID });
    expect(getSecurityCredentials()).toEqual(credentials);
    expectNoPersistentLocalAuthSecrets();
    expect(JSON.parse(window.localStorage.getItem(BROWSER_SESSION_BINDING_KEY) ?? "null")).toEqual({
      subject: "subject-1",
      sessionId: "session-1",
    });
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("rotates an expiring access token through the local refresh endpoint", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-01T18:00:00Z"));
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(tokenResponse("access-1", "refresh-1", 1))
      .mockResolvedValueOnce(tokenResponse("access-2", "refresh-2", 300));
    vi.stubGlobal("fetch", fetchMock);

    await signInWithLocalPassword(API_BASE_URL, "operator", "valid-password");
    await vi.advanceTimersByTimeAsync(2_000);
    const credentials = await createLocalCredentialProvider(API_BASE_URL, ORGANIZATION_ID)();

    expect(credentials.accessToken).toBe("access-2");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]?.[0]).toBe(`${API_BASE_URL}/api/v1/auth/local/refresh`);
  });

  it("serializes concurrent refreshes so a rotated token cannot invalidate the active tab", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-01T18:00:00Z"));
    let resolveRefresh!: (response: Response) => void;
    const refreshResponse = new Promise<Response>((resolve) => {
      resolveRefresh = resolve;
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(tokenResponse("access-1", "refresh-1", 1))
      .mockReturnValueOnce(refreshResponse);
    vi.stubGlobal("fetch", fetchMock);

    await signInWithLocalPassword(API_BASE_URL, "operator", "valid-password");
    await vi.advanceTimersByTimeAsync(2_000);
    const provider = createLocalCredentialProvider(API_BASE_URL, ORGANIZATION_ID);
    const first = provider();
    const second = provider();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    resolveRefresh(tokenResponse("access-2", "refresh-2", 300));

    await expect(Promise.all([first, second])).resolves.toEqual([
      { accessToken: "access-2", organizationId: ORGANIZATION_ID },
      { accessToken: "access-2", organizationId: ORGANIZATION_ID },
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(window.sessionStorage.getItem("nexolab.local-auth.refresh-token")).toBe("refresh-2");
  });

  it("retains browser session material when refresh fails transiently", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(tokenResponse("access-1", "refresh-1", 1))
      .mockRejectedValueOnce(new TypeError("network unavailable"));
    vi.stubGlobal("fetch", fetchMock);

    await signInWithLocalPassword(API_BASE_URL, "operator", "valid-password");
    const credentials = await createLocalCredentialProvider(API_BASE_URL, ORGANIZATION_ID)();

    expect(credentials).toEqual({ accessToken: "access-1", organizationId: ORGANIZATION_ID });
    expect(window.sessionStorage.getItem("nexolab.local-auth.refresh-token")).toBe("refresh-1");
    expectNoPersistentLocalAuthSecrets();
  });

  it("clears local material when refresh is rejected", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(tokenResponse("access-1", "refresh-1", 1))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: { message: "session expired" } }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await signInWithLocalPassword(API_BASE_URL, "operator", "valid-password");
    const credentials = await createLocalCredentialProvider(API_BASE_URL, ORGANIZATION_ID)();

    expect(credentials).toEqual({ accessToken: null, organizationId: ORGANIZATION_ID });
    expectLocalAuthCredentialsCleared();
  });

  it("bounds a stalled refresh so the cross-tab lock is released", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-01T18:00:00Z"));
    let lockReleased = false;
    vi.stubGlobal("navigator", {
      locks: {
        request: vi.fn(async (_name: string, callback: () => Promise<unknown>) => {
          try {
            return await callback();
          } finally {
            lockReleased = true;
          }
        }),
      },
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(tokenResponse("access-1", "refresh-1", 1))
      .mockImplementation((_url: unknown, init?: RequestInit) => {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
        });
      });
    vi.stubGlobal("fetch", fetchMock);

    await signInWithLocalPassword(API_BASE_URL, "operator", "valid-password");
    await vi.advanceTimersByTimeAsync(2_000);
    const pending = createLocalCredentialProvider(API_BASE_URL, ORGANIZATION_ID)();

    await vi.advanceTimersByTimeAsync(20_001);
    await expect(pending).resolves.toEqual({
      accessToken: "access-1",
      organizationId: ORGANIZATION_ID,
    });
    expect(lockReleased).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("reads the latest rotated token only after acquiring the logout lock", async () => {
    window.sessionStorage.setItem("nexolab.local-auth.access-token", "access-old");
    window.sessionStorage.setItem("nexolab.local-auth.refresh-token", "refresh-old");
    window.sessionStorage.setItem("nexolab.local-auth.access-expires-at", String(Date.now() + 300_000));
    window.sessionStorage.setItem("nexolab.local-auth.subject", "subject-1");
    window.sessionStorage.setItem("nexolab.local-auth.session-id", "session-1");
    vi.stubGlobal("navigator", {
      locks: {
        request: vi.fn(async (_name: string, callback: () => Promise<unknown>) => {
          window.sessionStorage.setItem("nexolab.local-auth.refresh-token", "refresh-new");
          return callback();
        }),
      },
    });
    let logoutBody: BodyInit | null | undefined;
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      logoutBody = init?.body;
      return new Response(null, { status: 204 });
    });
    vi.stubGlobal("fetch", fetchMock);

    await signOutLocal(API_BASE_URL);

    expect(JSON.parse(String(logoutBody))).toEqual({
      refresh_token: "refresh-new",
    });
    expectLocalAuthCredentialsCleared();
  });

  it("revokes the refresh session and clears browser credentials on logout", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(tokenResponse("access-1", "refresh-1"))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await signInWithLocalPassword(API_BASE_URL, "operator", "valid-password");
    await signOutLocal(API_BASE_URL);

    expectLocalAuthCredentialsCleared();
    expect(getSecurityCredentials()).toEqual({ accessToken: null, organizationId: null });
    expect(fetchMock.mock.calls[1]?.[0]).toBe(`${API_BASE_URL}/api/v1/auth/local/logout`);
  });
});

it.each([200, 401])(
  "retains the newly selected organization when delayed refresh returns %s",
  async (status) => {
    window.sessionStorage.setItem("nexolab.local-auth.access-token", "expired");
    window.sessionStorage.setItem("nexolab.local-auth.refresh-token", "refresh-old");
    window.sessionStorage.setItem("nexolab.local-auth.access-expires-at", "0");
    let resolve!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((finish) => {
            resolve = finish;
          }),
      ),
    );
    const pending = createLocalCredentialProvider(API_BASE_URL, ORGANIZATION_ID)();
    await vi.waitFor(() => expect(resolve).toBeTypeOf("function"));
    setSecurityCredentials({ accessToken: "expired", organizationId: "organization-b" });
    resolve(status === 200 ? tokenResponse("fresh", "refresh-new") : new Response("{}", { status }));
    expect((await pending).organizationId).toBe("organization-b");
    expect(getSecurityCredentials().organizationId).toBe("organization-b");
  },
);

it("rejects a peer snapshot from a different local operator session", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => tokenResponse("access-1", "refresh-1")),
  );
  await signInWithLocalPassword(API_BASE_URL, "operator", "valid-password");
  usePeerChannel();
  await createLocalCredentialProvider(API_BASE_URL, ORGANIZATION_ID)();
  const invalidated = vi.fn();
  window.addEventListener(SECURITY_CREDENTIALS_UPDATED_EVENT, invalidated);
  try {
    emitPeerMessage({
      type: "session-update",
      accessToken: "admin-access",
      refreshToken: "admin-refresh",
      subject: "administrator-subject",
      sessionId: "administrator-session",
      expiresAt: Date.now() + 600_000,
    });

    expect(window.sessionStorage.getItem("nexolab.local-auth.refresh-token")).toBe("refresh-1");
    expect(window.sessionStorage.getItem("nexolab.local-auth.subject")).toBe("subject-1");
    expect(invalidated).not.toHaveBeenCalled();
  } finally {
    window.removeEventListener(SECURITY_CREDENTIALS_UPDATED_EVENT, invalidated);
  }
});

it("rejects a delayed session update after logout tombstones the server session", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(tokenResponse("access-1", "refresh-1"))
    .mockResolvedValueOnce(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetchMock);
  await signInWithLocalPassword(API_BASE_URL, "operator", "valid-password");
  usePeerChannel();
  await createLocalCredentialProvider(API_BASE_URL, ORGANIZATION_ID)();

  await signOutLocal(API_BASE_URL);
  emitPeerMessage({
    type: "session-update",
    accessToken: "late-access",
    refreshToken: "late-refresh",
    subject: "subject-1",
    sessionId: "session-1",
    expiresAt: Date.now() + 600_000,
  });

  expect(window.sessionStorage.getItem("nexolab.local-auth.refresh-token")).toBeNull();
  expect(window.sessionStorage.getItem("nexolab.local-auth.peer-adoption-blocked")).toBe("1");
});

it("notifies the dashboard when a matching peer snapshot arrives after the request timeout", async () => {
  vi.useFakeTimers();
  window.localStorage.setItem(
    BROWSER_SESSION_BINDING_KEY,
    JSON.stringify({ subject: "subject-1", sessionId: "session-1" }),
  );
  let requestId = "";
  usePeerChannel((message) => {
    const request = message as { type?: string; requestId?: string };
    if (request.type === "session-request") requestId = request.requestId ?? "";
  });
  const updated = vi.fn();
  window.addEventListener(SECURITY_CREDENTIALS_UPDATED_EVENT, updated);
  try {
    const pending = createLocalCredentialProvider(API_BASE_URL, ORGANIZATION_ID)();
    await vi.advanceTimersByTimeAsync(151);
    await expect(pending).resolves.toEqual({
      accessToken: null,
      organizationId: ORGANIZATION_ID,
    });
    expect(requestId).not.toBe("");

    emitPeerMessage({
      type: "session-response",
      requestId,
      accessToken: "peer-access",
      refreshToken: "peer-refresh",
      subject: "subject-1",
      sessionId: "session-1",
      expiresAt: Date.now() + 300_000,
    });
    await vi.advanceTimersByTimeAsync(501);

    expect(window.sessionStorage.getItem("nexolab.local-auth.refresh-token")).toBe("peer-refresh");
    expect(updated).toHaveBeenCalledOnce();
  } finally {
    window.removeEventListener(SECURITY_CREDENTIALS_UPDATED_EVENT, updated);
  }
});

it("binds an empty tab to the explicitly selected browser session", async () => {
  vi.useFakeTimers();
  window.localStorage.setItem(
    BROWSER_SESSION_BINDING_KEY,
    JSON.stringify({ subject: "viewer-subject", sessionId: "viewer-session" }),
  );
  usePeerChannel((message) => {
    const request = message as {
      type?: string;
      requestId?: string;
      subject?: string;
      sessionId?: string;
    };
    if (request.type !== "session-request" || !request.requestId) return;
    expect(request.subject).toBe("viewer-subject");
    expect(request.sessionId).toBe("viewer-session");

    emitPeerMessage({
      type: "session-response",
      requestId: request.requestId,
      accessToken: "admin-access",
      refreshToken: "admin-refresh",
      subject: "admin-subject",
      sessionId: "admin-session",
      expiresAt: Date.now() + 600_000,
    });
    emitPeerMessage({
      type: "session-response",
      requestId: request.requestId,
      accessToken: "viewer-access",
      refreshToken: "viewer-refresh",
      subject: "viewer-subject",
      sessionId: "viewer-session",
      expiresAt: Date.now() + 300_000,
    });
    window.setTimeout(() => {
      emitPeerMessage({
        type: "session-response",
        requestId: request.requestId!,
        accessToken: "late-admin-access",
        refreshToken: "late-admin-refresh",
        subject: "admin-subject",
        sessionId: "admin-session",
        expiresAt: Date.now() + 900_000,
      });
    }, 200);
  });
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);

  const pending = createLocalCredentialProvider(API_BASE_URL, ORGANIZATION_ID)();
  await vi.advanceTimersByTimeAsync(151);

  await expect(pending).resolves.toEqual({
    accessToken: "viewer-access",
    organizationId: ORGANIZATION_ID,
  });
  expect(window.sessionStorage.getItem("nexolab.local-auth.refresh-token")).toBe("viewer-refresh");

  await vi.advanceTimersByTimeAsync(250);
  expect(window.sessionStorage.getItem("nexolab.local-auth.refresh-token")).toBe("viewer-refresh");
  expect(fetchMock).not.toHaveBeenCalled();
});

it("notifies the dashboard when an existing expired peer snapshot is refreshed", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-08-01T18:00:00Z"));
  usePeerChannel();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => tokenResponse("access-1", "refresh-1", 1)),
  );
  await signInWithLocalPassword(API_BASE_URL, "operator", "valid-password");
  await vi.advanceTimersByTimeAsync(2_000);

  const updated = vi.fn();
  window.addEventListener(SECURITY_CREDENTIALS_UPDATED_EVENT, updated);
  try {
    emitPeerMessage({
      type: "session-update",
      accessToken: "access-2",
      refreshToken: "refresh-2",
      subject: "subject-1",
      sessionId: "session-1",
      expiresAt: Date.now() + 300_000,
    });

    expect(window.sessionStorage.getItem("nexolab.local-auth.refresh-token")).toBe("refresh-2");
    expect(updated).toHaveBeenCalledOnce();
  } finally {
    window.removeEventListener(SECURITY_CREDENTIALS_UPDATED_EVENT, updated);
  }
});

it("adopts the peer session without reverting organization and ignores stale peer clears", async () => {
  window.localStorage.setItem(
    BROWSER_SESSION_BINDING_KEY,
    JSON.stringify({ subject: "subject-1", sessionId: "session-1" }),
  );
  usePeerChannel((message) => {
    const request = message as { type?: string; requestId?: string };
    if (request.type !== "session-request" || !request.requestId) return;
    setSecurityCredentials({ accessToken: "expired", organizationId: "organization-b" });
    queueMicrotask(() => {
      emitPeerMessage({
        type: "session-response",
        requestId: request.requestId,
        accessToken: "peer-access",
        refreshToken: "peer-refresh",
        subject: "subject-1",
        sessionId: "session-1",
        expiresAt: Date.now() + 300_000,
      });
    });
  });
  window.sessionStorage.clear();
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  const invalidated = vi.fn();
  window.addEventListener(SECURITY_CREDENTIALS_INVALIDATED_EVENT, invalidated);

  try {
    const credentials = await createLocalCredentialProvider(API_BASE_URL, ORGANIZATION_ID)();

    expect(credentials).toEqual({ accessToken: "peer-access", organizationId: "organization-b" });
    expect(window.sessionStorage.getItem("nexolab.local-auth.refresh-token")).toBe("peer-refresh");
    expectNoPersistentLocalAuthSecrets();
    expect(fetchMock).not.toHaveBeenCalled();

    emitPeerMessage({ type: "session-clear", refreshToken: "stale-refresh" });
    expect(window.sessionStorage.getItem("nexolab.local-auth.refresh-token")).toBe("peer-refresh");
    expect(invalidated).not.toHaveBeenCalled();

    emitPeerMessage({ type: "session-clear" });
    expect(window.sessionStorage.getItem("nexolab.local-auth.refresh-token")).toBeNull();
    expect(invalidated).toHaveBeenCalledOnce();
  } finally {
    window.removeEventListener(SECURITY_CREDENTIALS_INVALIDATED_EVENT, invalidated);
  }
});
