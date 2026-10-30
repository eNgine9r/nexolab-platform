import { afterEach, describe, expect, it, vi } from "vitest";

import { getTelemetryRuntimeConfig, validateTelemetryRuntimeConfig } from "./runtime-config";

describe("offline Pi browser origin integration", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("uses the private Pi host for REST and WebSocket when explicitly opted in", () => {
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_DATA_MODE", "live");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_API_BASE_URL", "http://127.0.0.1:8082");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL", "ws://127.0.0.1:8082/api/v1/telemetry/live");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_OFFLINE_DUAL_ACCESS", "true");
    vi.stubGlobal("window", { location: { origin: "http://192.168.50.1:3000" } });

    expect(getTelemetryRuntimeConfig()).toEqual({
      mode: "live",
      apiBaseUrl: "http://192.168.50.1:8082",
      websocketUrl: "ws://192.168.50.1:8082/api/v1/telemetry/live",
    });
  });

  it("does not change the installed legacy origin when opt-in is absent", () => {
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_DATA_MODE", "live");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_API_BASE_URL", "http://127.0.0.1:8082");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL", "ws://127.0.0.1:8082/api/v1/telemetry/live");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_OFFLINE_DUAL_ACCESS", "");
    vi.stubGlobal("window", { location: { origin: "http://192.168.50.1:3000" } });

    expect(getTelemetryRuntimeConfig()).toEqual({
      mode: "live",
      apiBaseUrl: "http://127.0.0.1:8082",
      websocketUrl: "ws://127.0.0.1:8082/api/v1/telemetry/live",
    });
  });
});

describe("validateTelemetryRuntimeConfig", () => {
  it("defaults to isolated demo mode", () => {
    expect(validateTelemetryRuntimeConfig({})).toEqual({
      mode: "demo",
      apiBaseUrl: null,
      websocketUrl: null,
    });
  });

  it("normalizes valid live URLs", () => {
    expect(
      validateTelemetryRuntimeConfig({
        mode: "live",
        apiBaseUrl: "http://127.0.0.1:8082/",
        websocketUrl: "ws://127.0.0.1:8082/api/v1/telemetry/live?ignored=true",
      }),
    ).toEqual({
      mode: "live",
      apiBaseUrl: "http://127.0.0.1:8082",
      websocketUrl: "ws://127.0.0.1:8082/api/v1/telemetry/live",
    });
  });

  it.each([
    [{ mode: "automatic" }, "Unsupported telemetry mode"],
    [{ mode: "live" }, "Telemetry API URL is required"],
    [
      {
        mode: "live",
        apiBaseUrl: "ftp://central.example",
        websocketUrl: "wss://central.example/api/v1/telemetry/live",
      },
      "Telemetry API URL must use http: or https:",
    ],
    [
      {
        mode: "live",
        apiBaseUrl: "https://central.example",
        websocketUrl: "https://central.example/api/v1/telemetry/live",
      },
      "Telemetry WebSocket URL must use ws: or wss:",
    ],
  ])("rejects an invalid configuration", (input, message) => {
    expect(() => validateTelemetryRuntimeConfig(input)).toThrowError(
      expect.objectContaining({
        code: "configuration",
        message: expect.stringContaining(message),
      }),
    );
  });
});
