import { createTelemetryAdapter } from "./create-adapter";
import { DemoTelemetryAdapter } from "./demo-adapter";
import { LiveTelemetryAdapter } from "./live-adapter";
import type { TelemetrySample } from "./types";

const sample: TelemetrySample = {
  event_id: "demo-event",
  node_id: "edge-01",
  captured_at: "2026-07-23T18:00:00Z",
  metric: "temperature",
  value: 4.2,
  unit: "degC",
  quality: "valid",
  source: "demo",
  equipment_id: "xjp60d-106",
  channel_id: "106-03",
  alarm: null,
  raw_value: 42,
  raw_status: null,
};

describe("createTelemetryAdapter", () => {
  it("creates a demo adapter that implements the common interface", async () => {
    const adapter = createTelemetryAdapter(
      { mode: "demo", apiBaseUrl: null, websocketUrl: null },
      { demoSamples: [sample] },
    );

    expect(adapter).toBeInstanceOf(DemoTelemetryAdapter);
    await expect(adapter.latest({ channel_id: "106-03" })).resolves.toMatchObject({
      count: 1,
      items: [sample],
    });
  });

  it("creates a live adapter without browser-side credentials", () => {
    const adapter = createTelemetryAdapter({
      mode: "live",
      apiBaseUrl: "http://127.0.0.1:8082",
      websocketUrl: "ws://127.0.0.1:8082/api/v1/telemetry/live",
    });

    expect(adapter).toBeInstanceOf(LiveTelemetryAdapter);
  });

  it("rejects an incomplete live configuration", () => {
    expect(() =>
      createTelemetryAdapter({
        mode: "live",
        apiBaseUrl: null,
        websocketUrl: null,
      }),
    ).toThrow("Live telemetry mode requires REST and WebSocket URLs");
  });
});
