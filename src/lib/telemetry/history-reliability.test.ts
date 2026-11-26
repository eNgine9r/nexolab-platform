import { describe, expect, it, vi } from "vitest";

import { TelemetryClientError } from "./errors";
import {
  fetchHistoryPageWithRetry,
  isRetryableHistoryError,
  loadCompleteTelemetryHistory,
  loadCompleteTelemetryHistoryForSeries,
} from "./history";
import { RequestLimiter } from "./request-limiter";
import { TelemetryRestClient, type TelemetryFetch } from "./rest-client";
import type {
  TelemetryAdapter,
  TelemetryCollectionResponse,
  TelemetryHistoryQuery,
  TelemetrySample,
} from "./types";

const SNAPSHOT = "2026-11-26T12:00:00.000Z";
const window = { from: new Date("2026-11-26T11:00:00Z"), to: new Date("2026-11-26T12:00:00Z") };

function sample(channelId: string, capturedAt: string): TelemetrySample {
  return {
    event_id: `${channelId}-${capturedAt}`,
    node_id: "edge-01",
    captured_at: capturedAt,
    metric: "temperature",
    value: 4,
    unit: "degC",
    quality: "valid",
    source: "test",
    equipment_id: "XJP60D-1",
    channel_id: channelId,
    alarm: null,
    raw_value: 40,
    raw_status: null,
  };
}

function page(items: TelemetrySample[], snapshotAt = SNAPSHOT): TelemetryCollectionResponse {
  return { items, count: items.length, limit: 1_000, offset: 0, next_offset: null, snapshot_at: snapshotAt };
}

function adapter(history: TelemetryAdapter["history"]): TelemetryAdapter {
  return { history, latest: vi.fn(), readiness: vi.fn(), subscribe: vi.fn() } as unknown as TelemetryAdapter;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe("history request limiter (#1809)", () => {
  it("never runs more than the configured number of requests at once", async () => {
    const limiter = new RequestLimiter(3);
    let active = 0;
    let peak = 0;
    const gates = Array.from({ length: 8 }, () => deferred<void>());
    const runs = gates.map((gate) =>
      limiter.run(undefined, async () => {
        active += 1;
        peak = Math.max(peak, active);
        await gate.promise;
        active -= 1;
      }),
    );
    await Promise.resolve();
    expect(limiter.inFlight).toBe(3);
    expect(limiter.queued).toBe(5);
    for (const gate of gates) gate.resolve();
    await Promise.all(runs);
    expect(peak).toBe(3);
    expect(limiter.inFlight).toBe(0);
  });

  it("removes an aborted request from the queue without running it", async () => {
    const limiter = new RequestLimiter(1);
    const gate = deferred<void>();
    const running = limiter.run(undefined, () => gate.promise);
    const controller = new AbortController();
    const task = vi.fn(async () => "never");
    const queued = limiter.run(controller.signal, task);
    controller.abort();
    await expect(queued).rejects.toMatchObject({ code: "aborted" });
    gate.resolve();
    await running;
    expect(task).not.toHaveBeenCalled();
    expect(limiter.queued).toBe(0);
  });

  it("starts the request timeout only when a queued history page is actually sent", async () => {
    const limiter = new RequestLimiter(1);
    const fetchMock = vi.fn<TelemetryFetch>().mockImplementation(async () => {
      await new Promise((resolve) => setTimeout(resolve, 100));
      return new Response(JSON.stringify(page([])), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    const client = new TelemetryRestClient("http://127.0.0.1:8082", {
      fetch: fetchMock,
      timeoutMs: 400,
      historyLimiter: limiter,
    });
    const query: TelemetryHistoryQuery = { from: window.from, to: window.to, limit: 10 };
    // Six pages of 100 ms each through one slot: with a timer started at enqueue, the last pages
    // would exceed 400 ms while still waiting for their turn.
    const pages = await Promise.all(Array.from({ length: 6 }, () => client.history(query)));
    expect(pages).toHaveLength(6);
  });
});

describe("history page retry (#1809)", () => {
  it("classifies timeouts, network failures and overload statuses as retryable", () => {
    expect(isRetryableHistoryError(new TelemetryClientError("timeout", "t"))).toBe(true);
    expect(isRetryableHistoryError(new TelemetryClientError("network", "n"))).toBe(true);
    expect(isRetryableHistoryError(new TelemetryClientError("http", "s", { status: 503 }))).toBe(true);
    expect(isRetryableHistoryError(new TelemetryClientError("http", "s", { status: 422 }))).toBe(false);
    expect(isRetryableHistoryError(new TelemetryClientError("aborted", "a"))).toBe(false);
    expect(isRetryableHistoryError(new TelemetryClientError("contract", "c"))).toBe(false);
  });

  it("retries a timed-out and an overloaded page, then loads the chart", async () => {
    const history = vi
      .fn<TelemetryAdapter["history"]>()
      .mockRejectedValueOnce(new TelemetryClientError("timeout", "Telemetry request exceeded 8000 ms"))
      .mockRejectedValueOnce(new TelemetryClientError("http", "busy", { status: 503 }))
      .mockResolvedValueOnce(page([sample("ch-1", "2026-11-26T11:30:00.000Z")]));

    const result = await loadCompleteTelemetryHistory(adapter(history), {}, window, {
      retryDelaysMs: [1, 1],
    });

    expect(result.samples).toHaveLength(1);
    expect(history).toHaveBeenCalledTimes(3);
  });

  it("gives up after the bounded retries and does not retry a client error", async () => {
    const overloaded = vi
      .fn<TelemetryAdapter["history"]>()
      .mockRejectedValue(new TelemetryClientError("http", "busy", { status: 503 }));
    await expect(
      fetchHistoryPageWithRetry(adapter(overloaded), { from: window.from, to: window.to }, undefined, [1, 1]),
    ).rejects.toMatchObject({ status: 503 });
    expect(overloaded).toHaveBeenCalledTimes(3);

    const invalid = vi
      .fn<TelemetryAdapter["history"]>()
      .mockRejectedValue(new TelemetryClientError("http", "bad", { status: 422 }));
    await expect(
      fetchHistoryPageWithRetry(adapter(invalid), { from: window.from, to: window.to }, undefined, [1, 1]),
    ).rejects.toMatchObject({ status: 422 });
    expect(invalid).toHaveBeenCalledTimes(1);
  });

  it("stops retrying when the load is aborted", async () => {
    const controller = new AbortController();
    const history = vi.fn<TelemetryAdapter["history"]>().mockImplementation(async () => {
      controller.abort();
      throw new TelemetryClientError("timeout", "slow");
    });
    await expect(
      fetchHistoryPageWithRetry(
        adapter(history),
        { from: window.from, to: window.to },
        controller.signal,
        [1, 1],
      ),
    ).rejects.toBeInstanceOf(TelemetryClientError);
    expect(history).toHaveBeenCalledTimes(1);
  });
});

describe("parallel multi-series history (#1809)", () => {
  it("loads every series under the snapshot fixed by the first page, in parallel", async () => {
    const firstPage = deferred<TelemetryCollectionResponse>();
    const queries: TelemetryHistoryQuery[] = [];
    const history = vi.fn<TelemetryAdapter["history"]>().mockImplementation(async (query) => {
      queries.push(query);
      if (query.channel_id === "ch-1") return firstPage.promise;
      return page([sample(String(query.channel_id), "2026-11-26T11:30:00.000Z")]);
    });

    const loading = loadCompleteTelemetryHistoryForSeries(
      adapter(history),
      [{ channel_id: "ch-1" }, { channel_id: "ch-2" }, { channel_id: "ch-3" }],
      window,
      { retryDelaysMs: [] },
    );
    await Promise.resolve();
    // Only the first page is in flight until it fixes the snapshot.
    expect(queries.map((query) => query.channel_id)).toEqual(["ch-1"]);
    firstPage.resolve(page([sample("ch-1", "2026-11-26T11:30:00.000Z")]));
    const results = await loading;

    expect(results.map((result) => result.samples[0].channel_id)).toEqual(["ch-1", "ch-2", "ch-3"]);
    expect(results.every((result) => result.snapshotAt === SNAPSHOT)).toBe(true);
    expect(queries.slice(1).every((query) => query.snapshot_at === SNAPSHOT)).toBe(true);
  });

  it("completes series in order with at most `seriesConcurrency` series in flight (#1824)", async () => {
    const inFlight = new Set<string>();
    let peak = 0;
    let requests = 0;
    const pagesServed = new Map<string, number>();
    const history = vi.fn<TelemetryAdapter["history"]>().mockImplementation(async (query) => {
      const channel = String(query.channel_id);
      requests += 1;
      inFlight.add(channel);
      peak = Math.max(peak, inFlight.size);
      await new Promise((resolve) => setTimeout(resolve, 1));
      inFlight.delete(channel);
      // Three pages per series, paged backwards by the captured-time cursor.
      const served = (pagesServed.get(channel) ?? 0) + 1;
      pagesServed.set(channel, served);
      const capturedAt = new Date(Date.parse("2026-11-26T12:00:00Z") - served * 600_000).toISOString();
      return { ...page([sample(channel, capturedAt)]), next_offset: served < 3 ? 1 : null };
    });
    const completed: number[] = [];
    const filters = Array.from({ length: 6 }, (_, index) => ({ channel_id: `ch-${index + 1}` }));

    const results = await loadCompleteTelemetryHistoryForSeries(
      adapter(history),
      filters,
      window,
      { retryDelaysMs: [], pageSize: 2, seriesConcurrency: 3 },
      (result, index) => {
        completed.push(index);
        return result;
      },
    );

    expect(requests).toBe(18);
    expect(peak).toBe(3);
    expect(results.map((result) => result.samples.length)).toEqual([3, 3, 3, 3, 3, 3]);
    // The first three finish before any of the last three: progressive, not all at the end.
    expect(completed.slice(0, 3).sort()).toEqual([0, 1, 2]);
    expect(completed.slice(3).sort()).toEqual([3, 4, 5]);
  });

  it("aborts the remaining series after the first failure", async () => {
    const signals: AbortSignal[] = [];
    const history = vi.fn<TelemetryAdapter["history"]>().mockImplementation(async (query, signal) => {
      if (signal) signals.push(signal);
      if (query.channel_id === "ch-2") throw new TelemetryClientError("http", "bad", { status: 422 });
      if (query.channel_id === "ch-1") return page([sample("ch-1", "2026-11-26T11:30:00.000Z")]);
      return new Promise<TelemetryCollectionResponse>(() => undefined);
    });

    await expect(
      loadCompleteTelemetryHistoryForSeries(
        adapter(history),
        [{ channel_id: "ch-1" }, { channel_id: "ch-2" }, { channel_id: "ch-3" }],
        window,
        { retryDelaysMs: [] },
      ),
    ).rejects.toMatchObject({ status: 422 });
    expect(signals.at(-1)?.aborted).toBe(true);
  });
});
