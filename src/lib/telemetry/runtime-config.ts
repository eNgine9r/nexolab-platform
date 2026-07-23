import { TelemetryClientError } from "./errors";
import type { TelemetryMode, TelemetryRuntimeConfig } from "./types";

export interface TelemetryRuntimeConfigInput {
  mode?: string;
  apiBaseUrl?: string;
  websocketUrl?: string;
}

function parseMode(value: string | undefined): TelemetryMode {
  const mode = value?.trim() || "demo";
  if (mode === "demo" || mode === "live") {
    return mode;
  }

  throw new TelemetryClientError(
    "configuration",
    `Unsupported telemetry mode: ${mode}`,
  );
}

function parseUrl(
  value: string | undefined,
  field: string,
  protocols: readonly string[],
): string {
  if (!value?.trim()) {
    throw new TelemetryClientError(
      "configuration",
      `${field} is required in live mode`,
    );
  }

  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch (error) {
    throw new TelemetryClientError(
      "configuration",
      `${field} must be an absolute URL`,
      { cause: error },
    );
  }

  if (!protocols.includes(parsed.protocol)) {
    throw new TelemetryClientError(
      "configuration",
      `${field} must use ${protocols.join(" or ")}`,
    );
  }

  parsed.hash = "";
  parsed.search = "";
  return parsed.toString().replace(/\/$/, "");
}

export function validateTelemetryRuntimeConfig(
  input: TelemetryRuntimeConfigInput,
): TelemetryRuntimeConfig {
  const mode = parseMode(input.mode);
  if (mode === "demo") {
    return Object.freeze({
      mode,
      apiBaseUrl: null,
      websocketUrl: null,
    });
  }

  return Object.freeze({
    mode,
    apiBaseUrl: parseUrl(input.apiBaseUrl, "Telemetry API URL", [
      "http:",
      "https:",
    ]),
    websocketUrl: parseUrl(input.websocketUrl, "Telemetry WebSocket URL", [
      "ws:",
      "wss:",
    ]),
  });
}

export function getTelemetryRuntimeConfig(): TelemetryRuntimeConfig {
  return validateTelemetryRuntimeConfig({
    mode: process.env.NEXT_PUBLIC_NEXOLAB_DATA_MODE,
    apiBaseUrl: process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL,
    websocketUrl: process.env.NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL,
  });
}
