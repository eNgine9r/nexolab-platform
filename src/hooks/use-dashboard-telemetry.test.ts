import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  TelemetryCollectionResponse,
  TelemetryHistoryQuery,
  TelemetryLiveHandlers,
  TelemetrySample,
} from "@/lib/telemetry/types";

const adapterState = vi.hoisted(() => ({
  latest: vi.fn(),
  history: vi.fn(),
  subscribe: vi.fn(),
  handlers: null as unknown,
}));

vi.mock("@/lib/telemetry/runtime-config", () => ({
  getTelemetryRuntimeConfig: () => ({
    mode: "live",
    apiBaseUrl: "http://127.0.0.1:8082",
    websocketUrl: "ws://127.0.0.1:8082/api/v1/telemetry/live",
  }),
}));

vi.mock("@/lib/telemetry/create-adapter", () => ({
  createTelemetryAdapter: () => ({
    readiness: vi.fn(),
    history: adapterState.history,
    latest: adapterState.latest,
    subscribe: adapterState.subscribe,
  }),
}));

import { useDashboardTelemetry } from "./use-dashboard-telemetry";

const sample: TelemetrySample = {
  event_id: "recovered-event",
  node_id: "edge-01",
  captured_at: new Date().toISOString(),
  metric: "temperature.probe",
  value: 4.2,
  unit: "degC",
  quality: "valid",
  source: "modbus",
  equipment_id: "xjp60d-106",
  channel_id: "106-03",
  alarm: null,
  raw_value: 42,
  raw_status: null,
};

function historyResponse(
  items: TelemetrySample[],
  nextOffset: number | null = null,
  snapshotAt = "2026-08-18T19:30:00.000Z",
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

describe("useDashboardTelemetry", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    adapterState.handlers = null;

    adapterState.latest.mockResolvedValue({
      items: [],
      count: 0,
      limit: 1000,
      offset: 0,
      next_offset: null,
    });
    adapterState.history.mockResolvedValue(historyResponse([sample]));
    adapterState.subscribe.mockImplementation((_filters: unknown, handlers: TelemetryLiveHandlers) => {
      adapterState.handlers = handlers;
      return { close: vi.fn() };
    });
  });

  it("clears transient transport errors after reconnect and a committed sample", async () => {
    const { result } = renderHook(() => useDashboardTelemetry());

    await waitFor(() => {
      expect(adapterState.subscribe).toHaveBeenCalledOnce();
    });
    expect(adapterState.latest).toHaveBeenCalledWith({ limit: 1000 }, expect.any(AbortSignal));
    expect(adapterState.subscribe).toHaveBeenCalledWith({}, expect.any(Object));

    const handlers = adapterState.handlers as TelemetryLiveHandlers;

    act(() => {
      handlers.onError?.(new Error("Telemetry WebSocket transport error"));
    });

    await waitFor(() => {
      expect(result.current.error?.message).toBe("Telemetry WebSocket transport error");
    });

    act(() => {
      handlers.onStateChange?.("connected");
    });

    await waitFor(() => {
      expect(result.current.error).toBeNull();
    });

    act(() => {
      handlers.onError?.(new Error("Temporary reconnect error"));
    });

    await waitFor(() => {
      expect(result.current.error?.message).toBe("Temporary reconnect error");
    });

    act(() => {
      handlers.onSample(sample);
    });

    await waitFor(() => {
      expect(result.current.error).toBeNull();
      expect(result.current.status).toBe("live");
    });
  });

  it("loads authenticated complete history and reloads the selected time range", async () => {
    const { result } = renderHook(() => useDashboardTelemetry({ enabled: true, organizationId: "org-1" }));

    await waitFor(() => {
      expect(result.current.historyStatus).toBe("ready");
      expect(result.current.historySamples).toEqual([sample]);
    });

    const firstQuery = adapterState.history.mock.calls[0][0] as TelemetryHistoryQuery;
    expect(firstQuery.node_id).toBeUndefined();
    expect(firstQuery.metric).toBe("temperature.probe");
    expect(firstQuery.limit).toBe(1000);
    expect(firstQuery.offset).toBe(0);
    expect(firstQuery.snapshot_at).toBeUndefined();
    expect(new Date(firstQuery.to).getTime() - new Date(firstQuery.from).getTime()).toBe(24 * 60 * 60 * 1000);

    act(() => {
      result.current.setHistoryRange("1h");
    });

    await waitFor(() => {
      expect(adapterState.history).toHaveBeenCalledTimes(2);
      expect(result.current.historyRange).toBe("1h");
      expect(result.current.historyStatus).toBe("ready");
    });
    const secondQuery = adapterState.history.mock.calls[1][0] as TelemetryHistoryQuery;
    expect(new Date(secondQuery.to).getTime() - new Date(secondQuery.from).getTime()).toBe(60 * 60 * 1000);
  });

  it("loads every persisted page against one snapshot instead of treating 1000 as complete", async () => {
    const newer = {
      ...sample,
      event_id: "newer",
      captured_at: new Date(Date.now() - 60_000).toISOString(),
    };
    const older = {
      ...sample,
      event_id: "older",
      captured_at: new Date(Date.now() - 2 * 60_000).toISOString(),
    };
    const queries: TelemetryHistoryQuery[] = [];
    adapterState.history.mockImplementation(async (query: TelemetryHistoryQuery) => {
      queries.push(query);
      return queries.length === 1 ? historyResponse([newer], 1000) : historyResponse([older], null);
    });

    const { result } = renderHook(() => useDashboardTelemetry());

    await waitFor(() => {
      expect(result.current.historyStatus).toBe("ready");
      expect(result.current.historySamples.map((item) => item.event_id)).toEqual(["older", "newer"]);
    });

    expect(queries).toHaveLength(2);
    expect(queries[0].snapshot_at).toBeUndefined();
    expect(queries[1].snapshot_at).toBe("2026-08-18T19:30:00.000Z");
    expect(queries[1].offset).toBe(0);
    expect(new Date(queries[1].to).getTime()).toBeLessThan(new Date(queries[0].to).getTime());
  });

  it("reconciles persisted history with live tail without duplicates or backward replay", async () => {
    const persisted = {
      ...sample,
      event_id: "persisted",
      captured_at: new Date(Date.now() - 10_000).toISOString(),
    };
    adapterState.history.mockResolvedValue(historyResponse([persisted]));

    const { result } = renderHook(() => useDashboardTelemetry());
    await waitFor(() => {
      expect(result.current.historyStatus).toBe("ready");
      expect(adapterState.subscribe).toHaveBeenCalledOnce();
    });

    const handlers = adapterState.handlers as TelemetryLiveHandlers;
    const delayed = {
      ...persisted,
      event_id: "delayed",
      captured_at: new Date(Date.parse(persisted.captured_at) - 5_000).toISOString(),
    };
    const newer = {
      ...persisted,
      event_id: "newer-tail",
      captured_at: new Date(Date.parse(persisted.captured_at) + 15_000).toISOString(),
      value: 4.4,
    };
    const failure = {
      ...persisted,
      event_id: "communication-failure",
      captured_at: new Date(Date.parse(newer.captured_at) + 5_000).toISOString(),
      quality: "communication_error" as const,
      value: null,
    };

    act(() => {
      handlers.onSample({ ...persisted });
      handlers.onSample(delayed);
      handlers.onSample(newer);
      handlers.onSample(newer);
      handlers.onSample(failure);
    });

    await waitFor(() => {
      expect(result.current.historySamples.map((item) => item.event_id)).toEqual([
        "persisted",
        "newer-tail",
        "communication-failure",
      ]);
    });
  });

  it("filters only chart temperature series while keeping the full dashboard view", async () => {
    adapterState.latest.mockResolvedValue({
      items: [sample],
      count: 1,
      limit: 1000,
      offset: 0,
      next_offset: null,
    });

    const { result } = renderHook(() => useDashboardTelemetry({ temperatureChannelIds: ["108-01"] }));

    await waitFor(() => {
      expect(result.current.view?.samples.map((item) => item.event_id)).toEqual(["recovered-event"]);
    });
    expect(result.current.temperatures).toEqual([]);
    await waitFor(() => expect(result.current.historyStatus).toBe("ready"));
    expect(result.current.historySamples).toEqual([]);
  });

  it("hides history immediately when the organization scope changes", async () => {
    const { result, rerender } = renderHook(
      ({ organizationId }) => useDashboardTelemetry({ enabled: true, organizationId }),
      { initialProps: { organizationId: "org-1" } },
    );
    await waitFor(() => expect(result.current.historyStatus).toBe("ready"));

    rerender({ organizationId: "org-2" });
    expect(result.current.historySamples).toEqual([]);
    expect(result.current.historyStatus).toBe("loading");
  });
});
