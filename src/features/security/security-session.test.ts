import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createAuthenticatedFetch,
  hasPermission,
  HttpSecuritySessionClient,
  getSecurityCredentials,
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

afterEach(() => {
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
      fetchImpl: vi.fn(async () =>
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
      fetchImpl: vi.fn(async () =>
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
