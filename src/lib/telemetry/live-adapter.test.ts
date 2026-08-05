import { describe, expect, it, vi } from "vitest";

import { LiveTelemetryAdapter } from "./live-adapter";
import { TelemetryRestClient, type TelemetryFetch } from "./rest-client";
import { RoutePersistentTelemetryClient, type TelemetryLiveSource } from "./route-persistent-client";
import type { TelemetrySubscription } from "./types";

const collection = {
  items: [
    {
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
    },
  ],
  count: 1,
  limit: 1000,
  offset: 0,
  next_offset: null,
  snapshot_at: "2026-08-05T14:00:00.000Z",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve;
  });
  return { promise, resolve };
}

const idleLiveSource: TelemetryLiveSource = {
  subscribe(): TelemetrySubscription {
    return { close: () => undefined };
  },
};

async function flushFactory(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

describe("LiveTelemetryAdapter request coordination", () => {
  it("deduplicates simultaneous identical latest requests", async () => {
    const pending = deferred<Response>();
    const fetchImpl = vi.fn<TelemetryFetch>(() => pending.promise);
    const runtime = new RoutePersistentTelemetryClient(idleLiveSource);
    const adapter = new LiveTelemetryAdapter(
      new TelemetryRestClient("http://telemetry.local", { fetch: fetchImpl }),
      runtime,
      "http://telemetry.local",
    );

    const first = adapter.latest({ node_id: "edge-01", limit: 1000 });
    const second = adapter.latest({ node_id: "edge-01", limit: 1000 });
    await flushFactory();

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    pending.resolve(Response.json(collection));
    await expect(first).resolves.toEqual(collection);
    await expect(second).resolves.toEqual(collection);
  });

  it("deduplicates canonical identical history requests with Date and ISO inputs", async () => {
    const pending = deferred<Response>();
    const fetchImpl = vi.fn<TelemetryFetch>(() => pending.promise);
    const runtime = new RoutePersistentTelemetryClient(idleLiveSource);
    const adapter = new LiveTelemetryAdapter(
      new TelemetryRestClient("http://telemetry.local", { fetch: fetchImpl }),
      runtime,
      "http://telemetry.local",
    );
    const from = "2026-08-05T13:00:00.000Z";
    const to = "2026-08-05T14:00:00.000Z";

    const first = adapter.history({ node_id: "edge-01", from: new Date(from), to: new Date(to) });
    const second = adapter.history({ node_id: "edge-01", from, to });
    await flushFactory();

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    pending.resolve(Response.json(collection));
    await expect(first).resolves.toEqual(collection);
    await expect(second).resolves.toEqual(collection);
  });
});
