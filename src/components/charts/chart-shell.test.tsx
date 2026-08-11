import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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
});
