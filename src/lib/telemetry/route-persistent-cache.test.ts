import { afterEach, describe, expect, it } from "vitest";

import {
  resetRoutePersistentTelemetryStateForTests,
  RoutePersistentTelemetryClient,
  type TelemetryLiveSource,
} from "./route-persistent-client";
import type { TelemetrySample, TelemetrySubscription } from "./types";

const temperature: TelemetrySample = {
  event_id: "temperature-1",
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

const energy: TelemetrySample = {
  ...temperature,
  event_id: "energy-1",
  metric: "energy.active_power",
  value: 420,
  unit: "W",
  source: "energy-meter",
  equipment_id: "meter-200",
  channel_id: "M200",
  raw_value: 420,
};

const idleSource: TelemetryLiveSource = {
  subscribe(): TelemetrySubscription {
    return { close: () => undefined };
  },
};

afterEach(() => {
  resetRoutePersistentTelemetryStateForTests();
});

describe("route-persistent latest cache coverage", () => {
  it("derives a narrower route snapshot from a complete broader snapshot", () => {
    const client = new RoutePersistentTelemetryClient(idleSource);
    client.seedLatest(
      { limit: 1000 },
      {
        items: [temperature, energy],
        count: 2,
        limit: 1000,
        offset: 0,
        next_offset: null,
        snapshot_at: "2026-08-05T14:00:00.000Z",
      },
    );

    expect(
      client.readCachedLatest({ node_id: "edge-01", metric: "energy.active_power", limit: 1000 }),
    ).toEqual({
      items: [energy],
      count: 1,
      limit: 1000,
      offset: 0,
      next_offset: null,
      snapshot_at: "2026-08-05T14:00:00.000Z",
    });
  });

  it("does not derive from a paginated snapshot with incomplete coverage", () => {
    const client = new RoutePersistentTelemetryClient(idleSource);
    client.seedLatest(
      { limit: 1 },
      {
        items: [temperature],
        count: 2,
        limit: 1,
        offset: 0,
        next_offset: 1,
        snapshot_at: "2026-08-05T14:00:00.000Z",
      },
    );

    expect(client.readCachedLatest({ metric: "energy.active_power", limit: 1000 })).toBeNull();
  });
});
