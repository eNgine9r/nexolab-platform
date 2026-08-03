import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TelemetryLiveHandlers } from "@/lib/telemetry/types";

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

describe("useEnergyTelemetry startup coverage", () => {
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
      items: [],
      count: 0,
      limit: 1000,
      offset: 0,
      next_offset: null,
      snapshot_at: SNAPSHOT_AT,
    });
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
});
