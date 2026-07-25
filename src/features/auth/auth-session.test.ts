import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AUTH_TOKEN_STORAGE_KEY,
  authenticatedWebSocketProtocols,
  bearerHeaders,
  clearBrowserAccessToken,
  fetchAuthSession,
  hasPermission,
  readBrowserAccessToken,
  writeBrowserAccessToken,
} from "./auth-session";

afterEach(() => {
  window.sessionStorage.clear();
});

describe("browser access token", () => {
  it("stores, reads and clears the session token", () => {
    writeBrowserAccessToken("  token-value  ");

    expect(readBrowserAccessToken()).toBe("token-value");
    expect(window.sessionStorage.getItem(AUTH_TOKEN_STORAGE_KEY)).toBe("token-value");

    clearBrowserAccessToken();
    expect(readBrowserAccessToken()).toBeNull();
  });

  it("builds bearer and WebSocket authentication metadata", () => {
    expect(bearerHeaders("abc").get("Authorization")).toBe("Bearer abc");
    expect(authenticatedWebSocketProtocols("abc")).toEqual([
      "nexolab.v1",
      "nexolab.jwt.abc",
    ]);
    expect(authenticatedWebSocketProtocols(null)).toBeUndefined();
  });
});

describe("auth session API", () => {
  it("validates a successful session payload", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          subject: "operator-1",
          organization_id: "laboratory-a",
          role: "operator",
          permissions: ["telemetry.read", "layouts.read", "layouts.write"],
          email: "operator@example.com",
          display_name: "Operator One",
          provider: "jwt",
        }),
        { status: 200 },
      ),
    );

    const result = await fetchAuthSession("https://api.example.test", "token", fetchImpl);

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.organizationId).toBe("laboratory-a");
    expect(result.value.role).toBe("operator");
    expect(hasPermission(result.value, "layouts.write")).toBe(true);
    expect(hasPermission(result.value, "layouts.publish")).toBe(false);
    expect(fetchImpl).toHaveBeenCalledWith(
      "https://api.example.test/api/v1/auth/session",
      expect.objectContaining({
        headers: expect.any(Headers),
      }),
    );
    const headers = fetchImpl.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer token");
  });

  it("returns explicit authentication-required state without a token", async () => {
    const fetchImpl = vi.fn<typeof fetch>();

    const result = await fetchAuthSession("https://api.example.test", null, fetchImpl);

    expect(result).toEqual({
      ok: false,
      error: expect.objectContaining({
        code: "AUTHENTICATION_REQUIRED",
        status: 401,
      }),
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("maps server permission denial", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "permission_denied",
            message: "permission denied",
            permission: "audit.read",
          },
        }),
        { status: 403 },
      ),
    );

    const result = await fetchAuthSession("https://api.example.test", "token", fetchImpl);

    expect(result).toEqual({
      ok: false,
      error: {
        code: "PERMISSION_DENIED",
        message: "permission denied",
        status: 403,
        permission: "audit.read",
      },
    });
  });

  it("rejects an unknown role or permission", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          subject: "operator-1",
          organization_id: "laboratory-a",
          role: "owner",
          permissions: ["everything"],
          email: null,
          display_name: null,
          provider: "jwt",
        }),
        { status: 200 },
      ),
    );

    const result = await fetchAuthSession("https://api.example.test", "token", fetchImpl);

    expect(result).toEqual({
      ok: false,
      error: expect.objectContaining({ code: "INVALID_AUTH_RESPONSE" }),
    });
  });
});
