import { TelemetryClientError } from "./errors";
import { TelemetryRestClient, type TelemetryFetch } from "./rest-client";

const collection = {
  items: [],
  count: 0,
  limit: 10,
  offset: 0,
  next_offset: null,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("TelemetryRestClient", () => {
  it("builds deterministic latest and history queries", async () => {
    const fetchMock = vi.fn<TelemetryFetch>().mockResolvedValue(
      jsonResponse(collection),
    );
    const client = new TelemetryRestClient("http://127.0.0.1:8082", {
      fetch: fetchMock,
    });

    await client.latest({
      node_id: "edge-01",
      channel_id: "106-03",
      limit: 10,
      offset: 0,
    });
    await client.history({
      node_id: "edge-01",
      metric: "temperature",
      from: new Date("2026-07-23T17:00:00Z"),
      to: "2026-07-23T18:00:00Z",
      limit: 10,
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8082/api/v1/telemetry/latest?node_id=edge-01&channel_id=106-03&limit=10&offset=0",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8082/api/v1/telemetry/history?node_id=edge-01&metric=temperature&limit=10&from=2026-07-23T17%3A00%3A00.000Z&to=2026-07-23T18%3A00%3A00Z",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("returns a structured HTTP error", async () => {
    const client = new TelemetryRestClient("http://127.0.0.1:8082", {
      fetch: vi
        .fn<TelemetryFetch>()
        .mockResolvedValue(new Response("not ready", { status: 503 })),
    });

    await expect(client.readiness()).rejects.toMatchObject({
      name: "TelemetryClientError",
      code: "http",
      status: 503,
      message: "Telemetry service returned 503: not ready",
    });
  });

  it("reports an externally aborted request", async () => {
    const fetchMock: TelemetryFetch = (_input, init) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => reject(init.signal?.reason ?? new DOMException("Aborted")),
          { once: true },
        );
      });
    const client = new TelemetryRestClient("http://127.0.0.1:8082", {
      fetch: fetchMock,
      timeoutMs: 10_000,
    });
    const controller = new AbortController();
    const request = client.latest({}, controller.signal);

    controller.abort();

    await expect(request).rejects.toMatchObject<TelemetryClientError>({
      code: "aborted",
    });
  });

  it("enforces the configured timeout", async () => {
    vi.useFakeTimers();
    const fetchMock: TelemetryFetch = (_input, init) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => reject(init.signal?.reason ?? new DOMException("Aborted")),
          { once: true },
        );
      });
    const client = new TelemetryRestClient("http://127.0.0.1:8082", {
      fetch: fetchMock,
      timeoutMs: 250,
    });
    const request = client.latest();

    await vi.advanceTimersByTimeAsync(250);

    await expect(request).rejects.toMatchObject<TelemetryClientError>({
      code: "timeout",
      message: "Telemetry request exceeded 250 ms",
    });
    vi.useRealTimers();
  });

  it("rejects a malformed successful response", async () => {
    const client = new TelemetryRestClient("http://127.0.0.1:8082", {
      fetch: vi
        .fn<TelemetryFetch>()
        .mockResolvedValue(jsonResponse({ items: "invalid" })),
    });

    await expect(client.latest()).rejects.toMatchObject({
      code: "contract",
    });
  });
});
