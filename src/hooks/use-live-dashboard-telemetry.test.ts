import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-08-18T20:00:00.000Z"));
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

  afterEach(() => {
    vi.useRealTimers();
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

  it("opens with the saved analysis view range instead of the dashboard default (#1666)", async () => {
    const { result } = renderHook(() =>
      useLiveDashboardTelemetry({
        dashboard: {
          ...dashboard,
          view_settings: {
            schema_version: 1,
            hidden_items: [],
            range_kind: "6h",
            range_from: null,
            range_to: null,
            viewport_from: null,
            viewport_to: null,
            density: null,
          },
        },
        organizationId: "organization-1",
        enabled: true,
      }),
    );

    await waitFor(() => {
      expect(result.current.historyRange.kind).toBe("6h");
      expect(result.current.historyStatus).toBe("ready");
    });
    // The first page of a load carries the full window; later pages only move `to` backwards.
    const ranges = state.history.mock.calls.map(([query]) => {
      const { from, to } = query as TelemetryHistoryQuery;
      return Date.parse(String(to)) - Date.parse(String(from));
    });
    expect(ranges).toContain(6 * 60 * 60_000);
    expect(ranges).not.toContain(24 * 60 * 60_000);
  });

  it("queries and subscribes to the exact selected standalone series", async () => {
    const item = {
      ...dashboard.items[0],
      node_id: "edge-1",
      equipment_id: "controller-106",
      channel_ref_id: null,
    };
    const scope = {
      node_id: item.node_id,
      equipment_id: item.equipment_id,
      channel_id: item.channel_id,
      metric: item.metric,
    };
    const { result } = renderHook(() =>
      useLiveDashboardTelemetry({
        dashboard: { ...dashboard, items: [item] },
        organizationId: "organization-1",
        enabled: true,
      }),
    );
    await waitFor(() => expect(result.current.historyStatus).toBe("ready"));
    expect(state.latest).toHaveBeenCalledWith(expect.objectContaining(scope), expect.anything());
    expect(state.history).toHaveBeenCalledWith(expect.objectContaining(scope), expect.anything());
    expect(state.subscribe).toHaveBeenCalledWith(scope, expect.anything());

    const tail = sample("standalone-tail", "2026-08-18T20:00:06.000Z", 7);
    act(() => {
      state.handlers!.onSample({ ...tail, equipment_id: "different-device", value: 99 });
      state.handlers!.onSample(tail);
    });
    await waitFor(() => expect(result.current.series[0]?.latest?.value).toBe(7));
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

    // The hour of silence before the tail is a real source gap (#1805), so the tail may start a new
    // segment; what matters here is that the replayed sample appears exactly once.
    expect(
      result.current.series[0]?.history.filter(
        (item) => item.event_id.replace("nexolab-live-segment:", "") === "tail",
      ),
    ).toHaveLength(1);
  });
});
