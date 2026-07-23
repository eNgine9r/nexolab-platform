import { describe, expect, it } from "vitest";

import {
  buildLiveDashboardKpis,
  createDashboardTelemetryStore,
  deriveDashboardTelemetry,
  mergeDashboardTelemetry,
  selectProductionTemperatures,
} from "./dashboard-state";
import type { TelemetrySample } from "./types";

function sample(overrides: Partial<TelemetrySample> = {}): TelemetrySample {
  return {
    event_id: "event-1",
    node_id: "edge-01",
    captured_at: "2026-07-23T18:00:00Z",
    metric: "temperature",
    value: 4.2,
    unit: "degC",
    quality: "valid",
    source: "modbus",
    equipment_id: "xjp60d-106",
    channel_id: "106-03",
    alarm: null,
    raw_value: 42,
    raw_status: null,
    ...overrides,
  };
}

const NOW = new Date("2026-07-23T18:00:10Z");

describe("dashboard telemetry state", () => {
  it("deduplicates event ids and keeps the newest series sample", () => {
    const initial = createDashboardTelemetryStore();
    const first = mergeDashboardTelemetry(
      initial,
      [sample(), sample({ event_id: "event-duplicate" })],
      { now: NOW },
    );
    const updated = mergeDashboardTelemetry(
      first,
      [
        sample({ event_id: "event-old", captured_at: "2026-07-23T17:59:59Z", value: 1 }),
        sample({ event_id: "event-2", captured_at: "2026-07-23T18:00:05Z", value: 5.1 }),
        sample({ event_id: "event-2", captured_at: "2026-07-23T18:00:05Z", value: 9.9 }),
      ],
      { now: NOW },
    );

    expect(Object.values(updated.samples)).toHaveLength(1);
    expect(Object.values(updated.samples)[0].value).toBe(5.1);
    expect(updated.seenEventIds).toContain("event-2");
  });

  it("rejects future-dated telemetry instead of presenting it as live", () => {
    const store = mergeDashboardTelemetry(
      createDashboardTelemetryStore(),
      [sample({ captured_at: "2026-07-23T18:02:00Z" })],
      { now: NOW, maxFutureSkewMs: 30_000 },
    );
    const view = deriveDashboardTelemetry(store, {
      now: NOW,
      hasLoadedSnapshot: true,
      connectionState: "connected",
      error: null,
    });

    expect(view.samples).toEqual([]);
    expect(view.rejectedFutureSamples).toBe(1);
    expect(view.status).toBe("offline");
  });

  it("distinguishes live, reconnecting, stale and offline", () => {
    const store = mergeDashboardTelemetry(
      createDashboardTelemetryStore(),
      [sample()],
      { now: NOW },
    );

    expect(
      deriveDashboardTelemetry(store, {
        now: NOW,
        hasLoadedSnapshot: true,
        connectionState: "connected",
        error: null,
      }).status,
    ).toBe("live");
    expect(
      deriveDashboardTelemetry(store, {
        now: NOW,
        hasLoadedSnapshot: true,
        connectionState: "reconnecting",
        error: null,
      }).status,
    ).toBe("reconnecting");
    expect(
      deriveDashboardTelemetry(store, {
        now: new Date("2026-07-23T18:01:00Z"),
        hasLoadedSnapshot: true,
        connectionState: "connected",
        error: null,
      }).status,
    ).toBe("stale");
    expect(
      deriveDashboardTelemetry(store, {
        now: new Date("2026-07-23T18:01:00Z"),
        hasLoadedSnapshot: true,
        connectionState: "disconnected",
        error: null,
      }).status,
    ).toBe("offline");
  });

  it("renders quality errors and status-only samples without fake values", () => {
    const store = mergeDashboardTelemetry(
      createDashboardTelemetryStore(),
      [
        sample({ quality: "sensor_error", value: null, alarm: "high" }),
        sample({
          event_id: "status-only",
          metric: "device_status",
          channel_id: "106-status",
          quality: "communication_error",
          value: null,
        }),
      ],
      { now: NOW },
    );
    const view = deriveDashboardTelemetry(store, {
      now: NOW,
      hasLoadedSnapshot: true,
      connectionState: "connected",
      error: null,
    });
    const kpis = buildLiveDashboardKpis(view);

    expect(kpis.find((item) => item.label === "Середня температура")?.value).toBe("—");
    expect(kpis.find((item) => item.label === "Активних тривог")?.value).toBe("2");
  });

  it("maps production temperature and power channels", () => {
    const store = mergeDashboardTelemetry(
      createDashboardTelemetryStore(),
      [
        sample(),
        sample({
          event_id: "temp-2",
          equipment_id: "xjp60d-106",
          channel_id: "106-04",
          value: 5.2,
        }),
        sample({
          event_id: "power-200",
          equipment_id: "le01mp-200",
          channel_id: "200",
          metric: "active_power",
          value: 1200,
          unit: "W",
        }),
        sample({
          event_id: "power-201",
          equipment_id: "le01mp-201",
          channel_id: "201",
          metric: "active_power",
          value: 0.8,
          unit: "kW",
        }),
      ],
      { now: NOW },
    );
    const view = deriveDashboardTelemetry(store, {
      now: NOW,
      hasLoadedSnapshot: true,
      connectionState: "connected",
      error: null,
    });
    const kpis = buildLiveDashboardKpis(view);

    expect(selectProductionTemperatures(view)).toHaveLength(2);
    expect(kpis.find((item) => item.label === "Поточне споживання")?.value).toBe("2,00 kW");
    expect(kpis.find((item) => item.label === "Середня температура")?.value).toBe("4,7 °C");
  });
});
