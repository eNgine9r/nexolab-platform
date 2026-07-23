export type TelemetryDashboardMode = "demo" | "live";

export interface PublicTelemetryEnvironment {
  NEXT_PUBLIC_TELEMETRY_MODE?: string;
  NEXT_PUBLIC_TELEMETRY_API_BASE_URL?: string;
  NEXT_PUBLIC_TELEMETRY_WS_URL?: string;
  NEXT_PUBLIC_TELEMETRY_REQUEST_TIMEOUT_MS?: string;
  NEXT_PUBLIC_TELEMETRY_RECONNECT_MIN_MS?: string;
  NEXT_PUBLIC_TELEMETRY_RECONNECT_MAX_MS?: string;
  NEXT_PUBLIC_TELEMETRY_RECONNECT_JITTER_RATIO?: string;
}

export interface TelemetryClientConfig {
  mode: TelemetryDashboardMode;
  apiBaseUrl: string;
  websocketUrl?: string;
  requestTimeoutMs: number;
  reconnectMinMs: number;
  reconnectMaxMs: number;
  reconnectJitterRatio: number;
}

function positiveInteger(
  value: string | undefined,
  fallback: number,
  field: string,
): number {
  if (!value) return fallback;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${field} must be a positive integer`);
  }
  return parsed;
}

function boundedRatio(value: string | undefined, fallback: number): number {
  if (!value) return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0 || parsed > 1) {
    throw new Error(
      "NEXT_PUBLIC_TELEMETRY_RECONNECT_JITTER_RATIO must be between 0 and 1",
    );
  }
  return parsed;
}

export function publicTelemetryEnvironment(): PublicTelemetryEnvironment {
  return {
    NEXT_PUBLIC_TELEMETRY_MODE: process.env.NEXT_PUBLIC_TELEMETRY_MODE,
    NEXT_PUBLIC_TELEMETRY_API_BASE_URL:
      process.env.NEXT_PUBLIC_TELEMETRY_API_BASE_URL,
    NEXT_PUBLIC_TELEMETRY_WS_URL: process.env.NEXT_PUBLIC_TELEMETRY_WS_URL,
    NEXT_PUBLIC_TELEMETRY_REQUEST_TIMEOUT_MS:
      process.env.NEXT_PUBLIC_TELEMETRY_REQUEST_TIMEOUT_MS,
    NEXT_PUBLIC_TELEMETRY_RECONNECT_MIN_MS:
      process.env.NEXT_PUBLIC_TELEMETRY_RECONNECT_MIN_MS,
    NEXT_PUBLIC_TELEMETRY_RECONNECT_MAX_MS:
      process.env.NEXT_PUBLIC_TELEMETRY_RECONNECT_MAX_MS,
    NEXT_PUBLIC_TELEMETRY_RECONNECT_JITTER_RATIO:
      process.env.NEXT_PUBLIC_TELEMETRY_RECONNECT_JITTER_RATIO,
  };
}

export function resolveTelemetryClientConfig(
  environment: PublicTelemetryEnvironment = publicTelemetryEnvironment(),
): TelemetryClientConfig {
  const modeValue = environment.NEXT_PUBLIC_TELEMETRY_MODE?.trim() || "demo";
  if (modeValue !== "demo" && modeValue !== "live") {
    throw new Error("NEXT_PUBLIC_TELEMETRY_MODE must be demo or live");
  }

  const reconnectMinMs = positiveInteger(
    environment.NEXT_PUBLIC_TELEMETRY_RECONNECT_MIN_MS,
    1_000,
    "NEXT_PUBLIC_TELEMETRY_RECONNECT_MIN_MS",
  );
  const reconnectMaxMs = positiveInteger(
    environment.NEXT_PUBLIC_TELEMETRY_RECONNECT_MAX_MS,
    30_000,
    "NEXT_PUBLIC_TELEMETRY_RECONNECT_MAX_MS",
  );
  if (reconnectMaxMs < reconnectMinMs) {
    throw new Error(
      "NEXT_PUBLIC_TELEMETRY_RECONNECT_MAX_MS must be greater than or equal to the minimum",
    );
  }

  return {
    mode: modeValue,
    apiBaseUrl:
      environment.NEXT_PUBLIC_TELEMETRY_API_BASE_URL?.trim() ||
      "/telemetry-api",
    websocketUrl:
      environment.NEXT_PUBLIC_TELEMETRY_WS_URL?.trim() || undefined,
    requestTimeoutMs: positiveInteger(
      environment.NEXT_PUBLIC_TELEMETRY_REQUEST_TIMEOUT_MS,
      10_000,
      "NEXT_PUBLIC_TELEMETRY_REQUEST_TIMEOUT_MS",
    ),
    reconnectMinMs,
    reconnectMaxMs,
    reconnectJitterRatio: boundedRatio(
      environment.NEXT_PUBLIC_TELEMETRY_RECONNECT_JITTER_RATIO,
      0.2,
    ),
  };
}
