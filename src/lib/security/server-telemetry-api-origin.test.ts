import { describe, expect, it } from "vitest";

import { getServerTelemetryApiBaseUrl } from "./server-telemetry-api-origin";

describe("NEXOLAB private server-side telemetry API origin", () => {
  const external = {
    NEXOLAB_EXTERNAL_HTTPS_STAGE: "true",
    NEXT_PUBLIC_NEXOLAB_API_BASE_URL: "https://nexolab-edge-01.example.ts.net",
  };

  it("preserves the trusted LAN implementation if external staging is not enabled", () => {
    expect(
      getServerTelemetryApiBaseUrl({
        NEXT_PUBLIC_NEXOLAB_API_BASE_URL: "http://172.18.48.66:8082",
      }).origin,
    ).toBe("http://172.18.48.66:8082");
  });

  it("uses private Telemetry API rather than public Funnel host", () => {
    expect(
      getServerTelemetryApiBaseUrl({
        ...external,
        NEXOLAB_SERVER_API_BASE_URL: "http://172.18.48.66:8082",
      }).origin,
    ).toBe("http://172.18.48.66:8082");
  });

  it("fails closed if stage is enabled without a private backend", () => {
    expect(() => getServerTelemetryApiBaseUrl(external)).toThrow("private server-only");
  });

  it.each([
    "https://172.18.48.66:8082",
    "http://127.0.0.1:3000",
    "http://0.0.0.0:8082",
    "http://8.8.8.8:8082",
    "http://169.254.1.10:8082",
    "http://example.com:8082",
    "http://user:secret@172.18.48.66:8082",
    "http://172.18.48.66:8082/?token=abc",
    "http://172.18.48.66:8082/other",
  ])("refuses unsafe private origin %s", (origin) => {
    expect(() =>
      getServerTelemetryApiBaseUrl({
        ...external,
        NEXOLAB_SERVER_API_BASE_URL: origin,
      }),
    ).toThrow("private server API must use");
  });

  it("accepts loopback API on the expected backend port", () => {
    expect(
      getServerTelemetryApiBaseUrl({
        ...external,
        NEXOLAB_SERVER_API_BASE_URL: "http://127.0.0.1:8082",
      }).origin,
    ).toBe("http://127.0.0.1:8082");
  });
});
