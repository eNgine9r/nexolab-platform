import { describe, expect, it } from "vitest";

import { validateTelemetryRuntimeConfig } from "./runtime-config";

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
