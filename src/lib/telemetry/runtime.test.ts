import {
  parseHeartbeat,
  parseTelemetryCollection,
  parseTelemetryEvent,
  TelemetryPayloadError,
} from "./runtime";

const event = {
  event_id: "56bb5d38-1c20-48c7-bfaf-8d3101da9e21",
  node_id: "edge-01",
  captured_at: "2026-07-23T12:05:20.442225+00:00",
  metric: "electrical.voltage",
  value: 227.3,
  unit: "V",
  quality: "valid",
  source: "f-and-f-le-01mp",
  equipment_id: "LE01MP-201",
  channel_id: "201-voltage",
  alarm: null,
  raw_value: 2273,
  raw_status: null,
};

describe("telemetry runtime validation", () => {
  it("accepts a canonical telemetry event", () => {
    expect(parseTelemetryEvent(event)).toEqual(event);
  });

  it("rejects naive timestamps and unsupported quality values", () => {
    expect(() => parseTelemetryEvent({ ...event, captured_at: "2026-07-23T12:05:20" })).toThrow(
      TelemetryPayloadError,
    );
    expect(() => parseTelemetryEvent({ ...event, quality: "excellent" })).toThrow(
      "quality has an unsupported value",
    );
  });

  it("requires a numeric value for valid telemetry", () => {
    expect(() => parseTelemetryEvent({ ...event, value: null })).toThrow(
      "valid telemetry requires a numeric value",
    );
  });

  it("parses paginated REST collections", () => {
    const collection = parseTelemetryCollection({
      items: [{ ...event, received_at: "2026-07-23T12:05:21+00:00" }],
      count: 1,
      limit: 200,
      offset: 0,
      next_offset: null,
    });

    expect(collection.count).toBe(1);
    expect(collection.items[0]?.event_id).toBe(event.event_id);
  });

  it("parses heartbeat messages separately from telemetry", () => {
    expect(
      parseHeartbeat({
        type: "heartbeat",
        server_time: "2026-07-23T12:06:00Z",
      }),
    ).toEqual({
      type: "heartbeat",
      server_time: "2026-07-23T12:06:00Z",
    });
  });
});
