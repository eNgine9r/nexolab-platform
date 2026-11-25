import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DashboardAlertEvents } from "@/components/live-dashboards/dashboard-alert-events";
import { buildSavedDashboardChartGroups } from "@/features/live-dashboards/chart";
import type { LiveDashboardItem, LiveDashboardSeries } from "@/features/live-dashboards/types";
import type { AlertInstance } from "@/lib/alerts/types";
import type { TelemetrySample } from "@/lib/telemetry/types";

const T0 = Date.parse("2026-11-22T00:00:00Z");
const WINDOW = { fromMs: T0, toMs: T0 + 3_600_000 };

function item(id: string, position: number, channelId: string): LiveDashboardItem {
  return {
    id,
    position,
    channel_ref_id: `ref-${id}`,
    node_id: "edge-1",
    equipment_id: "K106",
    channel_id: channelId,
    metric: "temperature.probe",
    native_unit: "°C",
    visualization: "line",
    color: "#22AAFF",
    display_unit: "°C",
  };
}

function sample(channelId: string): TelemetrySample {
  return {
    event_id: `e-${channelId}`,
    node_id: "edge-1",
    captured_at: new Date(T0 + 60_000).toISOString(),
    metric: "temperature.probe",
    value: 5,
    unit: "°C",
    quality: "valid",
    source: "test",
    equipment_id: "K106",
    channel_id: channelId,
    // Measurement context only: must never create a marker by itself.
    alarm: "high",
    raw_value: 5,
    raw_status: null,
  };
}

function alertFor(channelId: string): AlertInstance {
  return {
    id: `alert-${channelId}`,
    organization_id: "org",
    rule_id: "r",
    rule_version_id: "rv",
    resource_key: "rk",
    node_id: "edge-1",
    equipment_id: "K106",
    channel_id: channelId,
    metric: "temperature.probe",
    state: "active",
    severity: "alarm",
    trigger_value: 9,
    trigger_threshold: 8,
    clear_threshold: null,
    maximum_deviation: 1,
    first_event_id: "a",
    last_event_id: "b",
    session_id: null,
    stage_id: null,
    binding_id: null,
    context: {},
    triggered_at: new Date(T0 + 600_000).toISOString(),
    acknowledged_at: null,
    resolved_at: null,
    closed_at: null,
    lock_version: 1,
    created_at: new Date(T0).toISOString(),
    updated_at: new Date(T0).toISOString(),
  };
}

const series: LiveDashboardSeries[] = [
  { item: item("a", 1, "T-1"), latest: sample("T-1"), history: [sample("T-1")] },
  { item: item("b", 2, "T-2"), latest: sample("T-2"), history: [sample("T-2")] },
];

describe("saved dashboard alert annotations", () => {
  it("attaches events, regions and thresholds only for plotted matching channels", () => {
    const groups = buildSavedDashboardChartGroups({
      dashboardId: "d",
      series,
      status: "live",
      xDomain: WINDOW,
      now: T0 + 1_800_000,
      alerts: [alertFor("T-1"), alertFor("not-plotted")],
    });
    expect(groups).toHaveLength(1);
    const scene = groups[0].scene;
    expect(scene.events?.map((event) => event.source.channelId)).toEqual(["T-1"]);
    expect(scene.thresholds).toHaveLength(1);
    expect(scene.alarmRegions).toHaveLength(1);
  });

  it("never synthesises markers from telemetry alarm context", () => {
    const groups = buildSavedDashboardChartGroups({
      dashboardId: "d",
      series,
      status: "live",
      xDomain: WINDOW,
      alerts: [],
    });
    expect(groups[0].scene.events).toBeUndefined();
    expect(groups[0].scene.alarmRegions).toBeUndefined();
    expect(groups[0].scene.thresholds).toBeUndefined();
  });
});

describe("DashboardAlertEvents component", () => {
  const events = [
    {
      id: "alert-T-1:alert_triggered",
      timestampMs: T0 + 600_000,
      type: "alert_triggered",
      label: "Спрацювання: Аварія",
      source: { entityId: "alert-T-1", entityType: "alert_instance", equipmentId: "K106", channelId: "T-1" },
      severity: "alarm" as const,
      status: "active",
    },
  ];

  it("lists events with text severity, state and source", () => {
    render(<DashboardAlertEvents events={events} status="ready" message={null} displayTimeZone="UTC" />);
    const row = screen.getByTestId("dashboard-alert-event-row");
    expect(row).toHaveTextContent("Спрацювання");
    expect(row).toHaveTextContent("Аварія");
    expect(row).toHaveTextContent("Активна");
    expect(row).toHaveTextContent("alert_instance · alert-T-1");
  });

  it("shows explicit empty, unavailable and loading states and nothing when idle", () => {
    const { rerender, container } = render(
      <DashboardAlertEvents events={[]} status="idle" message={null} displayTimeZone="UTC" />,
    );
    expect(container).toBeEmptyDOMElement();
    rerender(<DashboardAlertEvents events={[]} status="ready" message={null} displayTimeZone="UTC" />);
    expect(screen.getByTestId("dashboard-alert-events-empty")).toBeInTheDocument();
    rerender(
      <DashboardAlertEvents
        events={[]}
        status="unavailable"
        message="Журнал недоступний"
        displayTimeZone="UTC"
      />,
    );
    expect(screen.getByTestId("dashboard-alert-events-note")).toHaveTextContent("Журнал недоступний");
    rerender(<DashboardAlertEvents events={[]} status="loading" message={null} displayTimeZone="UTC" />);
    expect(screen.getByRole("status")).toHaveTextContent("Завантаження");
  });
});
