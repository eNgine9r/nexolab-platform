import {
  parseTelemetryCollection,
  parseTelemetryReadiness,
} from "./contract";
import { TelemetryClientError, asTelemetryError } from "./errors";
import type {
  TelemetryCollectionResponse,
  TelemetryFilters,
  TelemetryHistoryQuery,
  TelemetryPageQuery,
  TelemetryReadinessResponse,
} from "./types";

export type TelemetryFetch = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export interface TelemetryRestClientOptions {
  fetch?: TelemetryFetch;
  timeoutMs?: number;
}

interface ManagedSignal {
  signal: AbortSignal;
  cleanup: () => void;
  didTimeout: () => boolean;
}

function createManagedSignal(
  externalSignal: AbortSignal | undefined,
  timeoutMs: number,
): ManagedSignal {
  const controller = new AbortController();
  let timedOut = false;

  const onAbort = () => controller.abort(externalSignal?.reason);
  if (externalSignal?.aborted) {
    onAbort();
  } else {
    externalSignal?.addEventListener("abort", onAbort, { once: true });
  }

  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort(new DOMException("Request timed out", "TimeoutError"));
  }, timeoutMs);

  return {
    signal: controller.signal,
    didTimeout: () => timedOut,
    cleanup: () => {
      window.clearTimeout(timer);
      externalSignal?.removeEventListener("abort", onAbort);
    },
  };
}

function appendFilters(
  params: URLSearchParams,
  filters: TelemetryFilters,
): void {
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined) {
      params.set(key, String(value));
    }
  }
}

function appendPage(
  params: URLSearchParams,
  query: TelemetryPageQuery,
): void {
  appendFilters(params, query);
  if (query.limit !== undefined) {
    params.set("limit", String(query.limit));
  }
  if (query.offset !== undefined) {
    params.set("offset", String(query.offset));
  }
}

function timestamp(value: Date | string): string {
  if (value instanceof Date) {
    return value.toISOString();
  }
  return value;
}

export class TelemetryRestClient {
  private readonly fetchImpl: TelemetryFetch;
  private readonly timeoutMs: number;

  constructor(
    private readonly apiBaseUrl: string,
    options: TelemetryRestClientOptions = {},
  ) {
    this.fetchImpl = options.fetch ?? fetch.bind(globalThis);
    this.timeoutMs = options.timeoutMs ?? 8_000;
  }

  readiness(signal?: AbortSignal): Promise<TelemetryReadinessResponse> {
    return this.request("/health/ready", parseTelemetryReadiness, signal);
  }

  latest(
    query: TelemetryPageQuery = {},
    signal?: AbortSignal,
  ): Promise<TelemetryCollectionResponse> {
    const params = new URLSearchParams();
    appendPage(params, query);
    return this.request(
      `/api/v1/telemetry/latest?${params.toString()}`,
      parseTelemetryCollection,
      signal,
    );
  }

  history(
    query: TelemetryHistoryQuery,
    signal?: AbortSignal,
  ): Promise<TelemetryCollectionResponse> {
    const params = new URLSearchParams();
    appendPage(params, query);
    params.set("from", timestamp(query.from));
    params.set("to", timestamp(query.to));
    return this.request(
      `/api/v1/telemetry/history?${params.toString()}`,
      parseTelemetryCollection,
      signal,
    );
  }

  private async request<T>(
    path: string,
    parser: (value: unknown) => T,
    externalSignal?: AbortSignal,
  ): Promise<T> {
    const managed = createManagedSignal(externalSignal, this.timeoutMs);
    let response: Response;

    try {
      response = await this.fetchImpl(`${this.apiBaseUrl}${path}`, {
        method: "GET",
        headers: { Accept: "application/json" },
        signal: managed.signal,
      });
    } catch (error) {
      if (managed.signal.aborted) {
        throw new TelemetryClientError(
          managed.didTimeout() ? "timeout" : "aborted",
          managed.didTimeout()
            ? `Telemetry request exceeded ${this.timeoutMs} ms`
            : "Telemetry request was aborted",
          { cause: error },
        );
      }
      throw asTelemetryError(error, "Telemetry request failed");
    } finally {
      managed.cleanup();
    }

    if (!response.ok) {
      const detail = await response.text().catch(() => "");
      throw new TelemetryClientError(
        "http",
        `Telemetry service returned ${response.status}${detail ? `: ${detail}` : ""}`,
        { status: response.status },
      );
    }

    let body: unknown;
    try {
      body = await response.json();
    } catch (error) {
      throw new TelemetryClientError(
        "contract",
        "Telemetry service returned invalid JSON",
        { cause: error },
      );
    }

    return parser(body);
  }
}
