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

async function flushConnection(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

describe("TelemetryWebSocketClient", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("filters, reconnects with the last committed timestamp and ignores duplicates", async () => {
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
      authenticationRequired: false,
      reconnectDelaysMs: [50, 100],
      heartbeatTimeoutMs: 60_000,
    });

    const subscription = client.subscribe(
      { node_id: "edge-01", channel_id: "106-03" },
      {
        onSample: (value) => samples.push(value),
        onStateChange: (state) => states.push(state),
      },
    );
    await flushConnection();

    expect(sockets[0].url).toBe(
      "ws://127.0.0.1:8082/api/v1/telemetry/live?node_id=edge-01&channel_id=106-03",
    );
    sockets[0].open();
    sockets[0].message(sample);
    sockets[0].message(sample);
    expect(samples).toEqual([sample]);
    expect(states.at(-1)).toBe("connected");

    sockets[0].disconnect();
    await vi.advanceTimersByTimeAsync(50);
    await flushConnection();

    expect(sockets).toHaveLength(2);
    const resumedUrl = new URL(sockets[1].url);
    expect(resumedUrl.searchParams.get("after")).toBe(sample.captured_at);
    sockets[1].open();
    sockets[1].message(sample);
    expect(samples).toEqual([sample]);
    expect(states).toContain("reconnecting");

    subscription.close();
    expect(states.at(-1)).toBe("idle");
  });

  it("authenticates, waits for acknowledgement and refreshes credentials on reconnect", async () => {
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
      authenticationRequired: true,
      reconnectDelaysMs: [10],
      authenticationTimeoutMs: 100,
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
    expect(sockets[0].url).not.toContain("jwt-one");
    expect(sockets[0].send).toHaveBeenCalledWith(
      JSON.stringify({
        type: "authenticate",
        access_token: "jwt-one",
        organization_id: "org-1",
      }),
    );
    expect(states.at(-1)).toBe("connecting");

    sockets[0].message({
      type: "authenticated",
      subject: "viewer-user",
      organization_id: "org-1",
    });
    expect(states.at(-1)).toBe("connected");

    sockets[0].disconnect();
    await vi.advanceTimersByTimeAsync(10);
    await flushConnection();
    sockets[1].open();
    expect(sockets[1].send).toHaveBeenCalledWith(expect.stringContaining("jwt-two"));
    expect(credentials).toHaveBeenCalledTimes(2);
  });

  it("connects without a credential handshake when authentication is disabled", async () => {
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

    client.subscribe(
      {},
      {
        onSample: vi.fn(),
        onStateChange: (state) => states.push(state),
      },
    );
    await flushConnection();
    sockets[0].open();

    expect(credentials).not.toHaveBeenCalled();
    expect(sockets[0].send).not.toHaveBeenCalled();
    expect(states.at(-1)).toBe("connected");
  });

  it("reports missing user credentials as unauthorized without opening or retrying", async () => {
    vi.useFakeTimers();
    const createSocket = vi.fn();
    const states: TelemetryConnectionState[] = [];
    const onError = vi.fn();
    const client = new TelemetryWebSocketClient("wss://central/api/v1/telemetry/live", {
      createSocket,
      credentials: vi.fn().mockResolvedValue({ accessToken: null, organizationId: "org-1" }),
      authenticationRequired: true,
      reconnectDelaysMs: [10],
    });

    client.subscribe(
      {},
      {
        onSample: vi.fn(),
        onError,
        onStateChange: (state) => states.push(state),
      },
    );
    await flushConnection();
    await vi.advanceTimersByTimeAsync(100);

    expect(createSocket).not.toHaveBeenCalled();
    expect(states.at(-1)).toBe("unauthorized");
    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({ message: expect.stringContaining("authenticated user session") }),
    );
  });

  it("reports a missing organization as configuration_error", async () => {
    const states: TelemetryConnectionState[] = [];
    const client = new TelemetryWebSocketClient("wss://central/api/v1/telemetry/live", {
      createSocket: vi.fn(),
      credentials: vi.fn().mockResolvedValue({ accessToken: "jwt", organizationId: null }),
      authenticationRequired: true,
    });

    client.subscribe(
      {},
      {
        onSample: vi.fn(),
        onStateChange: (state) => states.push(state),
      },
    );
    await flushConnection();

    expect(states.at(-1)).toBe("configuration_error");
  });

  it("does not retry a forbidden organization response", async () => {
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
      credentials: vi.fn().mockResolvedValue({ accessToken: "jwt", organizationId: "org-1" }),
      authenticationRequired: true,
      reconnectDelaysMs: [10],
    });

    client.subscribe(
      {},
      {
        onSample: vi.fn(),
        onError,
        onStateChange: (state) => states.push(state),
      },
    );
    await flushConnection();
    sockets[0].open();
    sockets[0].message({
      type: "error",
      code: "organization_membership_not_found",
      detail: "Organization membership not found",
    });
    await vi.advanceTimersByTimeAsync(100);

    expect(states.at(-1)).toBe("forbidden");
    expect(sockets).toHaveLength(1);
    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({ message: "Organization membership not found" }),
    );
  });

  it("reconnects after heartbeat timeout and returns to connected", async () => {
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
      reconnectDelaysMs: [10],
      heartbeatTimeoutMs: 50,
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

    await vi.advanceTimersByTimeAsync(50);
    expect(sockets[0].close).toHaveBeenCalledWith(4000, "heartbeat timeout");
    await vi.advanceTimersByTimeAsync(10);
    await flushConnection();
    expect(sockets).toHaveLength(2);

    sockets[1].open();
    expect(states.at(-1)).toBe("connected");
  });

  it("enters offline only after bounded reconnect exhaustion", async () => {
    vi.useFakeTimers();
    const sockets: MockWebSocket[] = [];
    const onError = vi.fn();
    const states: TelemetryConnectionState[] = [];
    const client = new TelemetryWebSocketClient("ws://central/live", {
      createSocket: (url) => {
        const socket = new MockWebSocket(url);
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
      authenticationRequired: false,
      reconnectDelaysMs: [10],
    });

    client.subscribe(
      {},
      {
        onSample: vi.fn(),
        onError,
        onStateChange: (state) => states.push(state),
      },
    );
    await flushConnection();
    sockets[0].disconnect();
    await vi.advanceTimersByTimeAsync(10);
    await flushConnection();
    sockets[1].disconnect();

    expect(states.at(-1)).toBe("offline");
    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({
        code: "websocket",
        message: "Telemetry WebSocket reconnect limit reached",
      }),
    );
  });
});
