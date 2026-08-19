import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LiveDashboard } from "@/features/live-dashboards/types";
import type {
  TelemetryCollectionResponse,
  TelemetryHistoryQuery,
  TelemetryLiveHandlers,
  TelemetrySample,
} from "@/lib/telemetry/types";

const state = vi.hoisted(() => ({
  latest: vi.fn(),
  history: vi.fn(),
  subscribe: vi.fn(),
  handlers: null as TelemetryLiveHandlers | null,
  exportTelemetryCsv: vi.fn(),
}));

vi.mock("@/lib/telemetry/runtime-config", () => ({
  getTelemetryRuntimeConfig: () => ({
    mode: "live",
    apiBaseUrl: "http://127.0.0.1:8082",
    websocketUrl: "ws://127.0.0.1:8082/api/v1/telemetry/live",
  }),
}));

vi.mock("@/features/security/auth-runtime", () => ({
  createRuntimeCredentialProvider: () => vi.fn(),
}));

vi.mock("@/features/security/security-session", () => ({
  createAuthenticatedFetch: (fetchImpl: typeof fetch) => fetchImpl,
}));

vi.mock("@/lib/telemetry/create-adapter", () => ({
  createTelemetryAdapter: () => ({
    readiness: vi.fn(),
    latest: state.latest,
    history: state.history,
    subscribe: state.subscribe,
  }),
}));

vi.mock("@/features/live-dashboards/api-client", () => ({
  createLiveDashboardApiClient: () => ({ exportTelemetryCsv: state.exportTelemetryCsv }),
}));

import { useLiveDashboardTelemetry } from "./use-live-dashboard-telemetry";

const dashboard: LiveDashboard = {
  id: "dashboard-1",
  organization_id: "organization-1",
  name: "Temperatures",
  description: null,
  owner_subject: "operator-1",
  refresh_seconds: 1,
  time_window: "24h",
  version: 1,
  status: "active",
  created_by: "operator-1",
  updated_by: "operator-1",
  created_at: "2026-08-18T18:00:00.000Z",
  updated_at: "2026-08-18T18:00:00.000Z",
  archived_by: null,
  archived_at: null,
  items: [
    {
      id: "item-1",
      position: 1,
      channel_ref_id: "ref-1",
      channel_id: "106-03",
      metric: "temperature.probe",
      native_unit: "degC",
      visualization: "line",
      color: "#00C6E0",
      display_unit: "degC",
    },
  ],
};

function sample(eventId: string, capturedAt: string, value: number): TelemetrySample {
  return {
    event_id: eventId,
    node_id: "edge-1",
    captured_at: capturedAt,
    metric: "temperature.probe",
    value,
    unit: "degC",
    quality: "valid",
    source: "test",
    equipment_id: "controller-106",
    channel_id: "106-03",
    alarm: null,
    raw_value: value,
    raw_status: null,
  };
}

function historyResponse(
  items: TelemetrySample[],
  nextOffset: number | null,
  snapshotAt = "2026-08-18T20:00:00.000Z",
): TelemetryCollectionResponse {
  return {
    items,
    count: items.length,
    limit: 1000,
    offset: 0,
    next_offset: nextOffset,
    snapshot_at: snapshotAt,
  };
}

describe("useLiveDashboardTelemetry persisted history", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.handlers = null;
    state.latest.mockResolvedValue({
      items: [sample("latest", "2026-08-18T19:59:00.000Z", 5)],
      count: 1,
      limit: 1,
      offset: 0,
      next_offset: null,
    });
    state.subscribe.mockImplementation((_filters: unknown, handlers: TelemetryLiveHandlers) => {
      state.handlers = handlers;
      return { close: vi.fn() };
    });
    state.history.mockImplementation(async (query: TelemetryHistoryQuery) => {
      return query.snapshot_at
        ? historyResponse([sample("older", "2026-08-18T18:00:00.000Z", 3)], null)
        : historyResponse([sample("newer", "2026-08-18T19:00:00.000Z", 4)], 1000);
    });
  });

  it("loads every persisted page under one snapshot and keeps range changes UI-only", async () => {
    const { result } = renderHook(() =>
      useLiveDashboardTelemetry({
        dashboard,
        organizationId: "organization-1",
        enabled: true,
      }),
    );

    await waitFor(() => {
      expect(result.current.historyStatus).toBe("ready");
      expect(
        result.current.series[0]?.history.map((item) => item.event_id.replace("nexolab-live-segment:", "")),
      ).toEqual(expect.arrayContaining(["older", "newer"]));
    });

    expect(state.history).toHaveBeenCalledTimes(2);
    expect((state.history.mock.calls[0][0] as TelemetryHistoryQuery).snapshot_at).toBeUndefined();
    expect((state.history.mock.calls[1][0] as TelemetryHistoryQuery).snapshot_at).toBe(
      "2026-08-18T20:00:00.000Z",
    );
    expect(state.subscribe).toHaveBeenCalledTimes(1);
    expect(state.latest).toHaveBeenCalledTimes(1);

    act(() => result.current.selectHistoryPreset("1h"));

    await waitFor(() => {
      expect(result.current.historyRange.kind).toBe("1h");
      expect(result.current.historyStatus).toBe("ready");
      expect(state.history.mock.calls.length).toBeGreaterThan(2);
    });

    expect(state.subscribe).toHaveBeenCalledTimes(1);
    expect(state.latest).toHaveBeenCalledTimes(1);
  });

  it("reconciles a live tail after persisted bootstrap without replay duplicates", async () => {
    const { result } = renderHook(() =>
      useLiveDashboardTelemetry({
        dashboard,
        organizationId: "organization-1",
        enabled: true,
      }),
    );
    await waitFor(() => expect(result.current.historyStatus).toBe("ready"));
    const handlers = state.handlers!;
    const tail = sample("tail", "2026-08-18T20:00:05.000Z", 6);

    act(() => {
      handlers.onSample(tail);
      handlers.onSample(tail);
    });

    await waitFor(() => {
      expect(result.current.series[0]?.latest?.event_id).toBe("tail");
    });
    await new Promise((resolve) => setTimeout(resolve, 1_100));

    expect(result.current.series[0]?.history.filter((item) => item.event_id === "tail")).toHaveLength(1);
  });
});
