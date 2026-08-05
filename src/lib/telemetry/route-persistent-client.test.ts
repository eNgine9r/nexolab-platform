import { afterEach, describe, expect, it, vi } from "vitest";

import {
  resetRoutePersistentTelemetryStateForTests,
  RoutePersistentTelemetryClient,
  type TelemetryLiveSource,
} from "./route-persistent-client";
import type {
  TelemetryConnectionState,
  TelemetryFilters,
  TelemetryLiveHandlers,
  TelemetrySample,
  TelemetrySubscription,
} from "./types";

const firstSample: TelemetrySample = {
  event_id: "event-1",
  node_id: "edge-01",
  captured_at: "2026-08-05T14:00:00.000Z",
  metric: "temperature.probe",
  value: 3.8,
  unit: "degC",
  quality: "valid",
  source: "dixell-xjp60d",
  equipment_id: "xjp60d-106",
  channel_id: "106-03",
  alarm: null,
  raw_value: 38,
  raw_status: null,
};

const newerSample: TelemetrySample = {
  ...firstSample,
  event_id: "event-2",
  captured_at: "2026-08-05T14:00:05.000Z",
  value: 3.9,
  raw_value: 39,
};

class FakeTelemetryLiveSource implements TelemetryLiveSource {
  subscribeCalls = 0;
  closeCalls = 0;
  private handlers: TelemetryLiveHandlers | null = null;

  subscribe(_filters: TelemetryFilters, handlers: TelemetryLiveHandlers): TelemetrySubscription {
    this.subscribeCalls += 1;
    this.handlers = handlers;
    return {
      close: () => {
        this.closeCalls += 1;
        this.handlers = null;
      },
    };
  }

  emitSample(sample: TelemetrySample): void {
    this.handlers?.onSample(sample);
  }

  emitState(state: TelemetryConnectionState): void {
    this.handlers?.onStateChange?.(state);
  }

  emitError(error: Error): void {
    this.handlers?.onError?.(error);
  }
}

async function flushReplay(): Promise<void> {
  await Promise.resolve();
}

afterEach(() => {
  vi.useRealTimers();
  resetRoutePersistentTelemetryStateForTests();
});

describe("RoutePersistentTelemetryClient", () => {
  it("reuses one physical subscription when the next route mounts within the grace interval", async () => {
    vi.useFakeTimers();
    const source = new FakeTelemetryLiveSource();
    const client = new RoutePersistentTelemetryClient(source, {
      transitionGraceMs: 1_000,
      cacheTtlMs: 10_000,
    });
    client.setApplicationShellRetained(true);

    const routeA: TelemetrySample[] = [];
    const firstSubscription = client.subscribe(
      { node_id: "edge-01" },
      { onSample: (sample) => routeA.push(sample) },
    );
    source.emitState("connected");
    source.emitSample(firstSample);
    firstSubscription.close();

    await vi.advanceTimersByTimeAsync(500);
    const routeB: TelemetrySample[] = [];
    const states: TelemetryConnectionState[] = [];
    const secondSubscription = client.subscribe(
      { node_id: "edge-01" },
      {
        onSample: (sample) => routeB.push(sample),
        onStateChange: (state) => states.push(state),
      },
    );
    await flushReplay();

    expect(source.subscribeCalls).toBe(1);
    expect(source.closeCalls).toBe(0);
    expect(routeB).toEqual([firstSample]);
    expect(states).toEqual(["connected"]);

    source.emitSample(newerSample);
    expect(routeA).toEqual([firstSample]);
    expect(routeB).toEqual([firstSample, newerSample]);

    secondSubscription.close();
    await vi.advanceTimersByTimeAsync(1_000);
    expect(source.closeCalls).toBe(1);
  });

  it("closes an idle transport after grace but retains the bounded snapshot for a later route", async () => {
    vi.useFakeTimers();
    const source = new FakeTelemetryLiveSource();
    const client = new RoutePersistentTelemetryClient(source, {
      transitionGraceMs: 1_000,
      cacheTtlMs: 10_000,
    });
    client.setApplicationShellRetained(true);

    const firstSubscription = client.subscribe({}, { onSample: () => undefined });
    source.emitSample(firstSample);
    firstSubscription.close();
    await vi.advanceTimersByTimeAsync(1_000);

    expect(source.closeCalls).toBe(1);

    const replayed: TelemetrySample[] = [];
    const secondSubscription = client.subscribe({}, { onSample: (sample) => replayed.push(sample) });
    await flushReplay();

    expect(source.subscribeCalls).toBe(2);
    expect(replayed).toEqual([firstSample]);
    secondSubscription.close();
  });

  it("evicts an idle organization scope and clears retained state after the bounded TTL", async () => {
    vi.useFakeTimers();
    const source = new FakeTelemetryLiveSource();
    const onEvict = vi.fn();
    const client = new RoutePersistentTelemetryClient(source, {
      transitionGraceMs: 100,
      cacheTtlMs: 1_000,
      onEvict,
    });
    client.setApplicationShellRetained(true);

    const subscription = client.subscribe({}, { onSample: () => undefined });
    source.emitSample(firstSample);
    subscription.close();

    await vi.advanceTimersByTimeAsync(1_000);
    expect(source.closeCalls).toBe(1);
    expect(onEvict).toHaveBeenCalledTimes(1);
    expect(() => client.subscribe({}, { onSample: () => undefined })).toThrow(
      "Telemetry runtime scope is disposed",
    );
  });

  it("retains truthful reconnect errors without duplicating route listeners", async () => {
    const source = new FakeTelemetryLiveSource();
    const client = new RoutePersistentTelemetryClient(source);
    client.setApplicationShellRetained(true);

    const firstSubscription = client.subscribe({}, { onSample: () => undefined });
    source.emitSample(firstSample);
    source.emitError(new Error("socket interrupted"));
    source.emitState("reconnecting");
    firstSubscription.close();

    const samples: TelemetrySample[] = [];
    const states: TelemetryConnectionState[] = [];
    const errors: string[] = [];
    const secondSubscription = client.subscribe(
      {},
      {
        onSample: (sample) => samples.push(sample),
        onStateChange: (state) => states.push(state),
        onError: (error) => errors.push(error.message),
      },
    );
    await flushReplay();

    expect(samples).toEqual([firstSample]);
    expect(states).toEqual(["reconnecting"]);
    expect(errors).toEqual(["socket interrupted"]);
    expect(source.subscribeCalls).toBe(1);

    source.emitState("connected");
    secondSubscription.close();

    const postReconnectErrors: string[] = [];
    client.subscribe(
      {},
      {
        onSample: () => undefined,
        onError: (error) => postReconnectErrors.push(error.message),
      },
    );
    await flushReplay();

    expect(postReconnectErrors).toEqual([]);
    expect(source.subscribeCalls).toBe(1);
  });

  it("serves exact latest-query snapshots from the shared cache and advances them with live data", () => {
    const source = new FakeTelemetryLiveSource();
    const client = new RoutePersistentTelemetryClient(source);
    const query = { node_id: "edge-01", limit: 1000 };

    client.seedLatest(query, {
      items: [firstSample],
      count: 1,
      limit: 1000,
      offset: 0,
      next_offset: null,
      snapshot_at: "2026-08-05T14:00:00.000Z",
    });
    client.setApplicationShellRetained(true);
    const subscription = client.subscribe({}, { onSample: () => undefined });
    source.emitSample(newerSample);

    expect(client.readCachedLatest(query)).toEqual({
      items: [newerSample],
      count: 1,
      limit: 1000,
      offset: 0,
      next_offset: null,
      snapshot_at: "2026-08-05T14:00:00.000Z",
    });
    expect(client.readCachedLatest({ node_id: "edge-02", limit: 1000 })).toBeNull();
    subscription.close();
  });
});
