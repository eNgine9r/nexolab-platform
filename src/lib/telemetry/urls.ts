import type { TelemetryFilters, TelemetryHistoryQuery, TelemetryPagination } from "./types";

const FILTER_KEYS = ["node_id", "equipment_id", "channel_id", "metric", "quality", "alarm"] as const;

export interface TelemetryEndpointConfig {
  apiBaseUrl: string;
  websocketUrl?: string;
  origin?: string;
}

function absoluteUrl(value: string, origin?: string): URL {
  try {
    return new URL(value);
  } catch {
    if (!origin) {
      throw new Error(`Relative telemetry URL requires a browser origin: ${value}`);
    }
    return new URL(value, origin);
  }
}

function appendPath(baseUrl: string, path: string, origin?: string): URL {
  const base = absoluteUrl(baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`, origin);
  return new URL(path.replace(/^\/+/, ""), base);
}

function appendFilters(url: URL, filters: TelemetryFilters): void {
  for (const key of FILTER_KEYS) {
    const value = filters[key];
    if (value !== undefined && value !== "") {
      url.searchParams.set(key, value);
    }
  }
}

function appendPagination(url: URL, pagination: TelemetryPagination): void {
  if (pagination.limit !== undefined) {
    url.searchParams.set("limit", String(pagination.limit));
  }
  if (pagination.offset !== undefined) {
    url.searchParams.set("offset", String(pagination.offset));
  }
}

export function buildLatestTelemetryUrl(
  config: TelemetryEndpointConfig,
  filters: TelemetryFilters = {},
  pagination: TelemetryPagination = {},
): string {
  const url = appendPath(config.apiBaseUrl, "/api/v1/telemetry/latest", config.origin);
  appendFilters(url, filters);
  appendPagination(url, pagination);
  return url.toString();
}

export function buildHistoryTelemetryUrl(
  config: TelemetryEndpointConfig,
  query: TelemetryHistoryQuery,
): string {
  const url = appendPath(config.apiBaseUrl, "/api/v1/telemetry/history", config.origin);
  appendFilters(url, query);
  appendPagination(url, query);
  url.searchParams.set("from", query.from);
  url.searchParams.set("to", query.to);
  return url.toString();
}

export function buildLiveTelemetryUrl(
  config: TelemetryEndpointConfig,
  filters: TelemetryFilters = {},
  after?: string,
): string {
  const url = config.websocketUrl
    ? absoluteUrl(config.websocketUrl, config.origin)
    : appendPath(config.apiBaseUrl, "/api/v1/telemetry/live", config.origin);

  if (url.protocol === "http:") url.protocol = "ws:";
  if (url.protocol === "https:") url.protocol = "wss:";
  if (url.protocol !== "ws:" && url.protocol !== "wss:") {
    throw new Error(`Unsupported telemetry WebSocket protocol: ${url.protocol}`);
  }

  appendFilters(url, filters);
  if (after) url.searchParams.set("after", after);
  return url.toString();
}
