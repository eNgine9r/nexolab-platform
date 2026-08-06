import { createRuntimeCredentialProvider } from "@/features/security/auth-runtime";
import { createAuthenticatedFetch } from "@/features/security/security-session";
import type {
  LiveDashboardInventoryCollection,
  LiveDashboardInventoryItem,
} from "@/features/live-dashboards/types";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";
import type { TelemetryAlarm, TelemetryQuality, TelemetrySample } from "@/lib/telemetry/types";

export type LiveDashboardInventoryFetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export interface LiveDashboardInventoryClientOptions {
  fetch?: LiveDashboardInventoryFetch;
  timeoutMs?: number;
}

export interface LiveDashboardInventoryQuery {
  limit?: number;
  offset?: number;
}

export class LiveDashboardInventoryClientError extends Error {
  constructor(
    message: string,
    public readonly status: number | undefined,
    public readonly code: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "LiveDashboardInventoryClientError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown, field: string): string {
  if (typeof value !== "string") {
    throw new LiveDashboardInventoryClientError(`${field} is invalid.`, undefined, "contract");
  }
  return value;
}

function numberValue(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new LiveDashboardInventoryClientError(`${field} is invalid.`, undefined, "contract");
  }
  return value;
}

function booleanValue(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") {
    throw new LiveDashboardInventoryClientError(`${field} is invalid.`, undefined, "contract");
  }
  return value;
}

function qualityValue(value: unknown): TelemetryQuality {
  if (
    value === "valid" ||
    value === "sensor_error" ||
    value === "communication_error" ||
    value === "unknown"
  ) {
    return value;
  }
  throw new LiveDashboardInventoryClientError("Inventory quality is invalid.", undefined, "contract");
}

function alarmValue(value: unknown): TelemetryAlarm | null {
  if (value === null || value === "low" || value === "high") return value;
  throw new LiveDashboardInventoryClientError("Inventory alarm is invalid.", undefined, "contract");
}

function nullableNumber(value: unknown, field: string): number | null {
  if (value === null) return null;
  return numberValue(value, field);
}

function inventoryKey(channelId: string, metric: string): string {
  return `${encodeURIComponent(channelId)}|${encodeURIComponent(metric)}`;
}

function parseLatest(value: unknown): TelemetrySample | null {
  if (value === null) return null;
  if (!isRecord(value)) {
    throw new LiveDashboardInventoryClientError("Inventory latest sample is invalid.", undefined, "contract");
  }
  return {
    event_id: stringValue(value.event_id, "Inventory latest event id"),
    node_id: stringValue(value.node_id, "Inventory latest node"),
    equipment_id: stringValue(value.equipment_id, "Inventory latest equipment"),
    channel_id: stringValue(value.channel_id, "Inventory latest channel"),
    captured_at: stringValue(value.captured_at, "Inventory latest captured timestamp"),
    metric: stringValue(value.metric, "Inventory latest metric"),
    value: nullableNumber(value.value, "Inventory latest value"),
    unit: stringValue(value.unit, "Inventory latest unit"),
    quality: qualityValue(value.quality),
    source: stringValue(value.source, "Inventory latest source"),
    alarm: alarmValue(value.alarm),
    raw_value: nullableNumber(value.raw_value, "Inventory latest raw value"),
    raw_status: nullableNumber(value.raw_status, "Inventory latest raw status"),
    received_at: stringValue(value.received_at, "Inventory latest received timestamp"),
  };
}

function parseItem(value: unknown): LiveDashboardInventoryItem {
  if (!isRecord(value)) {
    throw new LiveDashboardInventoryClientError("Inventory item is invalid.", undefined, "contract");
  }
  const channelId = stringValue(value.channel_id, "Inventory channel id");
  const metric = stringValue(value.metric, "Inventory metric");
  return {
    key: inventoryKey(channelId, metric),
    channel_ref_id: stringValue(value.channel_ref_id, "Inventory channel reference"),
    node_id: stringValue(value.node_id, "Inventory node"),
    equipment_id: stringValue(value.equipment_id, "Inventory equipment"),
    equipment_name: stringValue(value.equipment_name, "Inventory equipment name"),
    channel_id: channelId,
    channel_name: stringValue(value.channel_name, "Inventory channel name"),
    metric,
    native_unit: stringValue(value.native_unit, "Inventory native unit"),
    source: stringValue(value.source, "Inventory source"),
    quality: qualityValue(value.quality),
    alarm: alarmValue(value.alarm),
    latest: parseLatest(value.latest),
  };
}

export function parseLiveDashboardInventoryCollection(value: unknown): LiveDashboardInventoryCollection {
  if (!isRecord(value) || !Array.isArray(value.items)) {
    throw new LiveDashboardInventoryClientError("Inventory collection is invalid.", undefined, "contract");
  }
  return {
    items: value.items.map(parseItem),
    total: numberValue(value.total, "Inventory total"),
    limit: numberValue(value.limit, "Inventory limit"),
    offset: numberValue(value.offset, "Inventory offset"),
    has_more: booleanValue(value.has_more, "Inventory pagination"),
  };
}

function errorDetail(body: unknown, fallback: string): { message: string; code: string } {
  const rawDetail = isRecord(body) ? body.detail : null;
  const detail = isRecord(rawDetail) && isRecord(rawDetail.detail) ? rawDetail.detail : rawDetail;
  if (!isRecord(detail)) return { message: fallback, code: "http_error" };
  return {
    message: typeof detail.message === "string" ? detail.message : fallback,
    code: typeof detail.code === "string" ? detail.code : "http_error",
  };
}

export class LiveDashboardInventoryClient {
  private readonly fetchImpl: LiveDashboardInventoryFetch;
  private readonly timeoutMs: number;

  constructor(
    private readonly apiBaseUrl: string,
    options: LiveDashboardInventoryClientOptions = {},
  ) {
    this.fetchImpl = options.fetch ?? fetch.bind(globalThis);
    this.timeoutMs = options.timeoutMs ?? 8_000;
  }

  async list(
    query: LiveDashboardInventoryQuery = {},
    signal?: AbortSignal,
  ): Promise<LiveDashboardInventoryCollection> {
    const params = new URLSearchParams({
      limit: String(query.limit ?? 500),
      offset: String(query.offset ?? 0),
    });
    const controller = new AbortController();
    let timedOut = false;
    const onAbort = () => controller.abort(signal?.reason);
    if (signal?.aborted) onAbort();
    else signal?.addEventListener("abort", onAbort, { once: true });
    const timer = globalThis.setTimeout(() => {
      timedOut = true;
      controller.abort(new DOMException("Request timed out", "TimeoutError"));
    }, this.timeoutMs);

    let response: Response;
    try {
      response = await this.fetchImpl(
        `${this.apiBaseUrl}/api/v1/live-dashboards/channel-inventory?${params.toString()}`,
        {
          headers: { Accept: "application/json" },
          signal: controller.signal,
        },
      );
    } catch (error) {
      const code = timedOut ? "timeout" : controller.signal.aborted ? "aborted" : "network";
      throw new LiveDashboardInventoryClientError(
        timedOut
          ? `Live Dashboard inventory request exceeded ${this.timeoutMs} ms.`
          : controller.signal.aborted
            ? "Live Dashboard inventory request was aborted."
            : "Live Dashboard inventory request failed.",
        undefined,
        code,
        { cause: error },
      );
    } finally {
      globalThis.clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
    }

    let body: unknown = null;
    const text = await response.text();
    if (text) {
      try {
        body = JSON.parse(text) as unknown;
      } catch (error) {
        if (response.ok) {
          throw new LiveDashboardInventoryClientError(
            "Live Dashboard inventory returned invalid JSON.",
            response.status,
            "contract",
            { cause: error },
          );
        }
      }
    }
    if (!response.ok) {
      const detail = errorDetail(body, `Live Dashboard inventory returned HTTP ${response.status}.`);
      throw new LiveDashboardInventoryClientError(detail.message, response.status, detail.code);
    }
    return parseLiveDashboardInventoryCollection(body);
  }
}

export function createLiveDashboardInventoryClient(
  organizationId: string | null,
  options: LiveDashboardInventoryClientOptions = {},
): LiveDashboardInventoryClient {
  const config = getTelemetryRuntimeConfig();
  if (config.mode !== "live" || !config.apiBaseUrl) {
    throw new LiveDashboardInventoryClientError(
      "Live Dashboard inventory requires configured live mode.",
      undefined,
      "configuration",
    );
  }
  const fetchImpl = options.fetch ?? fetch.bind(globalThis);
  return new LiveDashboardInventoryClient(config.apiBaseUrl, {
    ...options,
    fetch: createAuthenticatedFetch(
      fetchImpl as typeof fetch,
      createRuntimeCredentialProvider(config.apiBaseUrl, organizationId),
    ),
  });
}
