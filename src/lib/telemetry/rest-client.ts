import { parseTelemetryCollection } from "./runtime";
import type { TelemetryClientConfig } from "./config";
import type {
  TelemetryCollection,
  TelemetryFilters,
  TelemetryHistoryQuery,
  TelemetryPagination,
} from "./types";
import {
  buildHistoryTelemetryUrl,
  buildLatestTelemetryUrl,
  type TelemetryEndpointConfig,
} from "./urls";

export class TelemetryRequestError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "TelemetryRequestError";
  }
}

export interface TelemetryRestClientOptions {
  config: TelemetryClientConfig;
  origin?: string;
  fetchImpl?: typeof fetch;
}

function browserOrigin(): string | undefined {
  return typeof window === "undefined" ? undefined : window.location.origin;
}

export class TelemetryRestClient {
  private readonly endpoints: TelemetryEndpointConfig;
  private readonly requestTimeoutMs: number;
  private readonly fetchImpl: typeof fetch;

  constructor(options: TelemetryRestClientOptions) {
    this.endpoints = {
      apiBaseUrl: options.config.apiBaseUrl,
      websocketUrl: options.config.websocketUrl,
      origin: options.origin ?? browserOrigin(),
    };
    this.requestTimeoutMs = options.config.requestTimeoutMs;
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  async latest(
    filters: TelemetryFilters = {},
    pagination: TelemetryPagination = {},
  ): Promise<TelemetryCollection> {
    return this.request(
      buildLatestTelemetryUrl(this.endpoints, filters, pagination),
    );
  }

  async history(query: TelemetryHistoryQuery): Promise<TelemetryCollection> {
    return this.request(buildHistoryTelemetryUrl(this.endpoints, query));
  }

  private async request(url: string): Promise<TelemetryCollection> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.requestTimeoutMs);

    try {
      const response = await this.fetchImpl(url, {
        method: "GET",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new TelemetryRequestError(
          `Telemetry request failed with ${response.status}${detail ? `: ${detail}` : ""}`,
          response.status,
        );
      }

      let payload: unknown;
      try {
        payload = await response.json();
      } catch (error) {
        throw new TelemetryRequestError(
          `Telemetry response is not valid JSON: ${String(error)}`,
          response.status,
        );
      }
      return parseTelemetryCollection(payload);
    } catch (error) {
      if (error instanceof TelemetryRequestError) throw error;
      if (controller.signal.aborted) {
        throw new TelemetryRequestError(
          `Telemetry request timed out after ${this.requestTimeoutMs} ms`,
        );
      }
      throw new TelemetryRequestError(
        `Telemetry request failed: ${String(error)}`,
      );
    } finally {
      clearTimeout(timeout);
    }
  }
}
