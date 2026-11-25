import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChartDensityControl } from "@/components/charts/chart-density-control";
import { resolveChartPointBudget } from "@/features/charts/density";
import { buildSavedDashboardChartGroups } from "@/features/live-dashboards/chart";
import type { LiveDashboardItem, LiveDashboardSeries } from "@/features/live-dashboards/types";
import type { TelemetrySample } from "@/lib/telemetry/types";

const T0 = Date.parse("2026-11-22T00:00:00Z");
const COUNT = 6_000;
const WINDOW = { fromMs: T0, toMs: T0 + COUNT * 10_000 };

const item: LiveDashboardItem = {
  id: "a",
  position: 1,
  channel_ref_id: "ref-a",
  node_id: "edge-1",
  equipment_id: "K106",
  channel_id: "T-1",
  metric: "temperature.probe",
  native_unit: "°C",
  visualization: "line",
  color: "#22AAFF",
  display_unit: "°C",
};

function sample(index: number, value: number): TelemetrySample {
  return {
    event_id: `e-${index}`,
    node_id: "edge-1",
    captured_at: new Date(T0 + index * 10_000).toISOString(),
    metric: "temperature.probe",
    value,
    unit: "°C",
    quality: "valid",
    source: "test",
    equipment_id: "K106",
    channel_id: "T-1",
    alarm: null,
    raw_value: value,
    raw_status: null,
  };
}

function plottedPoints(pointsPerSeries: number | undefined, spikeAt = 3_333) {
  const history = Array.from({ length: COUNT }, (_, index) => sample(index, index === spikeAt ? 40 : 4));
  const series: LiveDashboardSeries[] = [{ item, latest: history.at(-1) ?? null, history }];
  const groups = buildSavedDashboardChartGroups({
    dashboardId: "d",
    series,
    status: "live",
    xDomain: WINDOW,
    now: WINDOW.toMs,
    pointsPerSeries: pointsPerSeries,
  });
  const points = groups[0].scene.series[0].segments.flatMap((segment) => segment.points);
  return points;
}

describe("saved dashboard density budget (#1620)", () => {
  it("renders more points for a higher budget and keeps the extreme excursion at every budget", () => {
    const auto = plottedPoints(undefined);
    const high = plottedPoints(2_500);
    const higher = plottedPoints(5_000);
    expect(auto.length).toBeLessThan(high.length);
    expect(high.length).toBeLessThan(higher.length);
    expect(high.length).toBeLessThanOrEqual(2_500 + 10);
    for (const points of [auto, high, higher]) {
      expect(Math.max(...points.map((point) => point.value))).toBe(40);
    }
  });

  it("returns every sample unchanged when the source has fewer points than the budget", () => {
    const history = Array.from({ length: 100 }, (_, index) => sample(index, index));
    const groups = buildSavedDashboardChartGroups({
      dashboardId: "d",
      series: [{ item, latest: history.at(-1) ?? null, history }],
      status: "live",
      xDomain: WINDOW,
      now: WINDOW.toMs,
      pointsPerSeries: 500,
    });
    expect(groups[0].scene.series[0].segments.flatMap((segment) => segment.points)).toHaveLength(100);
  });
});

describe("ChartDensityControl", () => {
  it("is labelled in Ukrainian, offers the six modes and reports a change", () => {
    const onChange = vi.fn();
    render(
      <ChartDensityControl
        mode="auto"
        resolution={resolveChartPointBudget("auto", 3)}
        onChange={onChange}
        displayedPoints={720}
        availableMeasurements={8_640}
      />,
    );
    const select = screen.getByLabelText("Деталізація / точок на лінію");
    expect(Array.from((select as HTMLSelectElement).options).map((option) => option.value)).toEqual([
      "auto",
      "250",
      "500",
      "1000",
      "2500",
      "5000",
    ]);
    fireEvent.change(select, { target: { value: "1000" } });
    expect(onChange).toHaveBeenCalledWith(1000);
    expect(screen.getByTestId("chart-density-status")).toHaveTextContent("показано 720 із");
  });

  it("explains when the aggregate cap lowered the requested mode", () => {
    render(
      <ChartDensityControl
        mode={5000}
        resolution={resolveChartPointBudget(5000, 24)}
        onChange={() => undefined}
        displayedPoints={null}
        availableMeasurements={null}
      />,
    );
    expect(screen.getByTestId("chart-density-status")).toHaveTextContent("обмежено сумарним лімітом");
    expect(screen.getByTestId("chart-density-status")).toHaveTextContent("Максимум 250");
  });
});
