import { describe, expect, it } from "vitest";

import { chartSeriesKey } from "@/features/charts";
import {
  buildSavedDashboardChartGroups,
  savedDashboardChartIdentity,
  savedDashboardResetDomain,
} from "@/features/live-dashboards/chart";
import type { LiveDashboardItem, LiveDashboardSeries } from "@/features/live-dashboards/types";
import type { TelemetrySample } from "@/lib/telemetry/types";

const START = Date.parse("2026-08-12T05:00:00.000Z");

function item(
  id: string,
  position: number,
  channelId: string,
  unit: string,
  visualization: LiveDashboardItem["visualization"],
  color: string,
  metric = "temperature.probe",
): LiveDashboardItem {
  return {
    id,
    position,
    channel_ref_id: `ref-${id}`,
    channel_id: channelId,
    metric,
    native_unit: unit,
    visualization,
    color,
    display_unit: unit,
  };
}

function sample(
  eventId: string,
  channelId: string,
  unit: string,
  offsetMs: number,
  value: number | null,
  quality: TelemetrySample["quality"] = "valid",
  alarm: TelemetrySample["alarm"] = null,
  metric = "temperature.probe",
): TelemetrySample {
  return {
    event_id: eventId,
    node_id: "edge-1",
    captured_at: new Date(START + offsetMs).toISOString(),
    metric,
    value,
    unit,
    quality,
    source: "test",
    equipment_id: "equipment-1",
    channel_id: channelId,
    alarm,
    raw_value: value,
    raw_status: null,
  };
}

function series(sourceItem: LiveDashboardItem, history: TelemetrySample[]): LiveDashboardSeries {
  return { item: sourceItem, latest: history.at(-1) ?? null, history };
}

describe("Saved Live Dashboard canonical chart mapping", () => {
  it("preserves persisted order and colors while grouping compatible units and excluding value/gauge", () => {
    const second = item("second", 2, "T-2", "degC", "area", "#123456");
    const first = item("first", 1, "T-1", "degC", "line", "#654321");
    const valueItem = item("value", 3, "T-3", "degC", "value", "#ABCDEF");
    const groups = buildSavedDashboardChartGroups({
      dashboardId: "dashboard-1",
      series: [
        series(second, [sample("s2", "T-2", "degC", 10_000, 2)]),
        series(first, [sample("s1", "T-1", "degC", 10_000, 1)]),
        series(valueItem, [sample("s3", "T-3", "degC", 10_000, 3)]),
      ],
      status: "live",
      xDomain: { fromMs: START, toMs: START + 60_000 },
    });

    expect(groups).toHaveLength(1);
    expect(groups[0].scene.series.map((entry) => entry.identity.channelId)).toEqual(["T-1", "T-2"]);
    expect(groups[0].scene.series.map((entry) => entry.colorToken)).toEqual(["#654321", "#123456"]);
    expect(groups[0].scene.series[0].areaFillOpacity).toBeUndefined();
    expect(groups[0].scene.series[1].areaFillOpacity).toBeGreaterThan(0);
  });

  it("never bridges invalid samples or established source gaps", () => {
    const sourceItem = item("gap", 1, "T-gap", "degC", "line", "#00C6E0");
    const groups = buildSavedDashboardChartGroups({
      dashboardId: "dashboard-gap",
      series: [
        series(sourceItem, [
          sample("valid-a", "T-gap", "degC", 0, 1),
          sample("invalid", "T-gap", "degC", 10_000, null, "communication_error"),
          sample("valid-b", "T-gap", "degC", 20_000, 2),
          sample("valid-c", "T-gap", "degC", 70_000, 3),
        ]),
      ],
      status: "live",
      xDomain: { fromMs: START, toMs: START + 90_000 },
    });

    const segments = groups[0].scene.series[0].segments;
    expect(segments).toHaveLength(3);
    expect(segments[1].precedingBreak?.reason).toBe("invalid_quality");
    expect(segments[2].precedingBreak?.reason).toBe("source_gap");
    expect(segments.flatMap((segment) => segment.points).map((point) => point.id)).toEqual([
      "valid-a",
      "valid-b",
      "valid-c",
    ]);
  });

  it("does not turn telemetry alarm context into chart annotations and keeps energy semantics separate", () => {
    const temperature = item("temp", 1, "T-1", "degC", "line", "#00C6E0");
    const energy = item("energy", 2, "E-1", "kWh", "line", "#F5B301", "energy.total");
    const groups = buildSavedDashboardChartGroups({
      dashboardId: "dashboard-energy",
      series: [
        series(temperature, [
          sample("normal", "T-1", "degC", 0, 1),
          sample("alarm", "T-1", "degC", 10_000, 2, "valid", "high"),
        ]),
        series(energy, [sample("energy-1", "E-1", "kWh", 0, 10, "valid", null, "energy.total")]),
      ],
      status: "stale",
      xDomain: { fromMs: START, toMs: START + 60_000 },
    });

    expect(groups).toHaveLength(2);
    const temperatureSeries = groups
      .flatMap((group) => group.scene.series)
      .find((entry) => entry.identity.channelId === "T-1")!;
    const energySeries = groups
      .flatMap((group) => group.scene.series)
      .find((entry) => entry.identity.channelId === "E-1")!;
    expect(
      temperatureSeries.segments
        .flatMap((segment) => segment.points)
        .some((point) => point.pinReasons?.includes("alarm")),
    ).toBe(false);
    expect(groups.flatMap((group) => group.scene.events ?? [])).toHaveLength(0);
    expect(temperatureSeries.freshness).toBe("stale");
    expect(energySeries.semanticMode).toBe("cumulative_counter");
  });

  it("applies hide and solo without changing the persisted series identity", () => {
    const first = series(item("first", 1, "T-1", "degC", "line", "#00C6E0"), [
      sample("one", "T-1", "degC", 0, 1),
    ]);
    const second = series(item("second", 2, "T-2", "degC", "line", "#7ED321"), [
      sample("two", "T-2", "degC", 0, 2),
    ]);
    const secondKey = chartSeriesKey(savedDashboardChartIdentity("dashboard-visibility", second));

    const hidden = buildSavedDashboardChartGroups({
      dashboardId: "dashboard-visibility",
      series: [first, second],
      status: "live",
      xDomain: { fromMs: START, toMs: START + 60_000 },
      hiddenSeriesKeys: new Set([secondKey]),
    });
    expect(hidden[0].scene.series.map((entry) => entry.visible)).toEqual([true, false]);

    const solo = buildSavedDashboardChartGroups({
      dashboardId: "dashboard-visibility",
      series: [first, second],
      status: "live",
      xDomain: { fromMs: START, toMs: START + 60_000 },
      soloSeriesKey: secondKey,
    });
    expect(solo[0].scene.series.map((entry) => entry.visible)).toEqual([false, true]);
  });

  it("derives the initial viewport from the persisted time window", () => {
    expect(savedDashboardResetDomain("15m", START)).toEqual({
      fromMs: START - 15 * 60_000,
      toMs: START,
    });
    expect(savedDashboardResetDomain("7d", START)).toEqual({
      fromMs: START - 7 * 24 * 60 * 60_000,
      toMs: START,
    });
  });
});
