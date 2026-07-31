import { afterEach, describe, expect, it, vi } from "vitest";

import type { TelemetryConnectionState, TelemetrySample } from "./types";
import { TelemetryWebSocketClient } from "./websocket-client";

const sample: TelemetrySample = {
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

class MockWebSocket extends EventTarget {
  readonly send = vi.fn();
  readonly close = vi.fn((code = 1000, reason = "") => {
    if (code !== 1000 && (code < 3000 || code > 4999)) {
      throw new DOMException(
        "The close code must be either 1000, or between 3000 and 4999.",
        "InvalidAccessError",
      );
    }
    this.dispatchEvent(new CloseEvent("close", { code, reason }));
  });

  constructor(readonly url: string) {
    super();
  }

  open(): void {
    this.dispatchEvent(new Event("open"));
  }

  message(payload: unknown): void {
    this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(payload) }));
  }

  disconnect(code = 1006, reason = ""): void {
    this.dispatchEvent(new CloseEvent("close", { code, reason }));
  }
}

describe("TelemetryWebSocketClient", () => {
  afterEach(() => vi.useRealTimers());

  it("filters, reconnects with last committed timestamp and ignores duplicates", async () => {
    vi.useFakeTimers();
    const sockets: MockWebSocket[] = [];
    const samples: TelemetrySample[] = [];
    const states: TelemetryConnectionState[] = [];
    const client = new TelemetryWebSocketClient("ws://127.0.0.1:8082/api/v1/telemetry/live", {
      createSocket: (url) => {
        const socket = new MockWebSocket(url);
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
      reconnectDelaysMs: [50, 100],
    });

    const subscription = client.subscribe(
      { node_id: "edge-01", channel_id: "106-03" },
      { onSample: (value) => samples.push(value), onStateChange: (state) => states.push(state) },
    );

    expect(sockets[0].url).toBe(
      "ws://127.0.0.1:8082/api/v1/telemetry/live?node_id=edge-01&channel_id=106-03",
    );
    sockets[0].open();
    sockets[0].message(sample);
    sockets[0].message(sample);
    expect(samples).toEqual([sample]);

    sockets[0].disconnect();
    await vi.advanceTimersByTimeAsync(50);
    expect(sockets).toHaveLength(2);
    expect(new URL(sockets[1].url).searchParams.get("after")).toBe(sample.captured_at);
    sockets[1].open();
    sockets[1].message(sample);
    expect(samples).toEqual([sample]);
    expect(states).toContain("reconnecting");

    subscription.close();
    await vi.advanceTimersByTimeAsync(1_000);
    expect(sockets).toHaveLength(2);
    expect(states.at(-1)).toBe("disconnected");
  });

  it("authenticates after open and refreshes credentials on reconnect", async () => {
    vi.useFakeTimers();
    const sockets: MockWebSocket[] = [];
    const states: TelemetryConnectionState[] = [];
    const credentials = vi
      .fn()
      .mockResolvedValueOnce({ accessToken: "jwt-one", organizationId: "org-1" })
      .mockResolvedValueOnce({ accessToken: "jwt-two", organizationId: "org-1" });
    const client = new TelemetryWebSocketClient("wss://central/api/v1/telemetry/live", {
      createSocket: (url) => {
        const socket = new MockWebSocket(url);
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
      credentials,
      reconnectDelaysMs: [10],
    });

    client.subscribe({}, { onSample: vi.fn(), onStateChange: (state) => states.push(state) });
    sockets[0].open();
    await Promise.resolve();
    await Promise.resolve();
    expect(sockets[0].send).toHaveBeenCalledWith(
      JSON.stringify({ type: "authenticate", access_token: "jwt-one", organization_id: "org-1" }),
    );
    expect(states.at(-1)).toBe("connecting");

    sockets[0].message({ type: "authenticated", subject: "viewer-user", organization_id: "org-1" });
    expect(states.at(-1)).toBe("connected");

    sockets[0].disconnect();
    await vi.advanceTimersByTimeAsync(10);
    sockets[1].open();
    await Promise.resolve();
    await Promise.resolve();
    expect(sockets[1].send).toHaveBeenCalledWith(expect.stringContaining("jwt-two"));
    expect(credentials).toHaveBeenCalledTimes(2);
  });

  it("connects without a credential handshake when authentication is disabled", () => {
    const sockets: MockWebSocket[] = [];
    const states: TelemetryConnectionState[] = [];
    const credentials = vi.fn();
    const client = new TelemetryWebSocketClient("ws://central/api/v1/telemetry/live", {
      createSocket: (url) => {
        const socket = new MockWebSocket(url);
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
      credentials,
      authenticationRequired: false,
    });

    client.subscribe({}, { onSample: vi.fn(), onStateChange: (state) => states.push(state) });
    sockets[0].open();
    expect(credentials).not.toHaveBeenCalled();
    expect(sockets[0].send).not.toHaveBeenCalled();
    expect(states.at(-1)).toBe("connected");
  });

  it("uses a browser-safe private close code and reports unauthorized", async () => {
    vi.useFakeTimers();
    const sockets: MockWebSocket[] = [];
    const states: TelemetryConnectionState[] = [];
    const onError = vi.fn();
    const client = new TelemetryWebSocketClient("wss://central/api/v1/telemetry/live", {
      createSocket: (url) => {
        const socket = new MockWebSocket(url);
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
      credentials: vi.fn().mockRejectedValue(new Error("session unavailable")),
      reconnectDelaysMs: [10],
    });

    client.subscribe({}, { onSample: vi.fn(), onError, onStateChange: (state) => states.push(state) });
    sockets[0].open();
    await Promise.resolve();
    await Promise.resolve();

    expect(sockets[0].close).toHaveBeenCalledWith(4001, "telemetry authentication failed");
    expect(states.at(-1)).toBe("unauthorized");
    await vi.advanceTimersByTimeAsync(100);
    expect(sockets).toHaveLength(1);
  });

  it("handles heartbeat and reports offline only after bounded reconnect exhaustion", async () => {
    vi.useFakeTimers();
    const sockets: MockWebSocket[] = [];
    const heartbeat = vi.fn();
    const states: TelemetryConnectionState[] = [];
    const client = new TelemetryWebSocketClient("ws://central/live", {
      createSocket: (url) => {
        const socket = new MockWebSocket(url);
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
      reconnectDelaysMs: [10],
    });

    client.subscribe({}, { onSample: vi.fn(), onHeartbeat: heartbeat, onStateChange: (state) => states.push(state) });
    sockets[0].message({ type: "heartbeat", server_time: "2026-07-23T18:00:02Z" });
    expect(heartbeat).toHaveBeenCalledWith("2026-07-23T18:00:02Z");
    expect(states.at(-1)).toBe("connected");

    sockets[0].disconnect();
    await vi.advanceTimersByTimeAsync(10);
    sockets[1].disconnect();
    expect(states.at(-1)).toBe("offline");
  });

  it("maps authorization policy violations to forbidden without retrying", () => {
    vi.useFakeTimers();
    const sockets: MockWebSocket[] = [];
    const states: TelemetryConnectionState[] = [];
    const client = new TelemetryWebSocketClient("wss://central/live", {
      createSocket: (url) => {
        const socket = new MockWebSocket(url);
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
      reconnectDelaysMs: [10],
    });

    client.subscribe({}, { onSample: vi.fn(), onStateChange: (state) => states.push(state) });
    sockets[0].disconnect(1008, "access denied");
    vi.advanceTimersByTime(100);
    expect(sockets).toHaveLength(1);
    expect(states.at(-1)).toBe("forbidden");
  });

  it("reports invalid endpoints as configuration errors", () => {
    const states: TelemetryConnectionState[] = [];
    const client = new TelemetryWebSocketClient("not-a-websocket-url");
    client.subscribe({}, { onSample: vi.fn(), onStateChange: (state) => states.push(state) });
    expect(states.at(-1)).toBe("configuration_error");
  });
});
