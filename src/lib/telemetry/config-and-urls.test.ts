import { resolveTelemetryClientConfig } from "./config";
import {
  buildHistoryTelemetryUrl,
  buildLatestTelemetryUrl,
  buildLiveTelemetryUrl,
} from "./urls";

describe("telemetry public configuration", () => {
  it("uses explicit demo mode and same-origin proxy defaults", () => {
    expect(resolveTelemetryClientConfig({})).toMatchObject({
      mode: "demo",
      apiBaseUrl: "/telemetry-api",
      websocketUrl: undefined,
      requestTimeoutMs: 10_000,
      reconnectMinMs: 1_000,
      reconnectMaxMs: 30_000,
    });
  });

  it("validates reconnect bounds", () => {
    expect(() =>
      resolveTelemetryClientConfig({
        NEXT_PUBLIC_TELEMETRY_RECONNECT_MIN_MS: "5000",
        NEXT_PUBLIC_TELEMETRY_RECONNECT_MAX_MS: "1000",
      }),
    ).toThrow("must be greater than or equal to the minimum");
  });
});

describe("telemetry URL builders", () => {
  const endpoints = {
    apiBaseUrl: "/telemetry-api",
    origin: "https://dashboard.nexolab.example",
  };

  it("builds deterministic latest URLs with filters", () => {
    expect(
      buildLatestTelemetryUrl(
        endpoints,
        {
          node_id: "edge-01",
          equipment_id: "K106",
          quality: "valid",
        },
        { limit: 48, offset: 0 },
      ),
    ).toBe(
      "https://dashboard.nexolab.example/telemetry-api/api/v1/telemetry/latest?node_id=edge-01&equipment_id=K106&quality=valid&limit=48&offset=0",
    );
  });

  it("builds bounded history URLs", () => {
    const url = buildHistoryTelemetryUrl(endpoints, {
      node_id: "edge-01",
      channel_id: "106-03",
      from: "2026-07-23T12:00:00+00:00",
      to: "2026-07-23T13:00:00+00:00",
      limit: 200,
    });
    const parsed = new URL(url);

    expect(parsed.pathname).toBe(
      "/telemetry-api/api/v1/telemetry/history",
    );
    expect(parsed.searchParams.get("from")).toBe(
      "2026-07-23T12:00:00+00:00",
    );
    expect(parsed.searchParams.get("channel_id")).toBe("106-03");
  });

  it("derives a secure WebSocket URL and resume cursor", () => {
    expect(
      buildLiveTelemetryUrl(
        endpoints,
        { node_id: "edge-01", channel_id: "106-04" },
        "2026-07-23T12:05:20.442225+00:00",
      ),
    ).toBe(
      "wss://dashboard.nexolab.example/telemetry-api/api/v1/telemetry/live?node_id=edge-01&channel_id=106-04&after=2026-07-23T12%3A05%3A20.442225%2B00%3A00",
    );
  });
});
