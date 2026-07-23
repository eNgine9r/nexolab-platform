import {
  parseTelemetryCollection,
  parseTelemetryLiveMessage,
  parseTelemetryReadiness,
} from "./contract";
import { TelemetryClientError } from "./errors";

const sample = {
  event_id: "event-1",
  node_id: "edge-01",
  captured_at: "2026-07-23T18:00:00Z",
  metric: "temperature",
  value: 4.2,
  unit: "degC",
  quality: "valid",
  source: "modbus",
  equipment_id: "xjp60d-106",
  channel_id: "106-03",
  alarm: null,
  raw_value: 42,
  raw_status: null,
};

const readiness = {
  status: "ready",
  database: "ready",
  mqtt: "ready",
  queue_size: 0,
  websocket_clients: 1,
  database_outage_since: null,
  last_persisted_at: "2026-07-23T18:00:01Z",
  ingestion_lag_seconds: 0.25,
  mqtt_error: null,
  database_error: null,
  last_error: null,
};

describe("telemetry contract parsers", () => {
  it("parses a valid latest/history collection", () => {
    const response = parseTelemetryCollection({
      items: [{ ...sample, received_at: "2026-07-23T18:00:01Z" }],
      count: 1,
      limit: 200,
      offset: 0,
      next_offset: null,
    });

    expect(response.items[0]).toMatchObject(sample);
    expect(response.items[0].received_at).toBe("2026-07-23T18:00:01Z");
  });

  it("accepts a partial live sample without received_at", () => {
    expect(parseTelemetryLiveMessage(sample)).toEqual({
      kind: "sample",
      sample,
    });
  });

  it("parses heartbeat and service error messages", () => {
    expect(
      parseTelemetryLiveMessage({
        type: "heartbeat",
        server_time: "2026-07-23T18:00:02Z",
      }),
    ).toEqual({
      kind: "heartbeat",
      serverTime: "2026-07-23T18:00:02Z",
    });
    expect(
      parseTelemetryLiveMessage({ type: "error", detail: "resume limit" }),
    ).toEqual({ kind: "error", detail: "resume limit" });
  });

  it("parses readiness state", () => {
    expect(parseTelemetryReadiness(readiness)).toEqual(readiness);
  });

  it.each([
    [{ ...sample, event_id: "" }, "event_id"],
    [{ ...sample, captured_at: "not-a-date" }, "captured_at"],
    [{ ...sample, quality: "good" }, "quality"],
    [{ ...sample, value: Number.NaN }, "value"],
    [{ items: {}, count: 0, limit: 1, offset: 0, next_offset: null }, "items"],
  ])("rejects malformed payloads", (payload, path) => {
    const parse = "items" in payload ? parseTelemetryCollection : parseTelemetryLiveMessage;
    expect(() => parse(payload)).toThrowError(
      expect.objectContaining<TelemetryClientError>({
        code: "contract",
        message: expect.stringContaining(path),
      }),
    );
  });
});
