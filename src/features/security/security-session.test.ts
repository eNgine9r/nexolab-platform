import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createAuthenticatedFetch,
  getSecurityCredentials,
  hasPermission,
  HttpSecuritySessionClient,
  setSecurityCredentials,
} from "./security-session";

const sessionPayload = {
  authenticated: true,
  identity: {
    id: "identity-1",
    provider: "test-oidc",
    subject: "viewer-1",
    email: "viewer@example.test",
    display_name: "Viewer One",
  },
  memberships: [
    {
      organization_id: "org-1",
      organization_slug: "nexolab",
      organization_name: "NEXOLAB Laboratory",
      roles: ["viewer"],
      permissions: ["dashboard.read", "telemetry.read", "reports.read"],
    },
  ],
};

const browserLocation = {
  origin: "http://dashboard.example.test",
  protocol: "http:",
};

afterEach(() => {
  vi.useRealTimers();
  setSecurityCredentials({ accessToken: null, organizationId: null });
});

describe("security session client", () => {
  it("adds verified bearer and organization headers to API requests", async () => {
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const headers = new Headers(init?.headers);
      expect(headers.get("Authorization")).toBe("Bearer signed-token");
      expect(headers.get("X-Organization-ID")).toBe("org-1");
      expect(init?.credentials).toBe("same-origin");
      return new Response(JSON.stringify(sessionPayload), {
        headers: { "Content-Type": "application/json" },
      });
    }) as unknown as typeof fetch;
    const authenticatedFetch = createAuthenticatedFetch(fetchImpl, () => ({
      accessToken: "signed-token",
      organizationId: "org-1",
    }));

    const response = await authenticatedFetch("https://api.example.test/api/v1/auth/session");

    expect(response.ok).toBe(true);
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it("parses memberships and evaluates explicit permissions", async () => {
    const client = new HttpSecuritySessionClient({
      apiBaseUrl: "https://api.example.test",
      browserLocation,
      fetchImpl: vi.fn(
        async () =>
          new Response(JSON.stringify(sessionPayload), {
            headers: { "Content-Type": "application/json" },
          }),
      ) as unknown as typeof fetch,
    });

    const result = await client.getSession();

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.identity.displayName).toBe("Viewer One");
    expect(hasPermission(result.value, "org-1", "telemetry.read")).toBe(true);
    expect(hasPermission(result.value, "org-1", "layout.draft.edit")).toBe(false);
  });

  it("maps HTTP 401 to an authentication-required result", async () => {
    const client = new HttpSecuritySessionClient({
      apiBaseUrl: "https://api.example.test",
      browserLocation,
      fetchImpl: vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              detail: { code: "missing_bearer_token", message: "Bearer token is required" },
            }),
            { status: 401, headers: { "Content-Type": "application/json" } },
          ),
      ) as unknown as typeof fetch,
    });

    const result = await client.getSession();

    expect(result).toEqual({
      ok: false,
      error: {
        code: "AUTHENTICATION_REQUIRED",
        message: "Bearer token is required",
        diagnostics: {
          apiOrigin: "https://api.example.test",
          browserOrigin: "http://dashboard.example.test",
          endpointPath: "/api/v1/auth/session",
          timeoutMs: 8_000,
          httpStatus: 401,
        },
      },
    });
  });

  it("maps HTTP 403 to an access-denied result", async () => {
    const client = new HttpSecuritySessionClient({
      apiBaseUrl: "https://api.example.test",
      browserLocation,
      fetchImpl: vi.fn(async () => new Response(null, { status: 403 })) as unknown as typeof fetch,
    });

    const result = await client.getSession();

    expect(result).toMatchObject({
      ok: false,
      error: {
        code: "ACCESS_DENIED",
        diagnostics: { httpStatus: 403 },
      },
    });
  });

  it("does not classify a server error as an authorization denial", async () => {
    const client = new HttpSecuritySessionClient({
      apiBaseUrl: "https://api.example.test",
      browserLocation,
      fetchImpl: vi.fn(async () => new Response(null, { status: 503 })) as unknown as typeof fetch,
    });

    const result = await client.getSession();

    expect(result).toMatchObject({
      ok: false,
      error: {
        code: "SESSION_API_ERROR",
        diagnostics: { httpStatus: 503 },
      },
    });
  });

  it("rejects mixed content before issuing a browser request", async () => {
    const fetchImpl = vi.fn() as unknown as typeof fetch;
    const client = new HttpSecuritySessionClient({
      apiBaseUrl: "http://api.example.test",
      browserLocation: {
        origin: "https://dashboard.example.test",
        protocol: "https:",
      },
      fetchImpl,
    });

    const result = await client.getSession();

    expect(result).toMatchObject({
      ok: false,
      error: {
        code: "SESSION_MIXED_CONTENT",
        diagnostics: {
          apiOrigin: "http://api.example.test",
          browserOrigin: "https://dashboard.example.test",
        },
      },
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("returns a bounded timeout result and aborts the request", async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn(
      async (_input: RequestInfo | URL, init?: RequestInit) =>
        await new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        }),
    ) as unknown as typeof fetch;
    const client = new HttpSecuritySessionClient({
      apiBaseUrl: "https://api.example.test",
      browserLocation,
      fetchImpl,
      requestTimeoutMs: 1_000,
    });

    const resultPromise = client.getSession();
    await vi.advanceTimersByTimeAsync(1_000);
    const result = await resultPromise;

    expect(result).toMatchObject({
      ok: false,
      error: {
        code: "SESSION_REQUEST_TIMEOUT",
        diagnostics: { timeoutMs: 1_000 },
      },
    });
  });

  it("reports a generic browser transport failure without claiming a single cause", async () => {
    const client = new HttpSecuritySessionClient({
      apiBaseUrl: "http://192.168.1.50:8082",
      browserLocation,
      fetchImpl: vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }) as unknown as typeof fetch,
    });

    const result = await client.getSession();

    expect(result).toMatchObject({
      ok: false,
      error: {
        code: "SESSION_API_UNREACHABLE_OR_ORIGIN_BLOCKED",
        diagnostics: {
          apiOrigin: "http://192.168.1.50:8082",
          browserOrigin: "http://dashboard.example.test",
          httpStatus: null,
        },
      },
    });
  });

  it("keeps credentials in memory without reading public environment tokens", () => {
    setSecurityCredentials({ accessToken: "runtime-token", organizationId: "org-1" });

    expect(getSecurityCredentials()).toEqual({
      accessToken: "runtime-token",
      organizationId: "org-1",
    });
  });
});
