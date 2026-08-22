import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GET, PUT } from "./route";

const organizationId = "33333333-3333-3333-3333-333333333333";

function sessionResponse(permissions: string[]): Response {
  return Response.json({
    memberships: [
      {
        organization_id: organizationId,
        permissions,
      },
    ],
  });
}

function request(method: "GET" | "PUT", body?: object): NextRequest {
  return new NextRequest("http://localhost/api/device-agent/acquisition-cadence", {
    method,
    headers: {
      Authorization: "Bearer acceptance-token",
      "X-Organization-Id": organizationId,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
}

describe("acquisition cadence proxy", () => {
  beforeEach(() => {
    process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL = "http://127.0.0.1:8082";
    process.env.NEXOLAB_DEVICE_AGENT_BASE_URL = "http://127.0.0.1:8081";
  });

  afterEach(() => {
    vi.restoreAllMocks();
    delete process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL;
    delete process.env.NEXOLAB_DEVICE_AGENT_BASE_URL;
  });

  it("allows dashboard readers to fetch persisted cadence through loopback", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(sessionResponse(["dashboard.read"]))
      .mockResolvedValueOnce(
        Response.json({
          schema_version: 1,
          registry_revision: 7,
          policy: { presets_seconds: [10, 30, 60] },
          capacity: { safe: true, buses: [] },
        }),
      );

    const response = await GET(request("GET"));

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({ registry_revision: 7 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const agentCall = fetchMock.mock.calls[1];
    expect(String(agentCall[0])).toBe("http://127.0.0.1:8081/api/v1/acquisition-cadence");
    expect(agentCall[1]).toMatchObject({ method: "GET" });
  });

  it("denies cadence mutation without equipment manage permission", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(sessionResponse(["dashboard.read"]));

    const response = await PUT(
      request("PUT", {
        expected_revision: 7,
        reason: "Set XJP60D cadence to 30 seconds",
        family_defaults: [
          { bus_id: "rs485-main", device_family: "xjp60d", interval_seconds: 30 },
        ],
      }),
    );

    expect(response.status).toBe(403);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("forwards authorized cadence mutation with audit actor and preserves capacity errors", async () => {
    const capacityError = {
      code: "acquisition_capacity_exceeded",
      detail: "Requested acquisition cadence exceeds RS-485 capacity: rs485-main",
      capacity: {
        safe: false,
        buses: [
          {
            bus_id: "rs485-main",
            safe: false,
            recommended_minimum_interval_seconds: 30,
          },
        ],
      },
    };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(sessionResponse(["dashboard.read", "equipment.manage"]))
      .mockResolvedValueOnce(Response.json(capacityError, { status: 422 }));
    const payload = {
      expected_revision: 7,
      reason: "Try XJP60D cadence at 10 seconds",
      family_defaults: [
        { bus_id: "rs485-main", device_family: "xjp60d", interval_seconds: 10 },
      ],
    };

    const response = await PUT(request("PUT", payload));

    expect(response.status).toBe(422);
    await expect(response.json()).resolves.toEqual(capacityError);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [, options] = fetchMock.mock.calls[1];
    expect(options).toMatchObject({ method: "PUT", body: JSON.stringify(payload) });
    const headers = new Headers(options?.headers);
    expect(headers.get("X-NEXOLAB-Actor")).toBe(`organization:${organizationId}:equipment.manage`);
  });

  it("preserves optimistic concurrency conflict from Device Agent", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(sessionResponse(["dashboard.read", "equipment.manage"]))
      .mockResolvedValueOnce(Response.json({ detail: "Registry revision conflict" }, { status: 409 }));

    const response = await PUT(
      request("PUT", {
        expected_revision: 6,
        reason: "Stale cadence edit",
        device_overrides: [{ device_id: "xjp60d-106", interval_seconds: 30 }],
      }),
    );

    expect(response.status).toBe(409);
    await expect(response.json()).resolves.toEqual({ detail: "Registry revision conflict" });
  });

  it("fails closed when the Device Agent endpoint is not loopback", async () => {
    process.env.NEXOLAB_DEVICE_AGENT_BASE_URL = "https://remote.example.test";
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(sessionResponse(["dashboard.read"]));

    const response = await GET(request("GET"));

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toMatchObject({
      detail: { code: "device_agent_unavailable" },
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
