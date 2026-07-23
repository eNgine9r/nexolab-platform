import { describe, expect, it, vi } from "vitest";

import { resolveTelemetryClientConfig } from "./config";
import { TelemetryRestClient } from "./rest-client";

const sample = {
  event_id: "56bb5d38-1c20-48c7-bfaf-8d3101da9e21",
  node_id: "edge-01",
  captured_at: "2026-07-23T12:05:20.442225+00:00",
  metric: "electrical.voltage",
  value: 227.3,
  unit: "V",
  quality: "valid",
  source: "f-and-f-le-01mp",
  equipment_id: "LE01MP-201",
  channel_id: "201-voltage",
  alarm: null,
  raw_value: 2273,
  raw_status: null,
  received_at: "2026-07-23T12:05:21+00:00",
};

function collection(items: unknown[]) {
  return {
    items,
    count: items.length,
    limit: 200,
    offset: 0,
    next_offset: null,
  };
}

describe("TelemetryRestClient", () => {
  it("requests and validates latest telemetry", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify(collection([sample])), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    );
    const client = new TelemetryRestClient({
      config: resolveTelemetryClientConfig({
        NEXT_PUBLIC_TELEMETRY_API_BASE_URL: "https://api.nexolab.example",
      }),
      fetchImpl: fetchImpl as typeof fetch,
    });

    const result = await client.latest({ node_id: "edge-01" });

    expect(result.items[0]?.value).toBe(227.3);
    expect(fetchImpl).toHaveBeenCalledWith(
      "https://api.nexolab.example/api/v1/telemetry/latest?node_id=edge-01",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("rejects successful HTTP responses with invalid payloads", async () => {
    const client = new TelemetryRestClient({
      config: resolveTelemetryClientConfig({
        NEXT_PUBLIC_TELEMETRY_API_BASE_URL: "https://api.nexolab.example",
      }),
      fetchImpl: vi.fn(
        async () =>
          new Response(JSON.stringify({ items: "not-an-array" }), {
            status: 200,
          }),
      ) as typeof fetch,
    });

    await expect(client.latest()).rejects.toThrow("telemetry collection has an invalid shape");
  });

  it("surfaces backend status and response detail", async () => {
    const client = new TelemetryRestClient({
      config: resolveTelemetryClientConfig({
        NEXT_PUBLIC_TELEMETRY_API_BASE_URL: "https://api.nexolab.example",
      }),
      fetchImpl: vi.fn(async () => new Response("database unavailable", { status: 503 })) as typeof fetch,
    });

    await expect(client.latest()).rejects.toEqual(
      expect.objectContaining({
        name: "TelemetryRequestError",
        status: 503,
        message: expect.stringContaining("database unavailable"),
      }),
    );
  });
});
