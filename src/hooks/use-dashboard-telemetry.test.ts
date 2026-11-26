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

/** Display history is reduced and re-identified; compare what is drawn: time and value. */
function drawn(samples: readonly TelemetrySample[]): Array<[string, number | null]> {
  return samples.map((item) => [item.captured_at, item.value]);
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
      expect(drawn(result.current.historySamples)).toEqual([[sample.captured_at, 4.2]]);
    });

    // The 24 h window loads as four 6 h time slices under one snapshot (P0 charts).
    const queries = adapterState.history.mock.calls.map((call) => call[0] as TelemetryHistoryQuery);
    expect(queries).toHaveLength(4);
    expect(queries[0].snapshot_at).toBeUndefined();
    for (const query of queries) {
      expect(query.node_id).toBeUndefined();
      expect(query.metric).toBe("temperature.probe");
      expect(query.limit).toBe(1000);
      expect(query.offset).toBe(0);
      expect(new Date(query.to).getTime() - new Date(query.from).getTime()).toBe(6 * 60 * 60 * 1000);
    }
    const spanFrom = Math.min(...queries.map((query) => new Date(query.from).getTime()));
    const spanTo = Math.max(...queries.map((query) => new Date(query.to).getTime()));
    expect(spanTo - spanFrom).toBe(24 * 60 * 60 * 1000);
    expect(result.current.historyStore?.columns).toBeDefined();

    act(() => {
      result.current.setHistoryRange("1h");
    });

    await waitFor(() => {
      expect(adapterState.history).toHaveBeenCalledTimes(5);
      expect(result.current.historyRange).toBe("1h");
      expect(result.current.historyStatus).toBe("ready");
    });
    const lastQuery = adapterState.history.mock.calls[4][0] as TelemetryHistoryQuery;
    expect(new Date(lastQuery.to).getTime() - new Date(lastQuery.from).getTime()).toBe(60 * 60 * 1000);
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
    // A range-aware API: [from, to), newest first, one row per page while more remain.
    adapterState.history.mockImplementation(async (query: TelemetryHistoryQuery) => {
      queries.push(query);
      const from = new Date(query.from).getTime();
      const to = new Date(query.to).getTime();
      const inRange = [newer, older].filter((item) => {
        const at = Date.parse(item.captured_at);
        return at >= from && at < to;
      });
      return inRange.length === 0
        ? historyResponse([])
        : historyResponse([inRange[0]], inRange.length > 1 ? 1000 : null);
    });

    const { result } = renderHook(() => useDashboardTelemetry());

    await waitFor(() => {
      expect(result.current.historyStatus).toBe("ready");
      expect(drawn(result.current.historySamples).map(([capturedAt]) => capturedAt)).toEqual([
        older.captured_at,
        newer.captured_at,
      ]);
    });

    // The newest slice needed a second page (next_offset 1000 is not "complete"); every later
    // request reuses the first snapshot and pages by the captured-time cursor, never by offset.
    const newestSlice = queries.filter(
      (query) => query.to === queries[0].to || new Date(query.to).getTime() > Date.parse(older.captured_at),
    );
    expect(newestSlice.length).toBeGreaterThan(1);
    expect(queries[0].snapshot_at).toBeUndefined();
    expect(queries.slice(1).every((query) => query.snapshot_at === "2026-08-18T19:30:00.000Z")).toBe(true);
    expect(queries.every((query) => query.offset === 0)).toBe(true);
    expect(new Date(newestSlice[1].to).getTime()).toBeLessThan(new Date(queries[0].to).getTime());
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

    // #1827: live history is coalesced (one update per 5 s for the default 24 h window). The
    // repeated and the delayed events are not replayed; the communication failure is a break in
    // the drawing and a non-valid poll in the RAW columns.
    await waitFor(
      () => {
        expect(drawn(result.current.historySamples)).toEqual([
          [persisted.captured_at, persisted.value],
          [newer.captured_at, 4.4],
        ]);
      },
      { timeout: 8_000 },
    );
    const columns = Object.values(result.current.historyStore?.columns ?? {})[0];
    expect(columns?.invalidTimestamps).toEqual([Date.parse(failure.captured_at)]);
    expect(columns?.validTimestamps).toEqual([
      Date.parse(persisted.captured_at),
      Date.parse(newer.captured_at),
    ]);
  }, 15_000);

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

  it("loads a custom period as a fixed window that live samples never extend (#1683)", async () => {
    const toMs = Date.now() - 2 * 60 * 60 * 1000;
    const fromMs = toMs - 3 * 60 * 60 * 1000;
    const inside = {
      ...sample,
      event_id: "inside-custom",
      captured_at: new Date(toMs - 60_000).toISOString(),
    };
    adapterState.history.mockResolvedValue(historyResponse([inside]));

    const { result } = renderHook(() => useDashboardTelemetry());
    await waitFor(() => expect(result.current.historyStatus).toBe("ready"));

    act(() => {
      result.current.applyCustomHistoryRange(fromMs, toMs);
    });
    await waitFor(() => {
      expect(result.current.historyRange).toBe("custom");
      expect(result.current.historyStatus).toBe("ready");
      expect(drawn(result.current.historySamples)).toEqual([[inside.captured_at, inside.value]]);
    });
    const customQuery = adapterState.history.mock.calls.at(-1)?.[0] as TelemetryHistoryQuery;
    expect(new Date(customQuery.from).getTime()).toBe(fromMs);
    expect(new Date(customQuery.to).getTime()).toBe(toMs);
    const expectedWindow = { from: new Date(fromMs).toISOString(), to: new Date(toMs).toISOString() };
    expect(result.current.historyWindow).toEqual(expectedWindow);

    const handlers = adapterState.handlers as TelemetryLiveHandlers;
    act(() => {
      handlers.onSample({ ...sample, event_id: "live-after-window", captured_at: new Date().toISOString() });
    });
    await waitFor(() => expect(result.current.status).toBe("live"));
    expect(drawn(result.current.historySamples)).toEqual([[inside.captured_at, inside.value]]);
    expect(result.current.historyWindow).toEqual(expectedWindow);
  });

  it("rejects an invalid custom period with an operator message and keeps the preset", async () => {
    const { result } = renderHook(() => useDashboardTelemetry());
    await waitFor(() => expect(result.current.historyStatus).toBe("ready"));
    const now = Date.now();

    expect(() => result.current.applyCustomHistoryRange(now - 1_000, now - 2_000)).toThrow(
      "Початок діапазону має бути раніше завершення.",
    );
    expect(() => result.current.applyCustomHistoryRange(now - 32 * 24 * 60 * 60 * 1000, now)).toThrow(
      "Діапазон не може перевищувати 31 день.",
    );
    expect(result.current.historyRange).toBe("24h");
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
