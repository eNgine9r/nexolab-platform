import { describe, expect, it, vi } from "vitest";

import { LiveDashboardApiClient } from "./api-client";
import type { LiveDashboardWrite } from "./types";

const dashboard = {
  id: "dashboard-1",
  organization_id: "organization-1",
  name: "КК1 температури",
  description: null,
  owner_subject: "operator-1",
  refresh_seconds: 5,
  time_window: "15m",
  version: 3,
  status: "active",
  created_by: "operator-1",
  updated_by: "operator-1",
  created_at: "2026-08-05T17:00:00.000Z",
  updated_at: "2026-08-05T18:00:00.000Z",
  archived_by: null,
  archived_at: null,
  items: [
    {
      id: "item-1",
      position: 1,
      channel_ref_id: "channel-ref-1",
      channel_id: "106-03",
      metric: "temperature.probe",
      native_unit: "degC",
      visualization: "line",
      color: "#00C6E0",
      display_unit: "degC",
    },
  ],
};

const write: LiveDashboardWrite = {
  name: "КК1 температури",
  description: null,
  refresh_seconds: 5,
  time_window: "15m",
  items: [
    {
      channel_id: "106-03",
      metric: "temperature.probe",
      visualization: "line",
      color: "#00C6E0",
      display_unit: "degC",
    },
  ],
};

describe("LiveDashboardApiClient", () => {
  it("parses the persisted library collection", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({ items: [dashboard], total: 1, limit: 100, offset: 0, has_more: false }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
    );
    const client = new LiveDashboardApiClient("http://127.0.0.1:8082", { fetch: fetchImpl });

    const result = await client.list({ includeArchived: true });

    expect(result.items[0]?.name).toBe("КК1 температури");
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:8082/api/v1/live-dashboards?include_archived=true&limit=100&offset=0",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("sends If-Match and preserves the returned ETag on update", async () => {
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(new Headers(init?.headers).get("If-Match")).toBe('W/"live-dashboard-v3"');
      expect(new Headers(init?.headers).get("X-Audit-Reason")).toBe("Update Live Dashboard");
      return new Response(JSON.stringify({ ...dashboard, version: 4 }), {
        status: 200,
        headers: { "Content-Type": "application/json", ETag: 'W/"live-dashboard-v4"' },
      });
    });
    const client = new LiveDashboardApiClient("http://127.0.0.1:8082", { fetch: fetchImpl });

    const result = await client.update("dashboard-1", write, 'W/"live-dashboard-v3"');

    expect(result.value.version).toBe(4);
    expect(result.etag).toBe('W/"live-dashboard-v4"');
  });

  it("surfaces stale-writer versions without converting the conflict into generic failure", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            detail: {
              code: "live_dashboard_version_conflict",
              message: "expected 3, actual 4",
              expected_version: 3,
              actual_version: 4,
            },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
    );
    const client = new LiveDashboardApiClient("http://127.0.0.1:8082", { fetch: fetchImpl });

    await expect(client.update("dashboard-1", write, 'W/"live-dashboard-v3"')).rejects.toMatchObject({
      status: 409,
      code: "live_dashboard_version_conflict",
      expectedVersion: 3,
      actualVersion: 4,
    });
  });

  it("archives with DELETE and a version precondition", async () => {
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.method).toBe("DELETE");
      expect(new Headers(init?.headers).get("If-Match")).toBe('W/"live-dashboard-v3"');
      return new Response(null, { status: 204, headers: { ETag: 'W/"live-dashboard-v4"' } });
    });
    const client = new LiveDashboardApiClient("http://127.0.0.1:8082", { fetch: fetchImpl });

    await expect(client.archive("dashboard-1", 'W/"live-dashboard-v3"')).resolves.toBe(
      'W/"live-dashboard-v4"',
    );
  });
  it("downloads persisted CSV with the selected UTC range and browser timezone", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toContain("/api/v1/live-dashboards/dashboard-1/telemetry.csv?");
      const url = new URL(String(input));
      expect(url.searchParams.get("from")).toBe("2026-08-18T08:00:00.000Z");
      expect(url.searchParams.get("to")).toBe("2026-08-18T09:00:00.000Z");
      expect(url.searchParams.get("timezone")).toBe("Europe/Kyiv");
      expect(new Headers(init?.headers).get("Accept")).toBe("text/csv");
      return new Response("timestamp_utc,value\n2026-08-18T08:00:00Z,4.2\n", {
        status: 200,
        headers: {
          "Content-Type": "text/csv; charset=utf-8",
          "Content-Disposition": "attachment; filename*=UTF-8''live-dashboard-dashboard-1.csv",
        },
      });
    });
    const client = new LiveDashboardApiClient("http://127.0.0.1:8082", { fetch: fetchImpl });

    const result = await client.exportTelemetryCsv("dashboard-1", {
      from: "2026-08-18T08:00:00.000Z",
      to: "2026-08-18T09:00:00.000Z",
      timezone: "Europe/Kyiv",
    });

    expect(result.filename).toBe("live-dashboard-dashboard-1.csv");
    expect(result.mediaType).toContain("text/csv");
    expect(await result.blob.text()).toContain("2026-08-18T08:00:00Z");
  });

  it("surfaces bounded CSV export errors instead of returning a partial download", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            detail: {
              code: "live_dashboard_export_row_limit",
              message: "Saved Dashboard export exceeds the safe limit of 100000 rows.",
            },
          }),
          { status: 422, headers: { "Content-Type": "application/json" } },
        ),
    );
    const client = new LiveDashboardApiClient("http://127.0.0.1:8082", { fetch: fetchImpl });

    await expect(
      client.exportTelemetryCsv("dashboard-1", {
        from: "2026-07-19T08:00:00.000Z",
        to: "2026-08-18T08:00:00.000Z",
        timezone: "UTC",
      }),
    ).rejects.toMatchObject({
      status: 422,
      code: "live_dashboard_export_row_limit",
    });
  });
});
