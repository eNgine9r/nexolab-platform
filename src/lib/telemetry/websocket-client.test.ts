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
  readonly close = vi.fn(() => {
    this.dispatchEvent(new CloseEvent("close"));
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

  disconnect(): void {
    this.dispatchEvent(new CloseEvent("close"));
  }
}

describe("TelemetryWebSocketClient", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

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
      {
        onSample: (value) => samples.push(value),
        onStateChange: (state) => states.push(state),
      },
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
    const resumedUrl = new URL(sockets[1].url);
    expect(resumedUrl.searchParams.get("after")).toBe(sample.captured_at);
    sockets[1].open();
    sockets[1].message(sample);
    expect(samples).toEqual([sample]);
    expect(states).toContain("reconnecting");

    subscription.close();
  });

  it("handles heartbeat and bounded reconnect exhaustion", async () => {
    vi.useFakeTimers();
    const sockets: MockWebSocket[] = [];
    const heartbeat = vi.fn();
    const onError = vi.fn();
    const states: TelemetryConnectionState[] = [];
    const client = new TelemetryWebSocketClient("ws://central/live", {
      createSocket: (url) => {
        const socket = new MockWebSocket(url);
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
      reconnectDelaysMs: [10],
    });

    client.subscribe(
      {},
      {
        onSample: vi.fn(),
        onHeartbeat: heartbeat,
        onError,
        onStateChange: (state) => states.push(state),
      },
    );

    sockets[0].message({
      type: "heartbeat",
      server_time: "2026-07-23T18:00:02Z",
    });
    expect(heartbeat).toHaveBeenCalledWith("2026-07-23T18:00:02Z");

    sockets[0].disconnect();
    await vi.advanceTimersByTimeAsync(10);
    sockets[1].disconnect();

    expect(states.at(-1)).toBe("disconnected");
    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({
        code: "websocket",
        message: "Telemetry WebSocket reconnect limit reached",
      }),
    );
  });
});
