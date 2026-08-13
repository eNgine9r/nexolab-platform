import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AlertInstance, AlertPage, AlertState } from "@/lib/alerts/types";
import { clearAllMonitoringReadModels } from "@/lib/monitoring-read-model-cache";

import {
  invalidateOverviewAlertsReadModel,
  useOverviewAlertsReadModel,
} from "./use-overview-alerts-read-model";

const mocks = vi.hoisted(() => ({
  listAlerts: vi.fn(),
}));

vi.mock("@/lib/alerts/api-client", () => ({
  createAlertApiClient: () => ({ listAlerts: mocks.listAlerts }),
}));

beforeEach(() => {
  clearAllMonitoringReadModels();
  mocks.listAlerts.mockReset();
  mocks.listAlerts.mockImplementation(async ({ state }: { state?: AlertState }) =>
    alertPage(state === "active" ? [alertFixture()] : []),
  );
});

describe("Overview alerts read model", () => {
  it("reuses the exact active and acknowledged summary across a warm remount", async () => {
    const first = renderHook(() => useOverviewAlertsReadModel({ enabled: true, organizationId: "org-a" }));

    await waitFor(() => expect(first.result.current.value?.[0]?.id).toBe("alert-1"));
    expect(mocks.listAlerts).toHaveBeenCalledTimes(2);
    first.unmount();

    const second = renderHook(() => useOverviewAlertsReadModel({ enabled: true, organizationId: "org-a" }));

    await waitFor(() => expect(second.result.current.value?.[0]?.id).toBe("alert-1"));
    expect(mocks.listAlerts).toHaveBeenCalledTimes(2);
  });

  it("retains the last valid summary when an explicit refresh fails", async () => {
    const model = renderHook(() => useOverviewAlertsReadModel({ enabled: true, organizationId: "org-a" }));
    await waitFor(() => expect(model.result.current.value?.[0]?.id).toBe("alert-1"));
    mocks.listAlerts.mockRejectedValue(new Error("Alerts API unavailable"));

    act(() => model.result.current.retry());

    await waitFor(() => expect(model.result.current.error?.message).toBe("Alerts API unavailable"));
    expect(model.result.current.value?.[0]?.id).toBe("alert-1");
  });

  it("reloads the summary after targeted lifecycle invalidation", async () => {
    const first = renderHook(() => useOverviewAlertsReadModel({ enabled: true, organizationId: "org-a" }));
    await waitFor(() => expect(first.result.current.value?.[0]?.id).toBe("alert-1"));
    first.unmount();

    invalidateOverviewAlertsReadModel("org-a");
    const second = renderHook(() => useOverviewAlertsReadModel({ enabled: true, organizationId: "org-a" }));

    await waitFor(() => expect(mocks.listAlerts).toHaveBeenCalledTimes(4));
    expect(second.result.current.value?.[0]?.id).toBe("alert-1");
  });
});

function alertPage(items: AlertInstance[]): AlertPage {
  return { items, count: items.length, limit: 20, offset: 0, next_offset: null };
}

function alertFixture(): AlertInstance {
  return {
    id: "alert-1",
    organization_id: "org-a",
    rule_id: "rule-1",
    rule_version_id: "rule-version-1",
    resource_key: "edge-01:channel-1:temperature",
    node_id: "edge-01",
    equipment_id: "chamber-1",
    channel_id: "channel-1",
    metric: "temperature",
    state: "active",
    severity: "warning",
    trigger_value: 8.2,
    trigger_threshold: 8,
    clear_threshold: 7.5,
    maximum_deviation: 0.2,
    first_event_id: "event-1",
    last_event_id: "event-1",
    session_id: null,
    stage_id: null,
    binding_id: null,
    context: { unit: "°C" },
    triggered_at: "2026-08-13T08:00:00Z",
    acknowledged_at: null,
    resolved_at: null,
    closed_at: null,
    lock_version: 1,
    created_at: "2026-08-13T08:00:00Z",
    updated_at: "2026-08-13T08:00:00Z",
  };
}
