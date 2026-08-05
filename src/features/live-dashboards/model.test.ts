import { describe, expect, it } from "vitest";

import {
  addDashboardDraftItem,
  createEmptyLiveDashboardDraft,
  dashboardToDraft,
  filterLiveDashboardInventory,
  moveDashboardDraftItem,
  validateLiveDashboardDraft,
} from "./model";
import type { LiveDashboard, LiveDashboardInventoryItem } from "./types";

const inventory: LiveDashboardInventoryItem = {
  key: "106-03|temperature.probe",
  node_id: "edge-01",
  equipment_id: "xjp60d-106",
  channel_id: "106-03",
  metric: "temperature.probe",
  native_unit: "degC",
  source: "dixell-xjp60d",
  quality: "valid",
  alarm: null,
  latest: {
    event_id: "sample-1",
    node_id: "edge-01",
    captured_at: "2026-08-05T18:00:00.000Z",
    metric: "temperature.probe",
    value: 3.8,
    unit: "degC",
    quality: "valid",
    source: "dixell-xjp60d",
    equipment_id: "xjp60d-106",
    channel_id: "106-03",
    alarm: null,
    raw_value: 38,
    raw_status: null,
  },
};

const dashboard: LiveDashboard = {
  id: "dashboard-1",
  organization_id: "organization-1",
  name: "КК1 температури",
  description: "Контрольні точки",
  owner_subject: "operator-1",
  refresh_seconds: 5,
  time_window: "1h",
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

describe("Live Dashboard editor model", () => {
  it("preserves server order, version and ETag when editing", () => {
    const draft = dashboardToDraft(dashboard, 'W/"live-dashboard-v3"');

    expect(draft.id).toBe("dashboard-1");
    expect(draft.version).toBe(3);
    expect(draft.etag).toBe('W/"live-dashboard-v3"');
    expect(draft.items.map((item) => item.channel_id)).toEqual(["106-03"]);
    expect(validateLiveDashboardDraft(draft)).toEqual({ valid: true, issues: [] });
  });

  it("rejects duplicate channel and metric pairs without losing the draft", () => {
    const first = addDashboardDraftItem(createEmptyLiveDashboardDraft(), inventory);
    const second = addDashboardDraftItem(first.draft, inventory);

    expect(first.added).toBe(true);
    expect(second).toEqual({ draft: first.draft, added: false, reason: "duplicate" });
  });

  it("rejects display-unit conversion that is not backed by the persisted domain", () => {
    const draft = dashboardToDraft(dashboard);
    draft.items[0] = { ...draft.items[0], display_unit: "degF" };

    expect(validateLiveDashboardDraft(draft)).toEqual({
      valid: false,
      issues: ["Для 106-03 дозволена лише базова одиниця degC."],
    });
  });

  it("reorders selected channels deterministically", () => {
    const first = addDashboardDraftItem(createEmptyLiveDashboardDraft(), inventory).draft;
    const second = addDashboardDraftItem(first, {
      ...inventory,
      key: "115-04|temperature.probe",
      channel_id: "115-04",
      equipment_id: "xjp60d-115",
      latest: {
        ...inventory.latest,
        event_id: "sample-2",
        channel_id: "115-04",
        equipment_id: "xjp60d-115",
      },
    }).draft;

    expect(moveDashboardDraftItem(second, 1, -1).items.map((item) => item.channel_id)).toEqual([
      "115-04",
      "106-03",
    ]);
  });

  it("filters inventory by canonical identity fields and current quality", () => {
    const items = [
      inventory,
      {
        ...inventory,
        key: "M200|electrical.power.active",
        node_id: "edge-02",
        equipment_id: "meter-200",
        channel_id: "M200",
        metric: "electrical.power.active",
        native_unit: "W",
        source: "le-01mp",
        quality: "communication_error" as const,
        latest: {
          ...inventory.latest,
          event_id: "sample-3",
          node_id: "edge-02",
          equipment_id: "meter-200",
          channel_id: "M200",
          metric: "electrical.power.active",
          unit: "W",
          quality: "communication_error" as const,
        },
      },
    ];

    expect(
      filterLiveDashboardInventory(items, {
        search: "meter",
        node_id: "all",
        equipment_id: "all",
        metric: "all",
        quality: "communication_error",
        alarm: "all",
      }).map((item) => item.channel_id),
    ).toEqual(["M200"]);
  });
});
