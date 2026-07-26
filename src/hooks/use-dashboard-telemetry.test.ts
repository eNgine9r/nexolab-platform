import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TelemetryHistoryQuery, TelemetryLiveHandlers, TelemetrySample } from "@/lib/telemetry/types";

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
    adapterState.history.mockResolvedValue({
      items: [sample],
      count: 1,
      limit: 1000,
      offset: 0,
      next_offset: null,
    });
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

  it("loads authenticated history and reloads the selected time range", async () => {
    const { result } = renderHook(() => useDashboardTelemetry({ enabled: true, organizationId: "org-1" }));

    await waitFor(() => {
      expect(result.current.historyStatus).toBe("ready");
      expect(result.current.historySamples).toEqual([sample]);
    });

    const firstQuery = adapterState.history.mock.calls[0][0] as TelemetryHistoryQuery;
    expect(firstQuery.node_id).toBe("edge-01");
    expect(firstQuery.metric).toBe("temperature.probe");
    expect(new Date(firstQuery.to).getTime() - new Date(firstQuery.from).getTime()).toBe(24 * 60 * 60 * 1000);

    act(() => {
      result.current.setHistoryRange("1h");
    });

    await waitFor(() => {
      expect(adapterState.history).toHaveBeenCalledTimes(2);
      expect(result.current.historyRange).toBe("1h");
    });
    const secondQuery = adapterState.history.mock.calls[1][0] as TelemetryHistoryQuery;
    expect(new Date(secondQuery.to).getTime() - new Date(secondQuery.from).getTime()).toBe(60 * 60 * 1000);
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
