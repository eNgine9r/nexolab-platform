import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GET, PUT } from "./route";

const organizationId = "33333333-3333-3333-3333-333333333333";

function sessionResponse(permissions: string[]): Response {
  return Response.json({
    memberships: [{ organization_id: organizationId, permissions }],
  });
}

function request(method: "GET" | "PUT", body?: object): NextRequest {
  return new NextRequest("http://localhost/api/device-agent/xjp60d", {
    method,
    headers: {
      Authorization: "Bearer acceptance-token",
      "X-Organization-Id": organizationId,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
}

describe("XJP60D control proxy authorization", () => {
  beforeEach(() => {
    process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL = "http://127.0.0.1:8082";
    process.env.NEXOLAB_DEVICE_AGENT_BASE_URL = "http://127.0.0.1:8081";
  });

  afterEach(() => {
    vi.restoreAllMocks();
    delete process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL;
    delete process.env.NEXOLAB_DEVICE_AGENT_BASE_URL;
  });

  it.each([["dashboard.read"], ["equipment.manage"]])(
    "allows %s to read enrollment state",
    async (permission) => {
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValueOnce(sessionResponse([permission]))
        .mockResolvedValueOnce(Response.json({ schema_version: 1, revision: 9, points: [] }));

      const response = await GET(request("GET"));

      expect(response.status).toBe(200);
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(String(fetchMock.mock.calls[1][0])).toBe("http://127.0.0.1:8081/api/v1/xjp60d/configuration");
    },
  );

  it("denies enrollment reads without dashboard or equipment permission", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(sessionResponse(["telemetry.read"]));

    const response = await GET(request("GET"));

    expect(response.status).toBe(403);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("still requires equipment.manage for persisted enrollment changes", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(sessionResponse(["dashboard.read"]));

    const response = await PUT(request("PUT", { expected_revision: 9, points: [] }));

    expect(response.status).toBe(403);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
