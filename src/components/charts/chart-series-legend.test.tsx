import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { chartSeriesKey, type ChartMeasurementQuality, type ChartSeries } from "@/features/charts/domain";
import { createBenchmarkScene } from "@/features/charts/fixtures";

import { ChartSeriesLegend, type ChartLegendGroup } from "./chart-series-legend";

function withLatest(
  item: ChartSeries,
  value: number,
  quality: ChartMeasurementQuality = "valid",
): ChartSeries {
  return { ...item, latest: { timestampMs: 1, value, quality } };
}

describe("ChartSeriesLegend (#1878)", () => {
  it("renders one compact row per series with value, unit and icon controls only", () => {
    const { series } = createBenchmarkScene(2);
    const toggle = vi.fn();
    const solo = vi.fn();
    render(
      <ChartSeriesLegend
        series={[withLatest(series[0], 0), series[1]]}
        inspection={null}
        onToggleSeries={toggle}
        onSoloSeries={solo}
      />,
    );

    const rows = screen.getAllByTestId("chart-series-legend-row");
    expect(rows).toHaveLength(2);
    // Zero stays zero, never "no data".
    expect(within(rows[0]).getByTestId("chart-series-legend-value")).toHaveTextContent(/^0(?:[.,]0+)? /);
    expect(screen.getByTestId("chart-series-legend-mode")).toHaveTextContent("Останні вимірювання");
    // No textual card buttons.
    expect(screen.queryByRole("button", { name: "Приховати" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Лише цей" })).toBeNull();

    const hide = within(rows[0]).getByRole("button", { name: `Приховати ${series[0].name}` });
    expect(hide).toHaveAttribute("aria-pressed", "true");
    expect(hide).toHaveTextContent("");
    fireEvent.click(hide);
    fireEvent.click(within(rows[0]).getByRole("button", { name: `Лише ${series[0].name}` }));
    expect(toggle).toHaveBeenCalledWith(chartSeriesKey(series[0].identity));
    expect(solo).toHaveBeenCalledWith(chartSeriesKey(series[0].identity));
  });

  it("switches to cursor values and marks a series without a measurement at the cursor", () => {
    const { series } = createBenchmarkScene(2);
    const point = series[0].segments[0].points[3];
    render(
      <ChartSeriesLegend
        series={series}
        inspection={{
          timestampMs: point.timestampMs,
          series: [
            { seriesKey: chartSeriesKey(series[0].identity), point, freshness: "live" },
            { seriesKey: chartSeriesKey(series[1].identity), point: null, freshness: "live" },
          ],
        }}
        onToggleSeries={vi.fn()}
        onSoloSeries={vi.fn()}
      />,
    );
    expect(screen.getByTestId("chart-series-legend-mode")).toHaveTextContent("На курсорі");
    const values = screen.getAllByTestId("chart-series-legend-value");
    expect(values[0]).not.toHaveTextContent("Немає даних");
    expect(values[1]).toHaveTextContent("Немає даних");
  });

  it("shows stale freshness and non-valid quality as text, and offers Show for a hidden series", () => {
    const { series } = createBenchmarkScene(2);
    render(
      <ChartSeriesLegend
        series={[
          { ...withLatest(series[0], 5, "sensor_error"), freshness: "stale" },
          { ...series[1], visible: false },
        ]}
        inspection={null}
        onToggleSeries={vi.fn()}
        onSoloSeries={vi.fn()}
      />,
    );
    const rows = screen.getAllByTestId("chart-series-legend-row");
    expect(within(rows[0]).getByTestId("chart-series-legend-freshness")).toHaveTextContent("Застаріло");
    expect(within(rows[0]).getByTestId("chart-series-legend-value")).toHaveTextContent("помилка датчика");
    expect(within(rows[1]).getByRole("button", { name: `Показати ${series[1].name}` })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("groups rows by instrument and searches only above four series", () => {
    const { series } = createBenchmarkScene(6);
    const groups = new Map<string, ChartLegendGroup>(
      series.map((item, index) => [
        chartSeriesKey(item.identity),
        { key: index < 3 ? "a" : "b", label: index < 3 ? "Прилад A" : "Прилад B", secondary: "node-1" },
      ]),
    );
    const { rerender } = render(
      <ChartSeriesLegend
        series={series.slice(0, 4)}
        inspection={null}
        groups={groups}
        onToggleSeries={vi.fn()}
        onSoloSeries={vi.fn()}
      />,
    );
    expect(screen.queryByRole("searchbox")).toBeNull();

    rerender(
      <ChartSeriesLegend
        series={series}
        inspection={null}
        groups={groups}
        onToggleSeries={vi.fn()}
        onSoloSeries={vi.fn()}
      />,
    );
    const legend = screen.getByTestId("chart-series-legend");
    expect(within(legend).getByRole("region", { name: "Прилад A" })).toBeVisible();
    expect(within(legend).getByRole("region", { name: "Прилад B" })).toBeVisible();
    fireEvent.change(within(legend).getByRole("searchbox", { name: "Знайти серію" }), {
      target: { value: "Прилад B" },
    });
    expect(within(legend).getAllByTestId("chart-series-legend-row")).toHaveLength(3);
    expect(within(legend).queryByRole("region", { name: "Прилад A" })).toBeNull();
  });
});
