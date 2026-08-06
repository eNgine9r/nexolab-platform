import { describe, expect, it, vi } from "vitest";

import { LiveDashboardInventoryClient } from "./inventory-client";

const noSampleItem = {
  channel_ref_id: "channel-ref-1",
  node_id: "edge-01",
  equipment_id: "controller-106",
  equipment_name: "Controller 106",
  channel_id: "106-03",
  channel_name: "Temperature 106-03",
  metric: "temperature",
  native_unit: "°C",
  source: "temperature_controller",
  quality: "unknown",
  alarm: null,
  latest: null,
};

describe("LiveDashboardInventoryClient", () => {
  it("loads the bounded canonical catalog and preserves no-sample channels", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            items: [noSampleItem],
            total: 1,
            limit: 500,
            offset: 0,
            has_more: false,
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
    );
    const client = new LiveDashboardInventoryClient("http://127.0.0.1:8082", { fetch: fetchImpl });

    const result = await client.list();

    expect(result.items[0]).toMatchObject({
      key: "106-03|temperature",
      channel_ref_id: "channel-ref-1",
      quality: "unknown",
      latest: null,
    });
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:8082/api/v1/live-dashboards/channel-inventory?limit=500&offset=0",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("parses bounded latest metadata without inventing raw values", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            items: [
              {
                ...noSampleItem,
                quality: "valid",
                alarm: "high",
                latest: {
                  event_id: "event-1",
                  node_id: "edge-01",
                  equipment_id: "controller-106",
                  channel_id: "106-03",
                  captured_at: "2026-08-06T08:00:00Z",
                  metric: "temperature",
                  value: 3.2,
                  unit: "°C",
                  quality: "valid",
                  source: "dixell-xjp60d",
                  alarm: "high",
                  raw_value: null,
                  raw_status: null,
                  received_at: "2026-08-06T08:00:01Z",
                },
              },
            ],
            total: 1,
            limit: 500,
            offset: 0,
            has_more: false,
          }),
          { status: 200 },
        ),
    );
    const client = new LiveDashboardInventoryClient("http://127.0.0.1:8082", { fetch: fetchImpl });

    const result = await client.list();

    expect(result.items[0]?.latest).toMatchObject({
      event_id: "event-1",
      value: 3.2,
      raw_value: null,
      raw_status: null,
    });
  });

  it("surfaces permission errors as typed inventory failures", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            detail: { code: "permission_denied", message: "Forbidden" },
          }),
          { status: 403 },
        ),
    );
    const client = new LiveDashboardInventoryClient("http://127.0.0.1:8082", { fetch: fetchImpl });

    await expect(client.list()).rejects.toMatchObject({
      status: 403,
      code: "permission_denied",
      message: "Forbidden",
    });
  });
});
