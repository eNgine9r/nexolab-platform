import { createAuthenticatedFetch } from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";

import { AlertClientError, getAlertsApiBaseUrl } from "./runtime-config";
import type {
  AlertInstance,
  AlertLifecycleResponse,
  AlertPage,
  AlertSeverity,
  AlertState,
  AlertTransitionPage,
} from "./types";

export type AlertFetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export interface AlertApiClientOptions {
  fetch?: AlertFetch;
  timeoutMs?: number;
}

export interface AlertListQuery {
  state?: AlertState;
  severity?: AlertSeverity;
  metric?: string;
  limit?: number;
  offset?: number;
}

interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  idempotencyKey?: string;
  signal?: AbortSignal;
}

function withQuery(path: string, values: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined) params.set(key, String(value));
  }
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function assertObject<T>(value: unknown, label: string): T {
  if (!isRecord(value)) {
    throw new AlertClientError(`${label} returned an invalid object.`, undefined, "contract");
  }
  return value as T;
}

function errorDetail(body: unknown, fallback: string): { message: string; code?: string } {
  if (!isRecord(body)) return { message: fallback };
  const detail = body.detail;
  if (typeof detail === "string") return { message: detail };
  if (isRecord(detail)) {
    return {
      message: typeof detail.message === "string" ? detail.message : fallback,
      code: typeof detail.code === "string" ? detail.code : undefined,
    };
  }
  return { message: fallback };
}

export function createAlertIdempotencyKey(scope: string): string {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `nexolab-ui:alerts:${scope}:${random}`;
}

export class AlertApiClient {
  private readonly fetchImpl: AlertFetch;
  private readonly timeoutMs: number;

  constructor(
    private readonly apiBaseUrl: string,
    options: AlertApiClientOptions = {},
  ) {
    this.fetchImpl = options.fetch ?? fetch.bind(globalThis);
    this.timeoutMs = options.timeoutMs ?? 10_000;
  }

  listAlerts(query: AlertListQuery = {}, signal?: AbortSignal): Promise<AlertPage> {
    return this.request(
      withQuery("/api/v1/alerts", {
        state: query.state,
        severity: query.severity,
        metric: query.metric,
        limit: query.limit ?? 200,
        offset: query.offset ?? 0,
      }),
      { signal },
      (body) => assertObject<AlertPage>(body, "Alerts list"),
    );
  }

  getAlert(alertId: string, signal?: AbortSignal): Promise<AlertInstance> {
    return this.request(`/api/v1/alerts/${encodeURIComponent(alertId)}`, { signal }, (body) =>
      assertObject<AlertInstance>(body, "Alert detail"),
    );
  }

  listTransitions(alertId: string, signal?: AbortSignal): Promise<AlertTransitionPage> {
    return this.request(
      withQuery(`/api/v1/alerts/${encodeURIComponent(alertId)}/transitions`, { limit: 200, offset: 0 }),
      { signal },
      (body) => assertObject<AlertTransitionPage>(body, "Alert transitions"),
    );
  }

  acknowledge(
    alertId: string,
    reason: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<AlertLifecycleResponse> {
    return this.request(
      `/api/v1/alerts/${encodeURIComponent(alertId)}/acknowledge`,
      {
        method: "POST",
        body: { reason: reason.trim() || null, occurred_at: new Date().toISOString() },
        idempotencyKey,
        signal,
      },
      (body) => assertObject<AlertLifecycleResponse>(body, "Alert acknowledgement"),
    );
  }

  close(
    alertId: string,
    reason: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<AlertLifecycleResponse> {
    return this.request(
      `/api/v1/alerts/${encodeURIComponent(alertId)}/close`,
      {
        method: "POST",
        body: { reason: reason.trim() || null, occurred_at: new Date().toISOString() },
        idempotencyKey,
        signal,
      },
      (body) => assertObject<AlertLifecycleResponse>(body, "Alert close"),
    );
  }

  private async request<T>(path: string, options: RequestOptions, parser: (body: unknown) => T): Promise<T> {
    const controller = new AbortController();
    let timedOut = false;
    const onAbort = () => controller.abort(options.signal?.reason);
    if (options.signal?.aborted) onAbort();
    else options.signal?.addEventListener("abort", onAbort, { once: true });
    const timer = setTimeout(() => {
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
          ...(options.idempotencyKey ? { "Idempotency-Key": options.idempotencyKey } : {}),
        },
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: controller.signal,
      });
    } catch (error) {
      if (controller.signal.aborted) {
        throw new AlertClientError(
          timedOut ? `Alerts request exceeded ${this.timeoutMs} ms.` : "Alerts request was aborted.",
          undefined,
          timedOut ? "timeout" : "aborted",
          { cause: error },
        );
      }
      throw new AlertClientError("Alerts API request failed.", undefined, "network", { cause: error });
    } finally {
      clearTimeout(timer);
      options.signal?.removeEventListener("abort", onAbort);
    }

    let body: unknown = null;
    const text = await response.text();
    if (text) {
      try {
        body = JSON.parse(text) as unknown;
      } catch (error) {
        if (response.ok) {
          throw new AlertClientError("Alerts API returned invalid JSON.", response.status, "contract", {
            cause: error,
          });
        }
      }
    }

    if (!response.ok) {
      const fallback = `Alerts API returned HTTP ${response.status}.`;
      const detail = errorDetail(body, fallback);
      throw new AlertClientError(detail.message, response.status, detail.code);
    }
    return parser(body);
  }
}

export function createAlertApiClient(options: AlertApiClientOptions = {}): AlertApiClient {
  const fetchImpl = options.fetch ?? fetch.bind(globalThis);
  return new AlertApiClient(getAlertsApiBaseUrl(), {
    ...options,
    fetch: createAuthenticatedFetch(fetchImpl, createRuntimeCredentialProvider()),
  });
}
