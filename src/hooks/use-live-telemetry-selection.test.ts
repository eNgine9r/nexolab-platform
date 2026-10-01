import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { liveChannelKey } from "@/features/live/live-telemetry";
import type { TelemetryLiveHandlers, TelemetrySample } from "@/lib/telemetry/types";

const state = vi.hoisted(() => ({
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
vi.mock("@/features/security/supabase-auth", () => ({
  createRuntimeCredentialProvider: () => vi.fn(),
}));
vi.mock("@/features/security/security-session", () => ({
  createAuthenticatedFetch: (fetchImpl: typeof fetch) => fetchImpl,
}));
vi.mock("@/lib/telemetry/create-adapter", () => ({
  createTelemetryAdapter: () => ({
    latest: state.latest,
    history: state.history,
    subscribe: state.subscribe,
  }),
}));

import { useLiveTelemetry } from "./use-live-telemetry";

const sample: TelemetrySample = {
  event_id: "sample-1",
  node_id: "edge-1",
  equipment_id: "K106",
  channel_id: "106-03",
  captured_at: new Date().toISOString(),
  metric: "temperature.probe",
  value: 4.2,
  unit: "degC",
  quality: "valid",
  source: "unit-test",
  alarm: null,
  raw_value: null,
  raw_status: null,
};

function page(items: TelemetrySample[]) {
  return { items, count: items.length, limit: 1000, offset: 0, next_offset: null };
}

beforeEach(() => {
  state.handlers = null;
  state.latest.mockReset();
  state.history.mockReset();
  state.subscribe.mockReset();
  state.history.mockResolvedValue(page([]));
  state.subscribe.mockImplementation((_, handlers: TelemetryLiveHandlers) => {
    state.handlers = handlers;
    return { close: vi.fn() };
  });
});

async function connect() {
  await waitFor(() => expect(state.handlers).not.toBeNull());
  act(() => state.handlers!.onStateChange?.("connected"));
}

describe("complete inventory selection readiness", () => {
  it("does not authorize persistence while the inventory request is pending", async () => {
    state.latest.mockReturnValue(new Promise(() => undefined));
    const view = renderHook(() =>
      useLiveTelemetry({ organizationId: "org-a", initialSelectedKeys: [liveChannelKey(sample)] }),
    );
    await connect();
    await waitFor(() => expect(state.latest).toHaveBeenCalled());
    expect(view.result.current.selectionReady).toBe(false);
    view.unmount();
  });

  it("retains remembered state across failed startup and successful retry", async () => {
    state.latest.mockRejectedValueOnce(new Error("Inventory unavailable"));
    state.latest.mockResolvedValue(page([sample]));
    const key = liveChannelKey(sample);
    const view = renderHook(() => useLiveTelemetry({ organizationId: "org-a", initialSelectedKeys: [key] }));
    await connect();
    await waitFor(() => expect(view.result.current.error?.message).toBe("Inventory unavailable"));
    expect(view.result.current.selectionReady).toBe(false);
    expect(view.result.current.selectedKeys).toEqual([]);
    act(() => view.result.current.retry());
    await waitFor(() => expect(state.subscribe).toHaveBeenCalledTimes(2));
    await connect();
    await waitFor(() => expect(view.result.current.selectionReady).toBe(true));
    expect(view.result.current.selectedKeys).toEqual([key]);
    view.unmount();
  });

  it("pauses persistence before clearing a previously ready inventory on retry", async () => {
    state.latest.mockResolvedValueOnce(page([sample]));
    let resolveInventory: (value: ReturnType<typeof page>) => void = () => undefined;
    state.latest.mockImplementationOnce(
      () =>
        new Promise<ReturnType<typeof page>>((resolve) => {
          resolveInventory = resolve;
        }),
    );
    const key = liveChannelKey(sample);
    const view = renderHook(() => useLiveTelemetry({ organizationId: "org-a", initialSelectedKeys: [key] }));
    await connect();
    await waitFor(() => expect(view.result.current.selectionReady).toBe(true));
    expect(view.result.current.selectedKeys).toEqual([key]);
    act(() => view.result.current.retry());
    await waitFor(() => expect(state.subscribe).toHaveBeenCalledTimes(2));
    await connect();
    await waitFor(() => expect(state.latest).toHaveBeenCalledTimes(2));
    expect(view.result.current.selectionReady).toBe(false);
    act(() => resolveInventory(page([sample])));
    await waitFor(() => expect(view.result.current.selectionReady).toBe(true));
    expect(view.result.current.selectedKeys).toEqual([key]);
    view.unmount();
  });

  it("reconciles unavailable channels only after a complete successful inventory", async () => {
    state.latest.mockResolvedValue(page([]));
    const view = renderHook(() =>
      useLiveTelemetry({ organizationId: "org-a", initialSelectedKeys: ["missing"] }),
    );
    await connect();
    await waitFor(() => expect(view.result.current.selectionReady).toBe(true));
    expect(view.result.current.selectedKeys).toEqual([]);
    view.unmount();
  });
});
