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
  return new NextRequest("http://localhost/api/device-agent/acquisition-registry", {
    method,
    headers: {
      Authorization: "Bearer acceptance-token",
      "X-Organization-Id": organizationId,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
}

describe("acquisition registry proxy", () => {
  beforeEach(() => {
    process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL = "http://127.0.0.1:8082";
    process.env.NEXOLAB_DEVICE_AGENT_BASE_URL = "http://127.0.0.1:8081";
  });

  afterEach(() => {
    vi.restoreAllMocks();
    delete process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL;
    delete process.env.NEXOLAB_DEVICE_AGENT_BASE_URL;
  });

  it("allows dashboard readers to fetch the sanitized registry", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(sessionResponse(["dashboard.read"]))
      .mockResolvedValueOnce(
        Response.json({
          schema_version: 1,
          revision: 2,
          summary: { inventory_targets: 10, poll_eligible_targets: 3 },
        }),
      );

    const response = await GET(request("GET"));

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({ revision: 2 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const agentCall = fetchMock.mock.calls[1];
    expect(String(agentCall[0])).toBe("http://127.0.0.1:8081/api/v1/acquisition-registry");
    expect(agentCall[1]).toMatchObject({ method: "GET" });
  });

  it("denies registry mutation without equipment manage permission", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(sessionResponse(["dashboard.read"]));

    const response = await PUT(
      request("PUT", {
        expected_revision: 1,
        reason: "Disable reserve target",
        targets: [{ target_id: "xjp60d:106-03", lifecycle: "disabled" }],
      }),
    );

    expect(response.status).toBe(403);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("forwards an authorized bounded eligibility mutation with audit actor", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(sessionResponse(["dashboard.read", "equipment.manage"]))
      .mockResolvedValueOnce(
        Response.json({
          schema_version: 1,
          revision: 2,
          recent_audit: [],
        }),
      );
    const payload = {
      expected_revision: 1,
      reason: "Move unused meter metric to reserve",
      targets: [
        {
          target_id: "le01mp:200-active-power",
          lifecycle: "reserve",
        },
      ],
    };

    const response = await PUT(request("PUT", payload));

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [, options] = fetchMock.mock.calls[1];
    expect(options).toMatchObject({
      method: "PUT",
      body: JSON.stringify(payload),
    });
    const headers = new Headers(options?.headers);
    expect(headers.get("X-NEXOLAB-Actor")).toBe(`organization:${organizationId}:equipment.manage`);
  });

  it("rejects a non-loopback Device Agent endpoint before relaying", async () => {
    process.env.NEXOLAB_DEVICE_AGENT_BASE_URL = "https://remote.example.test";
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(sessionResponse(["dashboard.read"]));

    await expect(GET(request("GET"))).rejects.toThrow("Device Agent control endpoint must use loopback HTTP");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
