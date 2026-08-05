import { afterEach, describe, expect, it } from "vitest";

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
  await new Promise<void>((resolve) => queueMicrotask(resolve));
}

afterEach(() => {
  resetRoutePersistentTelemetryStateForTests();
});

describe("RoutePersistentTelemetryClient", () => {
  it("keeps one physical subscription and replays the latest snapshot across route transitions", async () => {
    const source = new FakeTelemetryLiveSource();
    const client = new RoutePersistentTelemetryClient(source);
    client.setApplicationShellRetained(true);

    const routeA: TelemetrySample[] = [];
    const firstSubscription = client.subscribe(
      { node_id: "edge-01" },
      { onSample: (sample) => routeA.push(sample) },
    );

    expect(source.subscribeCalls).toBe(1);
    source.emitState("connected");
    source.emitSample(firstSample);
    expect(routeA).toEqual([firstSample]);

    firstSubscription.close();

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
    expect(routeB).toEqual([firstSample]);
    expect(states).toEqual(["connected"]);

    source.emitSample(newerSample);
    expect(routeA).toEqual([firstSample]);
    expect(routeB).toEqual([firstSample, newerSample]);

    secondSubscription.close();
    expect(source.closeCalls).toBe(0);

    client.setApplicationShellRetained(false);
    expect(source.closeCalls).toBe(1);
  });

  it("retains cached values and truthful reconnect errors without duplicating listeners", async () => {
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
  });
});
