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
import { TelemetryWebSocketClient, type TelemetryWebSocketClientOptions } from "./websocket-client";

export interface CreateTelemetryAdapterOptions {
  demoSamples?: TelemetrySample[];
  demoReadiness?: TelemetryReadinessResponse;
  rest?: TelemetryRestClientOptions;
  websocket?: TelemetryWebSocketClientOptions;
}

export function createTelemetryAdapter(
  config: TelemetryRuntimeConfig,
  options: CreateTelemetryAdapterOptions = {},
): TelemetryAdapter {
  if (config.mode === "demo") {
    return new DemoTelemetryAdapter(options.demoSamples, options.demoReadiness);
  }

  if (!config.apiBaseUrl || !config.websocketUrl) {
    throw new TelemetryClientError("configuration", "Live telemetry mode requires REST and WebSocket URLs");
  }

  return new LiveTelemetryAdapter(
    new TelemetryRestClient(config.apiBaseUrl, options.rest),
    new TelemetryWebSocketClient(config.websocketUrl, options.websocket),
  );
}
