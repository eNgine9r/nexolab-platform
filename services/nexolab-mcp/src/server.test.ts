import { Client, InMemoryTransport } from "@modelcontextprotocol/client";
import { afterEach, describe, expect, it } from "vitest";

import type { NexoLabBackend } from "./backend.js";
import type { McpConfig } from "./config.js";
import { buildMcpServer } from "./server.js";

const config: McpConfig = {
  host: "127.0.0.1",
  port: 8787,
  telemetryApiUrl: "http://127.0.0.1:8100",
  nodesApiUrl: "http://127.0.0.1:8100",
  allowedHosts: ["127.0.0.1", "localhost", "::1"],
  allowedOrigins: [],
  requestTimeoutMs: 8_000,
  maxLatestItems: 200,
  maxHistoryItems: 500,
  maxHistoryHours: 24,
};

function fakeBackend(): NexoLabBackend {
  return {
    telemetryReadiness: async () => ({ status: "ready", database: "ready", mqtt: "ready" }),
    latestTelemetry: async (_filters, limit) => ({
      items: [
        {
          event_id: "evt-1",
          node_id: "node-1",
          captured_at: "2026-08-18T12:00:00Z",
          metric: "temperature",
          value: 4.2,
          unit: "C",
          quality: "valid",
          equipment_id: "cold-room-1",
          channel_id: "t1",
          alarm: null,
        },
      ],
      count: 1,
      limit,
      offset: 0,
      nextOffset: null,
      snapshotAt: "2026-08-18T12:00:01Z",
    }),
    telemetryHistory: async (_filters, from, to, limit) => ({
      items: [{ captured_at: from, to, value: 4.2 }],
      count: 1,
      limit,
      offset: 0,
      nextOffset: null,
      snapshotAt: null,
    }),
    listNodes: async () => [{ node_id: "node-1", display_name: "Lab edge" }],
    nodeOperationalState: async () => ({ state: "active" }),
    nodeHealthHistory: async () => [{ healthy: true }],
    nodeStatusHistory: async () => [{ status: "online" }],
  } as unknown as NexoLabBackend;
}

type Harness = {
  client: Client;
  server: ReturnType<typeof buildMcpServer>;
};

const harnesses: Harness[] = [];

async function connect(): Promise<Harness> {
  const server = buildMcpServer(fakeBackend(), config);
  const client = new Client({ name: "nexolab-mcp-test", version: "0.1.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await server.connect(serverTransport);
  await client.connect(clientTransport);
  const harness = { client, server };
  harnesses.push(harness);
  return harness;
}

afterEach(async () => {
  await Promise.all(
    harnesses.splice(0).map(async ({ client, server }) => {
      await client.close();
      await server.close();
    }),
  );
});

describe("NEXOLAB MCP", () => {
  it("exposes only the intended read-only tool surface", async () => {
    const { client } = await connect();
    const result = await client.listTools();
    const names = result.tools.map((tool) => tool.name).sort();

    expect(names).toEqual([
      "nexolab_get_active_alarms",
      "nexolab_get_latest_telemetry",
      "nexolab_get_node_status",
      "nexolab_get_system_health",
      "nexolab_get_telemetry_history",
      "nexolab_list_nodes",
    ]);
    expect(result.tools.every((tool) => tool.annotations?.readOnlyHint === true)).toBe(true);
    expect(result.tools.every((tool) => tool.annotations?.destructiveHint === false)).toBe(true);
  });

  it("returns structured telemetry data", async () => {
    const { client } = await connect();
    const result = await client.callTool({
      name: "nexolab_get_latest_telemetry",
      arguments: { metric: "temperature", limit: 10 },
    });

    expect(result.isError).not.toBe(true);
    expect(result.structuredContent).toMatchObject({ count: 1 });
  });

  it("rejects history intervals larger than the configured safety window", async () => {
    const { client } = await connect();
    const result = await client.callTool({
      name: "nexolab_get_telemetry_history",
      arguments: {
        from: "2026-08-01T00:00:00Z",
        to: "2026-08-03T00:00:00Z",
        limit: 10,
      },
    });

    expect(result.isError).toBe(true);
    const text = result.content.find((item) => item.type === "text");
    expect(text && "text" in text ? text.text : "").toContain("24-hour MCP limit");
  });
});
