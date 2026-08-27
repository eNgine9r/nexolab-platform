import { describe, expect, it } from "vitest";

import { MAX_CHART_Y_AXES } from "@/features/charts";
import { buildSavedDashboardChartGroups } from "@/features/live-dashboards/chart";
import type { LiveDashboardItem, LiveDashboardSeries } from "@/features/live-dashboards/types";
import type { TelemetrySample } from "@/lib/telemetry/types";

const START = Date.parse("2026-08-27T07:00:00.000Z");

function plottedSeries(
  position: number,
  channelId: string,
  metric: string,
  unit: string,
  equipmentId: string,
): LiveDashboardSeries {
  const item: LiveDashboardItem = {
    id: `item-${position}`,
    position,
    channel_ref_id: `ref-${channelId}`,
    channel_id: channelId,
    metric,
    native_unit: unit,
    visualization: "line",
    color: null,
    display_unit: unit,
  };
  const sample: TelemetrySample = {
    event_id: `event-${position}`,
    node_id: "edge-1",
    captured_at: new Date(START + position * 1_000).toISOString(),
    metric,
    value: position,
    unit,
    quality: "valid",
    source: "test",
    equipment_id: equipmentId,
    channel_id: channelId,
    alarm: null,
    raw_value: position,
    raw_status: null,
  };
  return { item, latest: sample, history: [sample] };
}

describe("Saved Dashboard combined chart workspace", () => {
  it("keeps same-unit series from different equipment on one chart", () => {
    const groups = buildSavedDashboardChartGroups({
      dashboardId: "dashboard-temperature",
      series: [
        plottedSeries(1, "T-101", "temperature", "°C", "controller-101"),
        plottedSeries(2, "T-108", "temperature", "°C", "controller-108"),
        plottedSeries(3, "T-115", "temperature", "°C", "controller-115"),
      ],
      status: "live",
      xDomain: { fromMs: START, toMs: START + 60_000 },
    });

    expect(groups).toHaveLength(1);
    expect(groups[0].title).toBe("Графік Dashboard");
    expect(groups[0].scene.series.map((series) => series.identity.channelId)).toEqual([
      "T-101",
      "T-108",
      "T-115",
    ]);
  });

  it("uses the axis budget as the only automatic split boundary", () => {
    const withinBudget = [
      plottedSeries(1, "V-1", "electrical.voltage", "V", "meter-1"),
      plottedSeries(2, "A-1", "electrical.current", "A", "meter-1"),
      plottedSeries(3, "W-1", "electrical.active_power", "W", "meter-2"),
      plottedSeries(4, "F-1", "electrical.frequency", "Hz", "meter-2"),
      plottedSeries(5, "E-1", "energy.total", "kWh", "meter-3"),
    ];

    expect(MAX_CHART_Y_AXES).toBe(5);
    expect(
      buildSavedDashboardChartGroups({
        dashboardId: "dashboard-within-budget",
        series: withinBudget,
        status: "live",
        xDomain: { fromMs: START, toMs: START + 60_000 },
      }),
    ).toHaveLength(1);

    const overBudget = [...withinBudget, plottedSeries(6, "RH-1", "humidity", "%RH", "climate-1")];
    const groups = buildSavedDashboardChartGroups({
      dashboardId: "dashboard-over-budget",
      series: overBudget,
      status: "live",
      xDomain: { fromMs: START, toMs: START + 60_000 },
    });

    expect(groups).toHaveLength(2);
    expect(groups.flatMap((group) => group.scene.series)).toHaveLength(overBudget.length);
    expect(groups.map((group) => group.title)).toEqual([
      "Графік Dashboard · 1/2",
      "Графік Dashboard · 2/2",
    ]);
  });
});
