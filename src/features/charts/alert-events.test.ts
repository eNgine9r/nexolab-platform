import { describe, expect, it } from "vitest";

import type { AlertInstance } from "@/lib/alerts/types";

import { alertMatchesSeries, buildAlertChartAnnotations } from "./alert-events";
import { chartSeriesKey, type ChartSeriesIdentity } from "./domain";

const T0 = Date.parse("2026-11-22T00:00:00Z");
const WINDOW = { fromMs: T0, toMs: T0 + 3_600_000 };
const NOW = T0 + 7_200_000;

const identity: ChartSeriesIdentity = {
  nodeId: "edge-1",
  equipmentId: "K106",
  channelId: "106-03",
  metric: "temperature.probe",
  nativeUnit: "°C",
};

function alert(overrides: Partial<AlertInstance> = {}): AlertInstance {
  return {
    id: "alert-1",
    organization_id: "org",
    rule_id: "rule",
    rule_version_id: "rv",
    resource_key: "rk",
    node_id: "edge-1",
    equipment_id: "K106",
    channel_id: "106-03",
    metric: "temperature.probe",
    state: "resolved",
    severity: "alarm",
    trigger_value: 9.2,
    trigger_threshold: 8,
    clear_threshold: 7,
    maximum_deviation: 1.2,
    first_event_id: "e1",
    last_event_id: "e2",
    session_id: null,
    stage_id: null,
    binding_id: null,
    context: {},
    triggered_at: new Date(T0 + 600_000).toISOString(),
    acknowledged_at: new Date(T0 + 900_000).toISOString(),
    resolved_at: new Date(T0 + 1_800_000).toISOString(),
    closed_at: null,
    lock_version: 1,
    created_at: new Date(T0).toISOString(),
    updated_at: new Date(T0).toISOString(),
    ...overrides,
  };
}

describe("canonical alert chart annotations", () => {
  it("maps an alert to marked transitions, one clipped region and an upper threshold", () => {
    const result = buildAlertChartAnnotations([alert()], [identity], WINDOW, NOW);
    expect(result.events.map((event) => event.id)).toEqual([
      "alert-1:alert_triggered",
      "alert-1:alert_acknowledged",
      "alert-1:alert_resolved",
    ]);
    expect(result.events[0]).toMatchObject({
      type: "alert_triggered",
      severity: "alarm",
      source: { entityId: "alert-1", entityType: "alert_instance", equipmentId: "K106", channelId: "106-03" },
    });
    expect(result.alarmRegions).toEqual([
      expect.objectContaining({ fromMs: T0 + 600_000, toMs: T0 + 1_800_000, severity: "alarm" }),
    ]);
    expect(result.thresholds).toEqual([
      expect.objectContaining({ seriesKey: chartSeriesKey(identity), kind: "upper", value: 8 }),
    ]);
  });

  it("uses a lower threshold when the trigger value is below the limit", () => {
    const result = buildAlertChartAnnotations(
      [alert({ trigger_value: -1, trigger_threshold: 2 })],
      [identity],
      WINDOW,
      NOW,
    );
    expect(result.thresholds[0]).toMatchObject({ kind: "lower", value: 2 });
  });

  it("ignores alerts for channels that are not plotted", () => {
    const result = buildAlertChartAnnotations(
      [alert({ channel_id: "other" }), alert({ id: "x", metric: "humidity" })],
      [identity],
      WINDOW,
      NOW,
    );
    expect(result).toEqual({ events: [], alarmRegions: [], thresholds: [] });
    expect(alertMatchesSeries(alert(), identity)).toBe(true);
  });

  it("extends an open alert to the window end and clips a region that started earlier", () => {
    const open = alert({
      state: "active",
      triggered_at: new Date(T0 - 600_000).toISOString(),
      acknowledged_at: null,
      resolved_at: null,
    });
    const result = buildAlertChartAnnotations([open], [identity], WINDOW, NOW);
    expect(result.alarmRegions[0]).toMatchObject({ fromMs: WINDOW.fromMs, toMs: WINDOW.toMs });
    // Trigger happened before the window, so no marker is drawn at a time outside it.
    expect(result.events).toEqual([]);
  });

  it("excludes alerts entirely outside the viewed window", () => {
    const old = alert({
      triggered_at: new Date(T0 - 7_200_000).toISOString(),
      acknowledged_at: null,
      resolved_at: new Date(T0 - 3_600_000).toISOString(),
    });
    const future = alert({
      id: "late",
      triggered_at: new Date(T0 + 4_000_000).toISOString(),
      resolved_at: null,
    });
    expect(buildAlertChartAnnotations([old, future], [identity], WINDOW, NOW)).toEqual({
      events: [],
      alarmRegions: [],
      thresholds: [],
    });
  });

  it("deduplicates repeated alert ids and identical thresholds, and ignores a missing threshold", () => {
    const result = buildAlertChartAnnotations(
      [alert(), alert(), alert({ id: "alert-2", trigger_threshold: null })],
      [identity],
      WINDOW,
      NOW,
    );
    expect(result.thresholds).toHaveLength(1);
    expect(result.events.filter((event) => event.id.startsWith("alert-1:"))).toHaveLength(3);
  });
});
