import { createRuntimeCredentialProvider } from "@/features/security/auth-runtime";
import { createAuthenticatedFetch } from "@/features/security/security-session";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";

import { liveDashboardEtag } from "./model";
import type {
  LiveDashboard,
  LiveDashboardCollection,
  LiveDashboardItem,
  LiveDashboardStatus,
  LiveDashboardVersioned,
  LiveDashboardVisualization,
  LiveDashboardWrite,
} from "./types";

export type LiveDashboardFetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export interface LiveDashboardApiClientOptions {
  fetch?: LiveDashboardFetch;
  timeoutMs?: number;
}

export interface LiveDashboardListQuery {
  includeArchived?: boolean;
  limit?: number;
  offset?: number;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  ifMatch?: string;
  auditReason?: string;
  signal?: AbortSignal;
}

export class LiveDashboardClientError extends Error {
  constructor(
    message: string,
    public readonly status: number | undefined,
    public readonly code: string,
    public readonly expectedVersion: number | null = null,
    public readonly actualVersion: number | null = null,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "LiveDashboardClientError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown, field: string): string {
  if (typeof value !== "string") throw new LiveDashboardClientError(`${field} is invalid.`, undefined, "contract");
  return value;
}

function nullableString(value: unknown, field: string): string | null {
  if (value === null) return null;
  return stringValue(value, field);
}

function numberValue(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new LiveDashboardClientError(`${field} is invalid.`, undefined, "contract");
  }
  return value;
}

function booleanValue(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") throw new LiveDashboardClientError(`${field} is invalid.`, undefined, "contract");
  return value;
}

function visualizationValue(value: unknown): LiveDashboardVisualization {
  if (value === "line" || value === "area" || value === "gauge" || value === "value") return value;
  throw new LiveDashboardClientError("Dashboard visualization is invalid.", undefined, "contract");
}

function statusValue(value: unknown): LiveDashboardStatus {
  if (value === "active" || value === "archived") return value;
  throw new LiveDashboardClientError("Dashboard status is invalid.", undefined, "contract");
}

function parseItem(value: unknown): LiveDashboardItem {
  if (!isRecord(value)) throw new LiveDashboardClientError("Dashboard item is invalid.", undefined, "contract");
  return {
    id: stringValue(value.id, "Dashboard item id"),
    position: numberValue(value.position, "Dashboard item position"),
    channel_ref_id: stringValue(value.channel_ref_id, "Dashboard channel reference"),
    channel_id: stringValue(value.channel_id, "Dashboard channel id"),
    metric: stringValue(value.metric, "Dashboard metric"),
    native_unit: stringValue(value.native_unit, "Dashboard native unit"),
    visualization: visualizationValue(value.visualization),
    color: nullableString(value.color, "Dashboard color"),
    display_unit: nullableString(value.display_unit, "Dashboard display unit"),
  };
}

export function parseLiveDashboard(value: unknown): LiveDashboard {
  if (!isRecord(value)) throw new LiveDashboardClientError("Dashboard response is invalid.", undefined, "contract");
  if (!Array.isArray(value.items)) {
    throw new LiveDashboardClientError("Dashboard items are invalid.", undefined, "contract");
  }
  const refreshSeconds = numberValue(value.refresh_seconds, "Dashboard refresh preference");
  if (![1, 2, 5, 10, 15, 30, 60].includes(refreshSeconds)) {
    throw new LiveDashboardClientError("Dashboard refresh preference is unsupported.", undefined, "contract");
  }
  const timeWindow = stringValue(value.time_window, "Dashboard time window");
  if (!["5m", "15m", "30m", "1h", "6h", "12h", "24h", "7d"].includes(timeWindow)) {
    throw new LiveDashboardClientError("Dashboard time window is unsupported.", undefined, "contract");
  }
  return {
    id: stringValue(value.id, "Dashboard id"),
    organization_id: stringValue(value.organization_id, "Dashboard organization"),
    name: stringValue(value.name, "Dashboard name"),
    description: nullableString(value.description, "Dashboard description"),
    owner_subject: stringValue(value.owner_subject, "Dashboard owner"),
    refresh_seconds: refreshSeconds as LiveDashboard["refresh_seconds"],
    time_window: timeWindow as LiveDashboard["time_window"],
    version: numberValue(value.version, "Dashboard version"),
    status: statusValue(value.status),
    created_by: stringValue(value.created_by, "Dashboard creator"),
    updated_by: stringValue(value.updated_by, "Dashboard updater"),
    created_at: stringValue(value.created_at, "Dashboard created timestamp"),
    updated_at: stringValue(value.updated_at, "Dashboard updated timestamp"),
    archived_by: nullableString(value.archived_by, "Dashboard archiver"),
    archived_at: nullableString(value.archived_at, "Dashboard archived timestamp"),
    items: value.items.map(parseItem),
  };
}

function parseCollection(value: unknown): LiveDashboardCollection {
  if (!isRecord(value) || !Array.isArray(value.items)) {
    throw new LiveDashboardClientError("Dashboard collection is invalid.", undefined, "contract");
  }
  return {
    items: value.items.map(parseLiveDashboard),
    total: numberValue(value.total, "Dashboard collection total"),
    limit: numberValue(value.limit, "Dashboard collection limit"),
    offset: numberValue(value.offset, "Dashboard collection offset"),
    has_more: booleanValue(value.has_more, "Dashboard collection pagination"),
  };
}

function withQuery(path: string, query: LiveDashboardListQuery): string {
  const params = new URLSearchParams();
  params.set("include_archived", String(Boolean(query.includeArchived)));
  params.set("limit", String(query.limit ?? 100));
  params.set("offset", String(query.offset ?? 0));
  return `${path}?${params.toString()}`;
}

function errorDetail(body: unknown, fallback: string): {
  message: string;
  code: string;
  expectedVersion: number | null;
  actualVersion: number | null;
} {
  const rawDetail = isRecord(body) ? body.detail : null;
  const detail = isRecord(rawDetail) && isRecord(rawDetail.detail) ? rawDetail.detail : rawDetail;
  if (!isRecord(detail)) {
    return { message: fallback, code: "http_error", expectedVersion: null, actualVersion: null };
  }
  return {
    message: typeof detail.message === "string" ? detail.message : fallback,
    code: typeof detail.code === "string" ? detail.code : "http_error",
    expectedVersion: typeof detail.expected_version === "number" ? detail.expected_version : null,
    actualVersion: typeof detail.actual_version === "number" ? detail.actual_version : null,
  };
}

export class LiveDashboardApiClient {
  private readonly fetchImpl: LiveDashboardFetch;
  private readonly timeoutMs: number;

  constructor(
    private readonly apiBaseUrl: string,
    options: LiveDashboardApiClientOptions = {},
  ) {
    this.fetchImpl = options.fetch ?? fetch.bind(globalThis);
    this.timeoutMs = options.timeoutMs ?? 10_000;
  }

  async list(query: LiveDashboardListQuery = {}, signal?: AbortSignal): Promise<LiveDashboardCollection> {
    const { body } = await this.request(withQuery("/api/v1/live-dashboards", query), { signal });
    return parseCollection(body);
  }

  async get(dashboardId: string, signal?: AbortSignal): Promise<LiveDashboardVersioned> {
    const { body, response } = await this.request(
      `/api/v1/live-dashboards/${encodeURIComponent(dashboardId)}`,
      { signal },
    );
    const value = parseLiveDashboard(body);
    return { value, etag: response.headers.get("ETag") ?? liveDashboardEtag(value.version) };
  }

  async create(
    payload: LiveDashboardWrite,
    auditReason = "Create Live Dashboard",
    signal?: AbortSignal,
  ): Promise<LiveDashboardVersioned> {
    const { body, response } = await this.request("/api/v1/live-dashboards", {
      method: "POST",
      body: payload,
      auditReason,
      signal,
    });
    const value = parseLiveDashboard(body);
    return { value, etag: response.headers.get("ETag") ?? liveDashboardEtag(value.version) };
  }

  async update(
    dashboardId: string,
    payload: LiveDashboardWrite,
    etag: string,
    auditReason = "Update Live Dashboard",
    signal?: AbortSignal,
  ): Promise<LiveDashboardVersioned> {
    const { body, response } = await this.request(
      `/api/v1/live-dashboards/${encodeURIComponent(dashboardId)}`,
      { method: "PUT", body: payload, ifMatch: etag, auditReason, signal },
    );
    const value = parseLiveDashboard(body);
    return { value, etag: response.headers.get("ETag") ?? liveDashboardEtag(value.version) };
  }

  async archive(
    dashboardId: string,
    etag: string,
    auditReason = "Archive Live Dashboard",
    signal?: AbortSignal,
  ): Promise<string> {
    const { response } = await this.request(`/api/v1/live-dashboards/${encodeURIComponent(dashboardId)}`, {
      method: "DELETE",
      ifMatch: etag,
      auditReason,
      signal,
    });
    return response.headers.get("ETag") ?? etag;
  }

  private async request(
    path: string,
    options: RequestOptions,
  ): Promise<{ body: unknown; response: Response }> {
    const controller = new AbortController();
    let timedOut = false;
    const onAbort = () => controller.abort(options.signal?.reason);
    if (options.signal?.aborted) onAbort();
    else options.signal?.addEventListener("abort", onAbort, { once: true });
    const timer = globalThis.setTimeout(() => {
      timedOut = true;
      controller.abort(new DOMException("Request timed out", "TimeoutError"));
    }, this.timeoutMs);

    let response: Response;
    try {
      response = await this.fetchImpl(`${this.apiBaseUrl}${path}`, {
        method: options.method ?? "GET",
        headers: {
          Accept: "application/json",
          ...(options.body === undefined ? {} : { "Content-Type": "application/json" }),
          ...(options.ifMatch ? { "If-Match": options.ifMatch } : {}),
          ...(options.auditReason ? { "X-Audit-Reason": options.auditReason } : {}),
        },
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: controller.signal,
      });
    } catch (error) {
      const code = timedOut ? "timeout" : controller.signal.aborted ? "aborted" : "network";
      throw new LiveDashboardClientError(
        timedOut
          ? `Live Dashboard API request exceeded ${this.timeoutMs} ms.`
          : controller.signal.aborted
            ? "Live Dashboard API request was aborted."
            : "Live Dashboard API request failed.",
        undefined,
        code,
        null,
        null,
        { cause: error },
      );
    } finally {
      globalThis.clearTimeout(timer);
      options.signal?.removeEventListener("abort", onAbort);
    }

    let body: unknown = null;
    const text = await response.text();
    if (text) {
      try {
        body = JSON.parse(text) as unknown;
      } catch (error) {
        if (response.ok) {
          throw new LiveDashboardClientError(
            "Live Dashboard API returned invalid JSON.",
            response.status,
            "contract",
            null,
            null,
            { cause: error },
          );
        }
      }
    }

    if (!response.ok) {
      const detail = errorDetail(body, `Live Dashboard API returned HTTP ${response.status}.`);
      throw new LiveDashboardClientError(
        detail.message,
        response.status,
        detail.code,
        detail.expectedVersion,
        detail.actualVersion,
      );
    }
    return { body, response };
  }
}

export function createLiveDashboardApiClient(
  organizationId: string | null,
  options: LiveDashboardApiClientOptions = {},
): LiveDashboardApiClient {
  const config = getTelemetryRuntimeConfig();
  if (config.mode !== "live" || !config.apiBaseUrl) {
    throw new LiveDashboardClientError(
      "Live Dashboard API is available only in configured live mode.",
      undefined,
      "configuration",
    );
  }
  const fetchImpl = options.fetch ?? fetch.bind(globalThis);
  return new LiveDashboardApiClient(config.apiBaseUrl, {
    ...options,
    fetch: createAuthenticatedFetch(
      fetchImpl as typeof fetch,
      createRuntimeCredentialProvider(config.apiBaseUrl, organizationId),
    ),
  });
}
