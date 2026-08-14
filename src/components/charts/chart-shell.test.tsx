import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { chartSeriesKey } from "@/features/charts/domain";
import { createBenchmarkScene } from "@/features/charts/fixtures";

import { ChartShell } from "./chart-shell";

describe("ChartShell accessibility contract", () => {
  it("provides non-color state text and keyboard-operable legend controls", () => {
    const scene = createBenchmarkScene(1);
    const toggle = vi.fn();
    const solo = vi.fn();
    render(
      <ChartShell
        title="Fixture telemetry"
        context="Benchmark"
        selectedRange="15 min"
        series={scene.series}
        inspection={null}
        onToggleSeries={toggle}
        onSoloSeries={solo}
        onResetZoom={vi.fn()}
      >
        <div>plot</div>
      </ChartShell>,
    );

    expect(screen.getByTestId("chart-accessible-summary")).toHaveTextContent(
      "Range 15 min. 1 series. Units °C. State Live.",
    );
    expect(screen.getByText(/valid · Live/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Hide" }));
    fireEvent.click(screen.getByRole("button", { name: "Solo" }));
    expect(toggle).toHaveBeenCalledTimes(1);
    expect(solo).toHaveBeenCalledTimes(1);
  });

  it("keeps one fixed-footprint inspector mounted and formats every visible series deterministically", () => {
    const scene = createBenchmarkScene(2);
    const firstSeries = scene.series[0];
    const secondSeries = scene.series[1];
    const firstPoint = { ...firstSeries.segments[0].points[0], value: 25.700000000000003 };
    const secondPoint = secondSeries.segments[0].points[0];
    const props = {
      title: "Fixture telemetry",
      context: "Benchmark",
      selectedRange: "15 min",
      series: scene.series,
      onToggleSeries: vi.fn(),
      onSoloSeries: vi.fn(),
      onResetZoom: vi.fn(),
    };
    const { rerender } = render(
      <ChartShell {...props} inspection={null}>
        <div>plot</div>
      </ChartShell>,
    );

    const inspector = screen.getByTestId("chart-inspector");
    expect(inspector).toHaveClass("min-h-44");
    expect(inspector).toHaveTextContent("Move the shared cursor or use keyboard inspection.");

    rerender(
      <ChartShell
        {...props}
        inspection={{
          timestampMs: firstPoint.timestampMs,
          series: [
            {
              seriesKey: chartSeriesKey(firstSeries.identity),
              point: firstPoint,
              freshness: firstSeries.freshness,
            },
            {
              seriesKey: chartSeriesKey(secondSeries.identity),
              point: secondPoint,
              freshness: secondSeries.freshness,
            },
          ],
        }}
      >
        <div>plot</div>
      </ChartShell>,
    );

    expect(screen.getByTestId("chart-inspector")).toBe(inspector);
    expect(inspector).toHaveTextContent("Nearest measured sample per visible series.");
    expect(inspector).toHaveTextContent(new Date(firstPoint.timestampMs).toISOString());
    expect(inspector).toHaveTextContent("25.70 °C");
    expect(inspector).not.toHaveTextContent("25.700000000000003");
    expect(within(inspector).getAllByRole("row")).toHaveLength(3);
  });

  it("renders a mutually exclusive placeholder when one series has no nearby sample", () => {
    const scene = createBenchmarkScene(1);
    const series = scene.series[0];
    render(
      <ChartShell
        title="Fixture telemetry"
        context="Benchmark"
        selectedRange="15 min"
        series={scene.series}
        inspection={{
          timestampMs: series.segments[0].points[0].timestampMs + 2_500,
          series: [
            {
              seriesKey: chartSeriesKey(series.identity),
              point: null,
              freshness: series.freshness,
            },
          ],
        }}
        onToggleSeries={vi.fn()}
        onSoloSeries={vi.fn()}
        onResetZoom={vi.fn()}
      >
        <div>plot</div>
      </ChartShell>,
    );

    const inspector = screen.getByTestId("chart-inspector");
    const row = within(inspector).getAllByRole("row")[1];
    expect(row).toHaveTextContent("—");
    expect(row).not.toHaveTextContent(`${series.segments[0].points[0].value}`);
  });
});
