import { describe, expect, it } from "vitest";

import { StaticAccessTokenProvider } from "./auth.js";
import { NexoLabBackend } from "./backend.js";
import type { McpConfig } from "./config.js";

const config: McpConfig = {
  host: "127.0.0.1",
  port: 8787,
  telemetryApiUrl: "http://nexolab.local:8082",
  nodesApiUrl: "http://nexolab.local:8082",
  organizationId: "00000000-0000-0000-0000-000000000001",
  backendAuth: { mode: "none" },
  allowedHosts: ["127.0.0.1", "localhost", "::1"],
  allowedOrigins: [],
  requestTimeoutMs: 1_000,
  maxLatestItems: 200,
  maxHistoryItems: 500,
  maxHistoryHours: 744,
};

describe("NexoLabBackend", () => {
  it("sends organization and bearer headers to protected read APIs", async () => {
    let request: RequestInit | undefined;
    const backend = new NexoLabBackend(config, {
      accessTokenProvider: new StaticAccessTokenProvider("backend-access-token"),
      fetch: async (_input, init) => {
        request = init;
        return new Response(JSON.stringify({ items: [], count: 0, limit: 1, offset: 0, next_offset: null }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      },
    });

    await backend.latestTelemetry({}, 1);
    const headers = new Headers(request?.headers);
    expect(headers.get("X-Organization-ID")).toBe(config.organizationId);
    expect(headers.get("Authorization")).toBe("Bearer backend-access-token");
  });

  it("never allows a caller to choose an arbitrary backend URL", async () => {
    let calledUrl = "";
    const backend = new NexoLabBackend(config, {
      accessTokenProvider: new StaticAccessTokenProvider("backend-access-token"),
      fetch: async (input) => {
        calledUrl = String(input);
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      },
    });

    await backend.listNodes(10);
    expect(calledUrl).toBe("http://nexolab.local:8082/api/v1/nodes");
  });
});
