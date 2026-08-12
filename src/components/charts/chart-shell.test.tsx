import { fireEvent, render, screen } from "@testing-library/react";
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

  it("keeps one fixed-footprint inspector mounted while cursor state changes", () => {
    const scene = createBenchmarkScene(1);
    const series = scene.series[0];
    const point = series.segments[0].points[0];
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
    expect(inspector).toHaveTextContent("Timestamp—Series—Value—Quality—Freshness—");

    rerender(
      <ChartShell
        {...props}
        inspection={{
          timestampMs: point.timestampMs,
          seriesKey: chartSeriesKey(series.identity),
          point,
          freshness: series.freshness,
        }}
      >
        <div>plot</div>
      </ChartShell>,
    );

    expect(screen.getByTestId("chart-inspector")).toBe(inspector);
    expect(inspector).toHaveTextContent("Exact measured sample.");
    expect(inspector).toHaveTextContent(new Date(point.timestampMs).toISOString());
    expect(inspector).toHaveTextContent(`${point.value} ${series.identity.nativeUnit}`);
  });
});
