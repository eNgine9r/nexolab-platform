import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setSecurityCredentials } from "@/features/security/security-session";

import { createReportApiClient, createReportIdempotencyKey, type ReportFetch } from "./api-client";

const emptyPage = {
  items: [],
  count: 0,
  limit: 200,
  offset: 0,
  next_offset: null,
};

function createFetchMock(response: Response = Response.json(emptyPage)) {
  return vi.fn<ReportFetch>(async () => response.clone());
}

describe("authenticated Reports API client", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_DATA_MODE", "live");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_API_BASE_URL", "https://api.example.test");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER", "supabase");
    setSecurityCredentials({
      accessToken: "verified-access-token",
      organizationId: "selected-org",
    });
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    setSecurityCredentials({ accessToken: null, organizationId: null });
  });

  it("adds bearer and organization headers to report reads", async () => {
    const fetchImpl = createFetchMock();
    await createReportApiClient({ fetch: fetchImpl }).listReports({ sessionId: "session-1" });

    const [url, init] = fetchImpl.mock.calls[0]!;
    const headers = new Headers(init?.headers);
    expect(url).toBe("https://api.example.test/api/v1/reports?session_id=session-1&limit=200&offset=0");
    expect(headers.get("Authorization")).toBe("Bearer verified-access-token");
    expect(headers.get("X-Organization-ID")).toBe("selected-org");
  });

  it("sends an idempotent generation request with the exact telemetry binding subset", async () => {
    const response = Response.json({
      id: "report-1",
      organization_id: "selected-org",
      session_id: "session-1",
      replayed: false,
    });
    const fetchImpl = createFetchMock(response);
    const idempotencyKey = createReportIdempotencyKey("session-1");

    await createReportApiClient({ fetch: fetchImpl }).generateReport(
      "session-1",
      "Controlled evidence export",
      idempotencyKey,
      "a".repeat(64),
      undefined,
      ["binding-2", "binding-4"],
    );

    const [url, init] = fetchImpl.mock.calls[0]!;
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    expect(url).toBe("https://api.example.test/api/v1/reports/sessions/session-1");
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("Idempotency-Key")).toBe(idempotencyKey);
    expect(body).toEqual({
      reason: "Controlled evidence export",
      expected_source_sha256: "a".repeat(64),
      binding_ids: ["binding-2", "binding-4"],
    });
    expect(body).not.toHaveProperty("generated_by");
    expect(body).not.toHaveProperty("actor_id");
  });

  it("keeps legacy generation compatible when no explicit binding subset is supplied", async () => {
    const response = Response.json({
      id: "report-1",
      organization_id: "selected-org",
      session_id: "session-1",
      replayed: false,
    });
    const fetchImpl = createFetchMock(response);

    await createReportApiClient({ fetch: fetchImpl }).generateReport(
      "session-1",
      "",
      "legacy-key",
    );

    const body = JSON.parse(String(fetchImpl.mock.calls[0]?.[1]?.body)) as Record<string, unknown>;
    expect(body).toEqual({
      reason: null,
      expected_source_sha256: null,
    });
    expect(body).not.toHaveProperty("binding_ids");
  });

  it("downloads bytes through authenticated fetch and keeps tokens out of the URL", async () => {
    const fetchImpl = createFetchMock(
      new Response("event_id,value\nevent-1,3.5\n", {
        status: 200,
        headers: {
          "Content-Type": "text/csv; charset=utf-8",
          "Content-Disposition": "attachment; filename*=UTF-8''telemetry.csv",
          "X-Content-SHA256": "b".repeat(64),
        },
      }),
    );

    const result = await createReportApiClient({ fetch: fetchImpl }).downloadArtifact(
      "report-1",
      "telemetry.csv",
    );

    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(url).toBe("https://api.example.test/api/v1/reports/report-1/artifacts/telemetry.csv");
    expect(String(url)).not.toContain("verified-access-token");
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer verified-access-token");
    expect(result.filename).toBe("telemetry.csv");
    expect(result.sha256).toBe("b".repeat(64));
    expect(await result.blob.text()).toContain("event-1,3.5");
  });
});
