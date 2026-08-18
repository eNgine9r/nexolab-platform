import { McpServer } from "@modelcontextprotocol/server";
import * as z from "zod/v4";

import { BackendError, NexoLabBackend, type TelemetryFilters } from "./backend.js";
import type { McpConfig } from "./config.js";

const SAFE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const QUALITY = ["valid", "sensor_error", "communication_error", "unknown"] as const;
const ALARM = ["low", "high"] as const;

const optionalIdentifier = z.string().trim().min(1).max(128).regex(SAFE_ID).optional();
const optionalMetric = z.string().trim().min(1).max(128).optional();

const telemetryFilterShape = {
  nodeId: optionalIdentifier.describe("NEXOLAB node ID"),
  equipmentId: optionalIdentifier.describe("Equipment ID"),
  channelId: optionalIdentifier.describe("Channel ID"),
  metric: optionalMetric.describe("Metric name, for example temperature"),
  quality: z.enum(QUALITY).optional(),
} as const;

type JsonResult = {
  content: Array<{ type: "text"; text: string }>;
  structuredContent?: Record<string, unknown>;
  isError?: boolean;
};

function ok(data: Record<string, unknown>): JsonResult {
  return {
    content: [{ type: "text", text: JSON.stringify(data) }],
    structuredContent: data,
  };
}

function toolError(error: unknown): JsonResult {
  const message =
    error instanceof BackendError
      ? error.message
      : error instanceof Error
        ? error.message
        : "Unexpected NEXOLAB MCP error.";
  return {
    content: [{ type: "text", text: message }],
    isError: true,
  };
}

function toFilters(input: {
  nodeId?: string | undefined;
  equipmentId?: string | undefined;
  channelId?: string | undefined;
  metric?: string | undefined;
  quality?: (typeof QUALITY)[number] | undefined;
  alarm?: (typeof ALARM)[number] | undefined;
}): TelemetryFilters {
  return {
    ...(input.nodeId ? { nodeId: input.nodeId } : {}),
    ...(input.equipmentId ? { equipmentId: input.equipmentId } : {}),
    ...(input.channelId ? { channelId: input.channelId } : {}),
    ...(input.metric ? { metric: input.metric } : {}),
    ...(input.quality ? { quality: input.quality } : {}),
    ...(input.alarm ? { alarm: input.alarm } : {}),
  };
}

function parseInstant(value: string, label: string): number {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) throw new Error(`${label} must be an ISO-8601 timestamp.`);
  return timestamp;
}

const readOnlyAnnotations = {
  readOnlyHint: true,
  destructiveHint: false,
  idempotentHint: true,
  openWorldHint: false,
} as const;

export function buildMcpServer(backend: NexoLabBackend, config: McpConfig): McpServer {
  const server = new McpServer(
    {
      name: "nexolab-mcp",
      version: "0.1.0",
      websiteUrl: "https://github.com/eNgine9r/nexolab-platform",
    },
    { capabilities: { tools: {} } },
  );

  server.registerTool(
    "nexolab_get_system_health",
    {
      title: "Get NEXOLAB system health",
      description:
        "Read the telemetry service readiness and ingestion health. This tool never changes NEXOLAB state.",
      annotations: readOnlyAnnotations,
    },
    async () => {
      try {
        const telemetry = await backend.telemetryReadiness();
        return ok({ telemetry });
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    "nexolab_list_nodes",
    {
      title: "List NEXOLAB nodes",
      description: "List configured NEXOLAB edge nodes. Results are bounded to protect the MCP context.",
      inputSchema: z.object({
        limit: z.number().int().min(1).max(100).default(50),
      }),
      annotations: readOnlyAnnotations,
    },
    async ({ limit }) => {
      try {
        const nodes = await backend.listNodes(limit);
        return ok({ nodes, count: nodes.length });
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    "nexolab_get_node_status",
    {
      title: "Get NEXOLAB node status",
      description:
        "Read a node operational state plus its latest health and status observations. No lifecycle action is exposed.",
      inputSchema: z.object({
        nodeId: z.string().trim().min(1).max(128).regex(SAFE_ID),
      }),
      annotations: readOnlyAnnotations,
    },
    async ({ nodeId }) => {
      try {
        const [operationalState, health, status] = await Promise.all([
          backend.nodeOperationalState(nodeId),
          backend.nodeHealthHistory(nodeId, 1),
          backend.nodeStatusHistory(nodeId, 1),
        ]);
        return ok({
          nodeId,
          operationalState,
          latestHealth: health[0] ?? null,
          latestStatus: status[0] ?? null,
        });
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    "nexolab_get_latest_telemetry",
    {
      title: "Get latest NEXOLAB telemetry",
      description:
        "Read the latest telemetry samples with optional node, equipment, channel, metric, or quality filters.",
      inputSchema: z.object({
        ...telemetryFilterShape,
        limit: z.number().int().min(1).max(config.maxLatestItems).default(Math.min(50, config.maxLatestItems)),
      }),
      annotations: readOnlyAnnotations,
    },
    async (input) => {
      try {
        const result = await backend.latestTelemetry(toFilters(input), input.limit);
        return ok({
          items: result.items,
          count: result.count,
          limit: result.limit,
          offset: result.offset,
          nextOffset: result.nextOffset,
          snapshotAt: result.snapshotAt,
        });
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    "nexolab_get_telemetry_history",
    {
      title: "Get NEXOLAB telemetry history",
      description:
        "Read bounded historical telemetry for a requested ISO-8601 interval. The server rejects reversed or excessively large intervals.",
      inputSchema: z.object({
        ...telemetryFilterShape,
        from: z.string().trim().min(1).max(64),
        to: z.string().trim().min(1).max(64),
        limit: z.number().int().min(1).max(config.maxHistoryItems).default(Math.min(200, config.maxHistoryItems)),
      }),
      annotations: readOnlyAnnotations,
    },
    async (input) => {
      try {
        const fromMs = parseInstant(input.from, "from");
        const toMs = parseInstant(input.to, "to");
        if (toMs <= fromMs) throw new Error("to must be later than from.");
        const hours = (toMs - fromMs) / 3_600_000;
        if (hours > config.maxHistoryHours) {
          throw new Error(`Requested interval exceeds the ${config.maxHistoryHours}-hour MCP limit.`);
        }
        const result = await backend.telemetryHistory(toFilters(input), input.from, input.to, input.limit);
        return ok({
          items: result.items,
          count: result.count,
          limit: result.limit,
          offset: result.offset,
          nextOffset: result.nextOffset,
          snapshotAt: result.snapshotAt,
          from: input.from,
          to: input.to,
        });
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    "nexolab_get_active_alarms",
    {
      title: "Get active NEXOLAB telemetry alarms",
      description:
        "Read latest telemetry samples marked with low or high alarm state. Use alarm=all to retrieve both categories.",
      inputSchema: z.object({
        nodeId: optionalIdentifier,
        equipmentId: optionalIdentifier,
        metric: optionalMetric,
        alarm: z.enum(["all", ...ALARM]).default("all"),
        limitPerAlarm: z.number().int().min(1).max(config.maxLatestItems).default(Math.min(100, config.maxLatestItems)),
      }),
      annotations: readOnlyAnnotations,
    },
    async ({ nodeId, equipmentId, metric, alarm, limitPerAlarm }) => {
      try {
        const common = toFilters({ nodeId, equipmentId, metric });
        const requested = alarm === "all" ? ALARM : [alarm] as const;
        const collections = await Promise.all(
          requested.map((alarmValue) =>
            backend.latestTelemetry({ ...common, alarm: alarmValue }, limitPerAlarm),
          ),
        );
        const items = collections.flatMap((collection) => collection.items);
        items.sort((a, b) => {
          const left = typeof a.captured_at === "string" ? Date.parse(a.captured_at) : 0;
          const right = typeof b.captured_at === "string" ? Date.parse(b.captured_at) : 0;
          return right - left;
        });
        return ok({ items, count: items.length, alarm });
      } catch (error) {
        return toolError(error);
      }
    },
  );

  return server;
}
