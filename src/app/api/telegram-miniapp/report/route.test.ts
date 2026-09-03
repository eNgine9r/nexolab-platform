import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { POST } from "./route";

function request(body: string): NextRequest {
  return new NextRequest("http://localhost/api/telegram-miniapp/report", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
}

describe("Telegram Mini App same-origin proxy", () => {
  beforeEach(() => {
    process.env.NEXOLAB_TELEGRAM_GATEWAY_BASE_URL = "http://127.0.0.1:8090";
  });

  afterEach(() => {
    vi.restoreAllMocks();
    delete process.env.NEXOLAB_TELEGRAM_GATEWAY_BASE_URL;
  });

  it("relays only the bounded auth payload to the fixed loopback endpoint", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        Response.json({ report: { id: "report-1" } }, { headers: { "Cache-Control": "no-store" } }),
      );
    const body = { init_data: "signed-data", start_hint: "report_test" };

    const response = await POST(request(JSON.stringify(body)));

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(String(fetchMock.mock.calls[0][0])).toBe("http://127.0.0.1:8090/miniapp/report");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "POST", body: JSON.stringify(body) });
  });

  it("allows only the exact internal service DNS endpoint on port 8090", async () => {
    process.env.NEXOLAB_TELEGRAM_GATEWAY_BASE_URL = "http://telegram-gateway:8090";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(Response.json({ report: {} }));

    const response = await POST(request(JSON.stringify({ init_data: "signed-data" })));

    expect(response.status).toBe(200);
    expect(String(fetchMock.mock.calls[0][0])).toBe("http://telegram-gateway:8090/miniapp/report");
  });

  it.each([
    "http://telegram-gateway:8080",
    "http://10.0.0.5:8090",
    "https://telegram-gateway:8090",
    "http://telegram-gateway:8090/prefix",
  ])("fails closed for an unapproved gateway target: %s", async (target) => {
    process.env.NEXOLAB_TELEGRAM_GATEWAY_BASE_URL = target;
    const fetchMock = vi.spyOn(globalThis, "fetch");

    const response = await POST(request(JSON.stringify({ init_data: "signed-data" })));

    expect(response.status).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects client-supplied authority fields instead of forwarding them", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const response = await POST(
      request(JSON.stringify({ init_data: "signed-data", organization_id: "client-controlled" })),
    );

    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects an oversized request before contacting the gateway", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const response = await POST(request(JSON.stringify({ init_data: "x".repeat(21 * 1024) })));

    expect(response.status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
