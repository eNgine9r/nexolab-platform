import {
  createAuthenticatedFetch,
  createAuthenticatedWebSocketFactory,
  type AccessTokenProvider,
} from "@/features/auth/authenticated-transport";
import { readBrowserAccessToken } from "@/features/auth/auth-session";

import { DemoTelemetryAdapter } from "./demo-adapter";
import { TelemetryClientError } from "./errors";
import { LiveTelemetryAdapter } from "./live-adapter";
import { TelemetryRestClient, type TelemetryRestClientOptions } from "./rest-client";
import type {
  TelemetryAdapter,
  TelemetryReadinessResponse,
  TelemetryRuntimeConfig,
  TelemetrySample,
} from "./types";
import {
  TelemetryWebSocketClient,
  type TelemetryWebSocketClientOptions,
} from "./websocket-client";

export interface CreateTelemetryAdapterOptions {
  demoSamples?: TelemetrySample[];
  demoReadiness?: TelemetryReadinessResponse;
  rest?: TelemetryRestClientOptions;
  websocket?: TelemetryWebSocketClientOptions;
  getAccessToken?: AccessTokenProvider;
}

export function createTelemetryAdapter(
  config: TelemetryRuntimeConfig,
  options: CreateTelemetryAdapterOptions = {},
): TelemetryAdapter {
  if (config.mode === "demo") {
    return new DemoTelemetryAdapter(options.demoSamples, options.demoReadiness);
  }

  if (!config.apiBaseUrl || !config.websocketUrl) {
    throw new TelemetryClientError(
      "configuration",
      "Live telemetry mode requires REST and WebSocket URLs",
    );
  }

  const getAccessToken = options.getAccessToken ?? readBrowserAccessToken;
  const restOptions: TelemetryRestClientOptions = {
    ...options.rest,
    fetch:
      options.rest?.fetch ??
      createAuthenticatedFetch(getAccessToken, fetch.bind(globalThis)),
  };
  const websocketOptions: TelemetryWebSocketClientOptions = {
    ...options.websocket,
    createSocket:
      options.websocket?.createSocket ?? createAuthenticatedWebSocketFactory(getAccessToken),
  };

  return new LiveTelemetryAdapter(
    new TelemetryRestClient(config.apiBaseUrl, restOptions),
    new TelemetryWebSocketClient(config.websocketUrl, websocketOptions),
  );
}
