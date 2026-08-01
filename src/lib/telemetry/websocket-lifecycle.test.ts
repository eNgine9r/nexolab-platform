import { afterEach, describe, expect, it, vi } from "vitest";

import type { TelemetryConnectionState, TelemetrySample } from "./types";
import { TelemetryWebSocketClient } from "./websocket-client";

const sample: TelemetrySample = {
  event_id: "event-lifecycle-1",
  node_id: "edge-01",
  captured_at: "2026-08-01T12:00:00Z",
  metric: "temperature.probe",
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

async function flushConnection(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

describe("TelemetryWebSocketClient lifecycle", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not present a transport open event as live evidence", async () => {
    const sockets: MockWebSocket[] = [];
    const states: TelemetryConnectionState[] = [];
    const client = new TelemetryWebSocketClient("ws://central/live", {
      createSocket: (url) => {
        const socket = new MockWebSocket(url);
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
      authenticationRequired: false,
      heartbeatTimeoutMs: 1_000,
    });

    client.subscribe(
      {},
      {
        onSample: vi.fn(),
        onStateChange: (state) => states.push(state),
      },
    );
    await flushConnection();
    sockets[0].open();

    expect(states.at(-1)).toBe("connecting");

    sockets[0].message({ type: "heartbeat", server_time: "2026-08-01T12:00:01Z" });
    expect(states.at(-1)).toBe("connected");
  });

  it("closes a connection attempt with a browser-safe private code and reconnects once", async () => {
    vi.useFakeTimers();
    const sockets: MockWebSocket[] = [];
    const states: TelemetryConnectionState[] = [];
    const client = new TelemetryWebSocketClient("ws://central/live", {
      createSocket: (url) => {
        const socket = new MockWebSocket(url);
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
      authenticationRequired: false,
      connectionTimeoutMs: 20,
      reconnectDelaysMs: [10],
      heartbeatTimeoutMs: 1_000,
    });

    client.subscribe(
      {},
      {
        onSample: vi.fn(),
        onStateChange: (state) => states.push(state),
      },
    );
    await flushConnection();

    await vi.advanceTimersByTimeAsync(20);
    expect(sockets[0].close).toHaveBeenCalledWith(4002, "telemetry connection timeout");
    expect(states.at(-1)).toBe("reconnecting");

    await vi.advanceTimersByTimeAsync(10);
    await flushConnection();
    expect(sockets).toHaveLength(2);
  });

  it("keeps reconnect backoff until valid live evidence arrives", async () => {
    vi.useFakeTimers();
    const sockets: MockWebSocket[] = [];
    const states: TelemetryConnectionState[] = [];
    const client = new TelemetryWebSocketClient("ws://central/live", {
      createSocket: (url) => {
        const socket = new MockWebSocket(url);
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
      authenticationRequired: false,
      reconnectDelaysMs: [10, 20],
      connectionTimeoutMs: 1_000,
      heartbeatTimeoutMs: 1_000,
    });

    client.subscribe(
      {},
      {
        onSample: vi.fn(),
        onStateChange: (state) => states.push(state),
      },
    );
    await flushConnection();
    sockets[0].open();
    sockets[0].disconnect();

    await vi.advanceTimersByTimeAsync(10);
    await flushConnection();
    sockets[1].open();
    sockets[1].disconnect();

    await vi.advanceTimersByTimeAsync(20);
    await flushConnection();
    expect(sockets).toHaveLength(3);

    sockets[2].open();
    sockets[2].message(sample);
    expect(states.at(-1)).toBe("connected");
  });

  it("cleans connection, authentication, heartbeat and reconnect timers on close", async () => {
    vi.useFakeTimers();
    const sockets: MockWebSocket[] = [];
    const onError = vi.fn();
    const client = new TelemetryWebSocketClient("wss://central/live", {
      createSocket: (url) => {
        const socket = new MockWebSocket(url);
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
      credentials: vi.fn().mockResolvedValue({ accessToken: "jwt", organizationId: "org-1" }),
      authenticationRequired: true,
      connectionTimeoutMs: 50,
      authenticationTimeoutMs: 50,
      heartbeatTimeoutMs: 50,
      reconnectDelaysMs: [10],
    });

    const subscription = client.subscribe({}, { onSample: vi.fn(), onError });
    await flushConnection();
    sockets[0].open();
    subscription.close();

    await vi.runAllTimersAsync();

    expect(sockets).toHaveLength(1);
    expect(sockets[0].close).toHaveBeenCalledWith(1000, "dashboard subscription closed");
    expect(onError).not.toHaveBeenCalled();
  });

  it("keeps a stale snapshot visible without assigning live status", async () => {
    vi.useFakeTimers();
    const sockets: MockWebSocket[] = [];
    const states: TelemetryConnectionState[] = [];
    const samples: TelemetrySample[] = [];
    const client = new TelemetryWebSocketClient("ws://central/live", {
      createSocket: (url) => {
        const socket = new MockWebSocket(url);
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
      authenticationRequired: false,
      reconnectDelaysMs: [],
      heartbeatTimeoutMs: 1_000,
    });

    client.subscribe(
      {},
      {
        onSample: (value) => samples.push(value),
        onStateChange: (state) => states.push(state),
      },
    );
    await flushConnection();
    sockets[0].open();
    sockets[0].message(sample);
    expect(states.at(-1)).toBe("connected");

    sockets[0].disconnect();
    expect(states.at(-1)).toBe("offline");
    expect(samples).toEqual([sample]);
  });
});
