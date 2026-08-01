import { describe, expect, it } from "vitest";

import {
  buildLiveDashboardKpis,
  createDashboardTelemetryStore,
  deriveDashboardTelemetry,
  mergeDashboardTelemetry,
} from "./dashboard-state";
import type { TelemetrySample } from "./types";

const snapshot: TelemetrySample = {
  event_id: "snapshot-event-1",
  node_id: "edge-01",
  captured_at: "2026-08-01T12:00:00Z",
  metric: "temperature.probe",
  value: 4.2,
  unit: "degC",
  quality: "valid",
  source: "dixell-xjp60d",
  equipment_id: "K106",
  channel_id: "106-03",
  alarm: null,
  raw_value: 42,
  raw_status: null,
};

describe("dashboard live lifecycle presentation", () => {
  it.each(["connected", "reconnecting"] as const)(
    "keeps an expired snapshot visible without a live badge while %s",
    (connectionState) => {
      const store = mergeDashboardTelemetry(createDashboardTelemetryStore(), [snapshot], {
        now: new Date("2026-08-01T12:00:10Z"),
      });
      const view = deriveDashboardTelemetry(store, {
        now: new Date("2026-08-01T12:01:00Z"),
        staleAfterMs: 30_000,
        hasLoadedSnapshot: true,
        connectionState,
        error: null,
      });
      const kpis = buildLiveDashboardKpis(view);

      expect(view.status).toBe("stale");
      expect(view.samples).toEqual([snapshot]);
      expect(view.freshSamples).toEqual([]);
      expect(kpis.every((item) => item.badgeTone === "stale")).toBe(true);
      expect(kpis.some((item) => item.badgeTone === "live")).toBe(false);
    },
  );

  it("preserves the snapshot while presenting reconnect exhaustion as offline", () => {
    const store = mergeDashboardTelemetry(createDashboardTelemetryStore(), [snapshot], {
      now: new Date("2026-08-01T12:00:10Z"),
    });
    const view = deriveDashboardTelemetry(store, {
      now: new Date("2026-08-01T12:01:00Z"),
      staleAfterMs: 30_000,
      hasLoadedSnapshot: true,
      connectionState: "offline",
      error: new Error("Telemetry WebSocket reconnect limit reached"),
    });
    const kpis = buildLiveDashboardKpis(view);

    expect(view.status).toBe("offline");
    expect(view.samples).toEqual([snapshot]);
    expect(kpis.every((item) => item.badgeTone === "offline")).toBe(true);
  });
});
