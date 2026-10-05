import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createLocalCredentialProvider, signInWithLocalPassword, signOutLocal } from "./local-auth";
import {
  getSecurityCredentials,
  SECURITY_CREDENTIALS_INVALIDATED_EVENT,
  setSecurityCredentials,
} from "./security-session";

const API_BASE_URL = "http://127.0.0.1:8082";
const ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111";

function tokenResponse(accessToken: string, refreshToken: string, expiresIn = 300): Response {
  return new Response(
    JSON.stringify({
      token_type: "Bearer",
      access_token: accessToken,
      refresh_token: refreshToken,
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
  setSecurityCredentials({ accessToken: null, organizationId: ORGANIZATION_ID });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.sessionStorage.clear();
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
    expect(window.localStorage.length).toBe(0);
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
    expect(window.localStorage.length).toBe(0);
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
    expect(window.sessionStorage.length).toBe(0);
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
    window.sessionStorage.setItem(
      "nexolab.local-auth.access-expires-at",
      String(Date.now() + 300_000),
    );
    vi.stubGlobal("navigator", {
      locks: {
        request: vi.fn(async (_name: string, callback: () => Promise<unknown>) => {
          window.sessionStorage.setItem("nexolab.local-auth.refresh-token", "refresh-new");
          return callback();
        }),
      },
    });
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await signOutLocal(API_BASE_URL);

    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      refresh_token: "refresh-new",
    });
    expect(window.sessionStorage.length).toBe(0);
  });

  it("revokes the refresh session and clears browser credentials on logout", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(tokenResponse("access-1", "refresh-1"))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await signInWithLocalPassword(API_BASE_URL, "operator", "valid-password");
    await signOutLocal(API_BASE_URL);

    expect(window.sessionStorage.length).toBe(0);
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

it("adopts the peer session without reverting organization and ignores stale peer clears", async () => {
  type Listener = (event: MessageEvent<unknown>) => void;
  let peerChannel: PeerSessionChannel | null = null;
  class PeerSessionChannel {
    private listener: Listener | null = null;

    constructor() {
      peerChannel = this;
    }

    addEventListener(_type: "message", listener: Listener): void {
      this.listener = listener;
    }

    postMessage(message: unknown): void {
      const request = message as { type?: string; requestId?: string };
      if (request.type !== "session-request" || !request.requestId) return;
      setSecurityCredentials({ accessToken: "expired", organizationId: "organization-b" });
      queueMicrotask(() => {
        this.listener?.({
          data: {
            type: "session-response",
            requestId: request.requestId,
            accessToken: "peer-access",
            refreshToken: "peer-refresh",
            expiresAt: Date.now() + 300_000,
          },
        } as MessageEvent<unknown>);
      });
    }

    emit(data: unknown): void {
      this.listener?.({ data } as MessageEvent<unknown>);
    }
  }

  vi.stubGlobal("BroadcastChannel", PeerSessionChannel);
  window.sessionStorage.clear();
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  const invalidated = vi.fn();
  window.addEventListener(SECURITY_CREDENTIALS_INVALIDATED_EVENT, invalidated);

  try {
    const credentials = await createLocalCredentialProvider(API_BASE_URL, ORGANIZATION_ID)();

    expect(credentials).toEqual({ accessToken: "peer-access", organizationId: "organization-b" });
    expect(window.sessionStorage.getItem("nexolab.local-auth.refresh-token")).toBe("peer-refresh");
    expect(window.localStorage.length).toBe(0);
    expect(fetchMock).not.toHaveBeenCalled();

    peerChannel?.emit({ type: "session-clear", refreshToken: "stale-refresh" });
    expect(window.sessionStorage.getItem("nexolab.local-auth.refresh-token")).toBe("peer-refresh");
    expect(invalidated).not.toHaveBeenCalled();

    peerChannel?.emit({ type: "session-clear" });
    expect(window.sessionStorage.getItem("nexolab.local-auth.refresh-token")).toBeNull();
    expect(invalidated).toHaveBeenCalledOnce();
  } finally {
    window.removeEventListener(SECURITY_CREDENTIALS_INVALIDATED_EVENT, invalidated);
  }
});
