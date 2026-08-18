import { describe, expect, it } from "vitest";

import { LocalSessionAccessTokenProvider } from "./auth.js";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("LocalSessionAccessTokenProvider", () => {
  it("logs in once and reuses a still-valid access token", async () => {
    const calls: Array<{ url: string; body: string }> = [];
    const provider = new LocalSessionAccessTokenProvider(
      "http://nexolab.local:8082",
      "mcp-viewer",
      "/run/secrets/password",
      {
        timeoutMs: 1_000,
        readSecret: async () => "secret-password\n",
        fetch: async (input, init) => {
          calls.push({ url: String(input), body: String(init?.body ?? "") });
          return jsonResponse({
            access_token: "access-token-0000000000000001",
            refresh_token: "refresh-token-00000000000000000000000000000001",
            expires_in: 300,
            refresh_expires_in: 3600,
          });
        },
      },
    );

    expect(await provider.getAccessToken()).toBe("access-token-0000000000000001");
    expect(await provider.getAccessToken()).toBe("access-token-0000000000000001");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toContain("/api/v1/auth/local/login");
    expect(calls[0]?.body).toContain('"username":"mcp-viewer"');
  });

  it("refreshes after invalidation without reading the password again", async () => {
    let secretReads = 0;
    let calls = 0;
    const provider = new LocalSessionAccessTokenProvider(
      "http://nexolab.local:8082",
      "mcp-viewer",
      "/run/secrets/password",
      {
        timeoutMs: 1_000,
        readSecret: async () => {
          secretReads += 1;
          return "secret-password";
        },
        fetch: async (input) => {
          calls += 1;
          if (String(input).endsWith("/login")) {
            return jsonResponse({
              access_token: "access-token-0000000000000001",
              refresh_token: "refresh-token-00000000000000000000000000000001",
              expires_in: 300,
              refresh_expires_in: 3600,
            });
          }
          return jsonResponse({
            access_token: "access-token-0000000000000002",
            refresh_token: "refresh-token-00000000000000000000000000000002",
            expires_in: 300,
            refresh_expires_in: 3600,
          });
        },
      },
    );

    await provider.getAccessToken();
    provider.invalidate();
    expect(await provider.getAccessToken()).toBe("access-token-0000000000000002");
    expect(calls).toBe(2);
    expect(secretReads).toBe(1);
  });
});
