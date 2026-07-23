import { resolveTelemetryClientConfig } from "./config";
import {
  TelemetryLiveClient,
  type TelemetryLiveCallbacks,
  type TelemetrySocket,
} from "./live-client";

const event = {
  event_id: "56bb5d38-1c20-48c7-bfaf-8d3101da9e21",
  node_id: "edge-01",
  captured_at: "2026-07-23T12:05:20.442225+00:00",
  metric: "temperature.probe",
  value: 26,
  unit: "degC",
  quality: "valid",
  source: "dixell-xjp60d",
  equipment_id: "K106",
  channel_id: "106-03",
  alarm: "high",
  raw_value: 260,
  raw_status: 4354,
};

class FakeSocket implements TelemetrySocket {
  static instances: FakeSocket[] = [];

  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onclose: ((event: { code: number; reason: string }) => void) | null = null;
  close = vi.fn();

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  open(): void {
    this.onopen?.();
  }

  message(payload: unknown): void {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  serverClose(code = 1012, reason = "restart"): void {
    this.onclose?.({ code, reason });
  }
}

function callbacks(): TelemetryLiveCallbacks & {
  onTelemetry: ReturnType<typeof vi.fn>;
  onStatus: ReturnType<typeof vi.fn>;
  onHeartbeat: ReturnType<typeof vi.fn>;
  onError: ReturnType<typeof vi.fn>;
} {
  return {
    onTelemetry: vi.fn(),
    onStatus: vi.fn(),
    onHeartbeat: vi.fn(),
    onError: vi.fn(),
  };
}

describe("TelemetryLiveClient", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps one active socket and resumes after the newest accepted event", () => {
    const handlers = callbacks();
    const client = new TelemetryLiveClient({
      config: resolveTelemetryClientConfig({
        NEXT_PUBLIC_TELEMETRY_API_BASE_URL: "https://api.nexolab.example",
        NEXT_PUBLIC_TELEMETRY_RECONNECT_MIN_MS: "1000",
        NEXT_PUBLIC_TELEMETRY_RECONNECT_MAX_MS: "8000",
        NEXT_PUBLIC_TELEMETRY_RECONNECT_JITTER_RATIO: "0",
      }),
      filters: { node_id: "edge-01", channel_id: "106-03" },
      socketFactory: (url) => new FakeSocket(url),
      random: () => 0.5,
    });

    client.connect(handlers);
    client.connect(handlers);
    expect(FakeSocket.instances).toHaveLength(1);

    const first = FakeSocket.instances[0]!;
    first.open();
    first.message(event);
    expect(handlers.onTelemetry).toHaveBeenCalledWith(event);
    expect(client.getResumeAfter()).toBe(event.captured_at);

    first.serverClose();
    expect(handlers.onStatus).toHaveBeenLastCalledWith("reconnecting");
    vi.advanceTimersByTime(999);
    expect(FakeSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);

    expect(FakeSocket.instances).toHaveLength(2);
    expect(FakeSocket.instances[1]!.url).toContain(
      "after=2026-07-23T12%3A05%3A20.442225%2B00%3A00",
    );
    client.disconnect();
    expect(handlers.onStatus).toHaveBeenLastCalledWith("stopped");
  });

  it("does not advance the resume cursor for invalid messages", () => {
    const handlers = callbacks();
    const client = new TelemetryLiveClient({
      config: resolveTelemetryClientConfig({
        NEXT_PUBLIC_TELEMETRY_API_BASE_URL: "https://api.nexolab.example",
        NEXT_PUBLIC_TELEMETRY_RECONNECT_MIN_MS: "1000",
        NEXT_PUBLIC_TELEMETRY_RECONNECT_JITTER_RATIO: "0",
      }),
      socketFactory: (url) => new FakeSocket(url),
    });

    client.connect(handlers);
    const first = FakeSocket.instances[0]!;
    first.open();
    first.message({ ...event, quality: "unsupported" });

    expect(handlers.onError).toHaveBeenCalledTimes(1);
    expect(client.getResumeAfter()).toBeUndefined();
    first.serverClose();
    vi.advanceTimersByTime(1000);
    expect(FakeSocket.instances[1]!.url).not.toContain("after=");
  });

  it("routes heartbeat messages without treating them as telemetry", () => {
    const handlers = callbacks();
    const client = new TelemetryLiveClient({
      config: resolveTelemetryClientConfig({
        NEXT_PUBLIC_TELEMETRY_API_BASE_URL: "https://api.nexolab.example",
      }),
      socketFactory: (url) => new FakeSocket(url),
    });

    client.connect(handlers);
    FakeSocket.instances[0]!.open();
    FakeSocket.instances[0]!.message({
      type: "heartbeat",
      server_time: "2026-07-23T12:06:00Z",
    });

    expect(handlers.onHeartbeat).toHaveBeenCalledTimes(1);
    expect(handlers.onTelemetry).not.toHaveBeenCalled();
  });
});
