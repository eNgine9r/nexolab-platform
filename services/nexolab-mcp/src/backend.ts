import { createBackendAccessTokenProvider, type AuthFetch, type BackendAccessTokenProvider } from "./auth.js";
import type { McpConfig } from "./config.js";

export type JsonObject = Record<string, unknown>;

export type TelemetryFilters = {
  nodeId?: string;
  equipmentId?: string;
  channelId?: string;
  metric?: string;
  quality?: "valid" | "sensor_error" | "communication_error" | "unknown";
  alarm?: "low" | "high";
};

export type TelemetryCollection = {
  items: JsonObject[];
  count: number;
  limit: number;
  offset: number;
  nextOffset: number | null;
  snapshotAt: string | null;
};

export class BackendError extends Error {
  constructor(
    message: string,
    readonly code: "network" | "timeout" | "http" | "contract",
    readonly status?: number,
  ) {
    super(message);
    this.name = "BackendError";
  }
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function finiteNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function parseCollection(value: unknown): TelemetryCollection {
  if (!isObject(value) || !Array.isArray(value.items) || !value.items.every(isObject)) {
    throw new BackendError("Telemetry API returned an invalid collection.", "contract");
  }
  return {
    items: value.items,
    count: finiteNumber(value.count, value.items.length),
    limit: finiteNumber(value.limit, value.items.length),
    offset: finiteNumber(value.offset, 0),
    nextOffset: typeof value.next_offset === "number" ? value.next_offset : null,
    snapshotAt: typeof value.snapshot_at === "string" ? value.snapshot_at : null,
  };
}

function appendFilters(params: URLSearchParams, filters: TelemetryFilters): void {
  if (filters.nodeId) params.set("node_id", filters.nodeId);
  if (filters.equipmentId) params.set("equipment_id", filters.equipmentId);
  if (filters.channelId) params.set("channel_id", filters.channelId);
  if (filters.metric) params.set("metric", filters.metric);
  if (filters.quality) params.set("quality", filters.quality);
  if (filters.alarm) params.set("alarm", filters.alarm);
}

export type NexoLabBackendOptions = {
  fetch?: AuthFetch;
  accessTokenProvider?: BackendAccessTokenProvider;
};

export class NexoLabBackend {
  private readonly fetchImpl: AuthFetch;
  private readonly accessTokenProvider: BackendAccessTokenProvider;

  constructor(
    private readonly config: McpConfig,
    options: NexoLabBackendOptions = {},
  ) {
    this.fetchImpl = options.fetch ?? fetch.bind(globalThis);
    this.accessTokenProvider =
      options.accessTokenProvider ??
      createBackendAccessTokenProvider(config.backendAuth, config.telemetryApiUrl, config.requestTimeoutMs);
  }

  telemetryReadiness(): Promise<JsonObject> {
    return this.requestObject(this.config.telemetryApiUrl, "/health/ready");
  }

  async latestTelemetry(filters: TelemetryFilters, limit: number): Promise<TelemetryCollection> {
    const params = new URLSearchParams({ limit: String(limit), offset: "0" });
    appendFilters(params, filters);
    return parseCollection(
      await this.requestJson(this.config.telemetryApiUrl, `/api/v1/telemetry/latest?${params.toString()}`),
    );
  }

  async telemetryHistory(
    filters: TelemetryFilters,
    from: string,
    to: string,
    limit: number,
  ): Promise<TelemetryCollection> {
    const params = new URLSearchParams({ from, to, limit: String(limit), offset: "0" });
    appendFilters(params, filters);
    return parseCollection(
      await this.requestJson(this.config.telemetryApiUrl, `/api/v1/telemetry/history?${params.toString()}`),
    );
  }

  async listNodes(limit: number): Promise<JsonObject[]> {
    const value = await this.requestJson(this.config.nodesApiUrl, "/api/v1/nodes");
    if (!Array.isArray(value) || !value.every(isObject)) {
      throw new BackendError("Nodes API returned an invalid list.", "contract");
    }
    return value.slice(0, limit);
  }

  nodeOperationalState(nodeId: string): Promise<JsonObject> {
    return this.requestObject(
      this.config.nodesApiUrl,
      `/api/v1/nodes/${encodeURIComponent(nodeId)}/operational-state`,
    );
  }

  async nodeHealthHistory(nodeId: string, limit: number): Promise<JsonObject[]> {
    return this.requestObjectArray(
      this.config.nodesApiUrl,
      `/api/v1/nodes/${encodeURIComponent(nodeId)}/health-history?limit=${limit}`,
    );
  }

  async nodeStatusHistory(nodeId: string, limit: number): Promise<JsonObject[]> {
    return this.requestObjectArray(
      this.config.nodesApiUrl,
      `/api/v1/nodes/${encodeURIComponent(nodeId)}/status-history?limit=${limit}`,
    );
  }

  private async requestObjectArray(baseUrl: string, path: string): Promise<JsonObject[]> {
    const value = await this.requestJson(baseUrl, path);
    if (!Array.isArray(value) || !value.every(isObject)) {
      throw new BackendError("NEXOLAB API returned an invalid array.", "contract");
    }
    return value;
  }

  private async requestObject(baseUrl: string, path: string): Promise<JsonObject> {
    const value = await this.requestJson(baseUrl, path);
    if (!isObject(value)) {
      throw new BackendError("NEXOLAB API returned an invalid object.", "contract");
    }
    return value;
  }

  private async requestJson(baseUrl: string, path: string): Promise<unknown> {
    let response = await this.performGet(baseUrl, path);
    if (response.status === 401 && this.accessTokenProvider.refreshable) {
      this.accessTokenProvider.invalidate();
      response = await this.performGet(baseUrl, path);
    }
    if (!response.ok) {
      throw new BackendError(`NEXOLAB API returned HTTP ${response.status}.`, "http", response.status);
    }
    try {
      return (await response.json()) as unknown;
    } catch {
      throw new BackendError("NEXOLAB API returned invalid JSON.", "contract", response.status);
    }
  }

  private async performGet(baseUrl: string, path: string): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(
      () => controller.abort(new DOMException("Request timed out", "TimeoutError")),
      this.config.requestTimeoutMs,
    );
    try {
      const accessToken = await this.accessTokenProvider.getAccessToken();
      return await this.fetchImpl(`${baseUrl}${path}`, {
        method: "GET",
        headers: {
          Accept: "application/json",
          "X-Organization-ID": this.config.organizationId,
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
        signal: controller.signal,
      });
    } catch (error) {
      if (error instanceof BackendError) throw error;
      if (controller.signal.aborted) {
        throw new BackendError(
          `NEXOLAB API request exceeded ${this.config.requestTimeoutMs} ms.`,
          "timeout",
        );
      }
      throw new BackendError(
        error instanceof Error ? error.message : "NEXOLAB API request failed.",
        "network",
      );
    } finally {
      clearTimeout(timer);
    }
  }
}
