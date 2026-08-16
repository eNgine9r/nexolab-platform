import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ENERGY_HISTORY_RECONCILIATION_OVERLAP_MS,
  resetRetainedEnergyHistoryForTests,
} from "@/features/energy/energy-history-retention";
import type { TelemetryHistoryQuery, TelemetryLiveHandlers, TelemetrySample } from "@/lib/telemetry/types";

const adapterState = vi.hoisted(() => ({
  latest: vi.fn(),
  history: vi.fn(),
  subscribe: vi.fn(),
  handlers: null as TelemetryLiveHandlers | null,
}));

vi.mock("@/lib/telemetry/runtime-config", () => ({
  getTelemetryRuntimeConfig: () => ({
    mode: "live",
    apiBaseUrl: "http://127.0.0.1:8082",
    websocketUrl: "ws://127.0.0.1:8082/api/v1/telemetry/live",
  }),
}));

vi.mock("@/features/security/security-session", () => ({
  createAuthenticatedFetch: () => vi.fn(),
}));

vi.mock("@/features/security/supabase-auth", () => ({
  createRuntimeCredentialProvider: () => vi.fn(),
}));

vi.mock("@/lib/telemetry/create-adapter", () => ({
  createTelemetryAdapter: () => ({
    readiness: vi.fn(),
    latest: adapterState.latest,
    history: adapterState.history,
    subscribe: adapterState.subscribe,
  }),
}));

import { useEnergyTelemetry } from "./use-energy-telemetry";

const SNAPSHOT_AT = "2026-08-03T20:00:00.000Z";

function energySample(eventId: string, capturedAt: string): TelemetrySample {
  return {
    event_id: eventId,
    node_id: "edge-01",
    captured_at: capturedAt,
    metric: "electrical.power.active",
    value: 420,
    unit: "W",
    quality: "valid",
    source: "modbus",
    equipment_id: "LE01MP-200",
    channel_id: "200-power-active",
    alarm: null,
    raw_value: 420,
    raw_status: 0,
    received_at: capturedAt,
  };
}

function emptyHistoryResponse() {
  return {
    items: [],
    count: 0,
    limit: 1000,
    offset: 0,
    next_offset: null,
    snapshot_at: SNAPSHOT_AT,
  };
}

describe("useEnergyTelemetry startup coverage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetRetainedEnergyHistoryForTests();
    adapterState.handlers = null;
    adapterState.latest.mockResolvedValue({
      items: [],
      count: 0,
      limit: 1000,
      offset: 0,
      next_offset: null,
    });
    adapterState.history.mockResolvedValue(emptyHistoryResponse());
    adapterState.subscribe.mockImplementation((_filters: unknown, handlers: TelemetryLiveHandlers) => {
      adapterState.handlers = handlers;
      return { close: vi.fn() };
    });
  });

  it("does not load history before authenticated WebSocket coverage", async () => {
    const { result } = renderHook(() => useEnergyTelemetry());

    await waitFor(() => expect(adapterState.subscribe).toHaveBeenCalledOnce());
    expect(adapterState.latest).not.toHaveBeenCalled();
    expect(adapterState.history).not.toHaveBeenCalled();

    act(() => {
      adapterState.handlers?.onStateChange?.("connected");
    });

    await waitFor(() => {
      expect(adapterState.latest).toHaveBeenCalledOnce();
      expect(adapterState.history).toHaveBeenCalledOnce();
      expect(result.current.historyStatus).toBe("ready");
    });
  });

  it("fails history explicitly when initial WebSocket coverage is unavailable", async () => {
    const { result } = renderHook(() => useEnergyTelemetry());

    await waitFor(() => expect(adapterState.subscribe).toHaveBeenCalledOnce());

    act(() => {
      adapterState.handlers?.onStateChange?.("offline");
    });

    await waitFor(() => {
      expect(result.current.historyStatus).toBe("error");
      expect(result.current.historyError?.message).toContain("authenticated live coverage");
    });
    expect(adapterState.latest).not.toHaveBeenCalled();
    expect(adapterState.history).not.toHaveBeenCalled();
  });

  it("reuses a five-page Energy bootstrap across a warm remount and fetches only the missing tail", async () => {
    let bootstrapPagesRemaining = 5;
    let bootstrapSequence = 0;

    adapterState.history.mockImplementation((query: TelemetryHistoryQuery) => {
      if (bootstrapPagesRemaining > 0) {
        bootstrapSequence += 1;
        const queryTo = Date.parse(query.to instanceof Date ? query.to.toISOString() : query.to);
        const capturedAt = new Date(queryTo - 60 * 60 * 1000).toISOString();
        const response = {
          items: [energySample(`bootstrap-${bootstrapSequence}`, capturedAt)],
          count: 1,
          limit: 1000,
          offset: 0,
          next_offset: bootstrapPagesRemaining > 1 ? 1 : null,
          snapshot_at: SNAPSHOT_AT,
        };
        bootstrapPagesRemaining -= 1;
        return Promise.resolve(response);
      }
      return Promise.resolve(emptyHistoryResponse());
    });

    const first = renderHook(() =>
      useEnergyTelemetry({
        organizationId: "org-a",
        securityScopeId: "user-a",
      }),
    );

    await waitFor(() => expect(adapterState.subscribe).toHaveBeenCalledTimes(1));
    act(() => {
      adapterState.handlers?.onStateChange?.("connected");
    });

    await waitFor(() => {
      expect(adapterState.history).toHaveBeenCalledTimes(5);
      expect(first.result.current.historyStatus).toBe("ready");
      expect(first.result.current.historySamples.length).toBeGreaterThan(0);
    });

    const coldFirstQuery = adapterState.history.mock.calls[0][0] as TelemetryHistoryQuery;
    const retainedWindow = first.result.current.historyWindow;
    expect(retainedWindow).not.toBeNull();
    first.unmount();

    const second = renderHook(() =>
      useEnergyTelemetry({
        organizationId: "org-a",
        securityScopeId: "user-a",
      }),
    );

    expect(second.result.current.historyStatus).toBe("ready");
    expect(second.result.current.historySamples.length).toBeGreaterThan(0);

    await waitFor(() => expect(adapterState.subscribe).toHaveBeenCalledTimes(2));
    act(() => {
      adapterState.handlers?.onStateChange?.("connected");
    });

    await waitFor(() => {
      expect(adapterState.history).toHaveBeenCalledTimes(6);
      expect(second.result.current.historyStatus).toBe("ready");
    });

    const warmQuery = adapterState.history.mock.calls[5][0] as TelemetryHistoryQuery;
    const coldFrom = Date.parse(
      coldFirstQuery.from instanceof Date ? coldFirstQuery.from.toISOString() : coldFirstQuery.from,
    );
    const warmFrom = Date.parse(
      warmQuery.from instanceof Date ? warmQuery.from.toISOString() : warmQuery.from,
    );
    const retainedTo = Date.parse(retainedWindow!.to);

    expect(warmFrom - coldFrom).toBeGreaterThan(
      23 * 60 * 60 * 1000 - ENERGY_HISTORY_RECONCILIATION_OVERLAP_MS,
    );
    expect(retainedTo - warmFrom).toBeGreaterThanOrEqual(ENERGY_HISTORY_RECONCILIATION_OVERLAP_MS - 5_000);
    expect(retainedTo - warmFrom).toBeLessThanOrEqual(ENERGY_HISTORY_RECONCILIATION_OVERLAP_MS + 5_000);
  });

  it("does not reuse retained history for another security identity in the same organization", async () => {
    const first = renderHook(() =>
      useEnergyTelemetry({
        organizationId: "org-a",
        securityScopeId: "user-a",
      }),
    );

    await waitFor(() => expect(adapterState.subscribe).toHaveBeenCalledTimes(1));
    act(() => {
      adapterState.handlers?.onStateChange?.("connected");
    });
    await waitFor(() => expect(adapterState.history).toHaveBeenCalledTimes(1));
    first.unmount();

    const second = renderHook(() =>
      useEnergyTelemetry({
        organizationId: "org-a",
        securityScopeId: "user-b",
      }),
    );

    expect(second.result.current.historyStatus).toBe("loading");
    expect(second.result.current.historySamples).toEqual([]);

    await waitFor(() => expect(adapterState.subscribe).toHaveBeenCalledTimes(2));
    act(() => {
      adapterState.handlers?.onStateChange?.("connected");
    });
    await waitFor(() => expect(adapterState.history).toHaveBeenCalledTimes(2));
  });

  it("invalidates retained history on explicit history Retry so the selected range reloads completely", async () => {
    const { result } = renderHook(() =>
      useEnergyTelemetry({
        organizationId: "org-a",
        securityScopeId: "user-a",
      }),
    );

    await waitFor(() => expect(adapterState.subscribe).toHaveBeenCalledOnce());
    act(() => {
      adapterState.handlers?.onStateChange?.("connected");
    });
    await waitFor(() => {
      expect(adapterState.history).toHaveBeenCalledTimes(1);
      expect(result.current.historyStatus).toBe("ready");
    });

    act(() => {
      result.current.retryHistory();
    });

    await waitFor(() => expect(adapterState.history).toHaveBeenCalledTimes(2));

    const retryQuery = adapterState.history.mock.calls[1][0] as TelemetryHistoryQuery;
    const from = Date.parse(
      retryQuery.from instanceof Date ? retryQuery.from.toISOString() : retryQuery.from,
    );
    const to = Date.parse(retryQuery.to instanceof Date ? retryQuery.to.toISOString() : retryQuery.to);
    expect(to - from).toBeGreaterThanOrEqual(23 * 60 * 60 * 1000);
  });
});
