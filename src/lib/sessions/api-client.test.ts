import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createIdempotencyKey,
  createOperatorCommand,
  SessionApiClient,
  type SessionFetch,
} from "./api-client";

const emptyPage = {
  items: [],
  count: 0,
  limit: 100,
  offset: 0,
  next_offset: null,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("SessionApiClient", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("builds deterministic session list and telemetry history queries", async () => {
    const fetchMock = vi.fn<SessionFetch>().mockResolvedValue(jsonResponse(emptyPage));
    const client = new SessionApiClient("http://127.0.0.1:8082", { fetch: fetchMock });

    await client.listSessions({ state: "running", nodeId: "edge-01", limit: 25, offset: 50 });
    await client.historyTelemetry("session-1", {
      from: new Date("2026-07-24T10:00:00Z"),
      to: "2026-07-24T11:00:00Z",
      metric: "temperature.probe",
      limit: 500,
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8082/api/v1/sessions?state=running&node_id=edge-01&limit=25&offset=50",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8082/api/v1/sessions/session-1/telemetry/history?from=2026-07-24T10%3A00%3A00.000Z&to=2026-07-24T11%3A00%3A00Z&metric=temperature.probe&limit=500&offset=0",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("sends mutation payloads with an idempotency key", async () => {
    const response = {
      session: { id: "session-1" },
      event: { id: "event-1" },
      replayed: false,
    };
    const fetchMock = vi.fn<SessionFetch>().mockResolvedValue(jsonResponse(response, 201));
    const client = new SessionApiClient("http://127.0.0.1:8082", { fetch: fetchMock });
    const key = createIdempotencyKey("session-create");
    const command = createOperatorCommand("test create");

    await client.createSession(
      {
        session_number: "NXL-001",
        title: "Test",
        test_object: "Display case",
        node_id: "edge-01",
        metadata_payload: {},
        ...command,
      },
      key,
    );

    expect(key.length).toBeLessThanOrEqual(128);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8082/api/v1/sessions",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "Idempotency-Key": key }),
      }),
    );
  });

  it("surfaces structured backend conflicts", async () => {
    const client = new SessionApiClient("http://127.0.0.1:8082", {
      fetch: vi.fn<SessionFetch>().mockResolvedValue(
        jsonResponse(
          {
            detail: {
              code: "idempotency_key_reused",
              message: "idempotency key was already used for another command",
            },
          },
          409,
        ),
      ),
    });

    await expect(client.listSessions()).rejects.toMatchObject({
      name: "SessionClientError",
      status: 409,
      code: "idempotency_key_reused",
    });
  });

  it("enforces request timeouts", async () => {
    vi.useFakeTimers();
    const fetchMock: SessionFetch = (_input, init) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => reject(init.signal?.reason ?? new DOMException("Aborted")),
          { once: true },
        );
      });
    const client = new SessionApiClient("http://127.0.0.1:8082", {
      fetch: fetchMock,
      timeoutMs: 250,
    });
    const request = client.listSessions();
    const assertion = expect(request).rejects.toMatchObject({ code: "timeout" });

    await vi.advanceTimersByTimeAsync(250);

    await assertion;
  });
});
