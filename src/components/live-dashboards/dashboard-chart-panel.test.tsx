import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { chartSeriesKey, type ChartCursorInspection, type ChartSeries } from "@/features/charts/domain";
import { createBenchmarkScene } from "@/features/charts/fixtures";
import type { SavedDashboardChartGroup } from "@/features/live-dashboards/chart";

import { DashboardChartPanel } from "./dashboard-chart-panel";

vi.mock("@/components/charts/chart-renderer-host", () => ({
  ChartRendererHost: ({
    scene,
    onCursor,
  }: {
    scene: SavedDashboardChartGroup["scene"];
    onCursor: (value: ChartCursorInspection) => void;
  }) => (
    <button
      type="button"
      name="inspect"
      onClick={() => onCursor({ timestampMs: scene.xDomain.fromMs + 2000, series: [] })}
    >
      Навести курсор
    </button>
  ),
}));

function group(
  id: string,
  series: readonly ChartSeries[],
  xDomain: SavedDashboardChartGroup["scene"]["xDomain"],
): SavedDashboardChartGroup {
  return {
    id,
    title: id,
    equipmentId: null,
    nativeUnits: ["°C"],
    physicalQuantities: ["temperature"],
    scene: { series, xDomain },
    instruments: new Map(
      series.map((item, index) => [
        chartSeriesKey(item.identity),
        {
          key: index < 12 ? "instrument-a" : "instrument-b",
          label: index < 12 ? "W5" : "W6",
          node: "RS-485",
        },
      ]),
    ),
  };
}

const actions = {
  onResetView: vi.fn(),
  onXDomainChange: vi.fn(),
  onToggleSeries: vi.fn(),
  onSoloSeries: vi.fn(),
};

describe("saved Live Dashboard chart inspection and legend", () => {
  it("uses the cursor from another panel and clears values past the observed history", () => {
    const { series, xDomain } = createBenchmarkScene(2);
    const first = group("Temperature", [series[0]], xDomain);
    const secondSeries = {
      ...series[1],
      segments: [
        {
          ...series[1].segments[0],
          points: [{ ...series[1].segments[0].points[0], value: 0 }],
        },
      ],
    };
    const second = group("Compressor", [secondSeries], xDomain);

    function View() {
      const [cursor, setCursor] = useState<number | null>(xDomain.fromMs);
      return [first, second].map((panel) => (
        <DashboardChartPanel
          key={panel.id}
          group={panel}
          rangeLabel="1h"
          sharedCursorMs={cursor}
          resetDomain={xDomain}
          onSharedCursorChange={setCursor}
          {...actions}
        />
      ));
    }
    render(<View />);
    const [left, right] = screen.getAllByTestId("saved-dashboard-chart-panel");
    expect(within(right).getByTestId("chart-series-legend")).toHaveTextContent(/0(?:[.,]0+)? °C/);
    fireEvent.click(within(left).getByRole("button", { name: "Навести курсор" }));
    for (const panel of [left, right]) {
      expect(within(panel).getByTestId("chart-inspector-timestamp")).toHaveAttribute(
        "dateTime",
        new Date(xDomain.fromMs + 2000).toISOString(),
      );
    }
    expect(within(right).getByTestId("chart-series-legend")).toHaveTextContent("Немає даних");
  });

  it("filters a 24-series legend by device or channel and keeps existing visibility actions", () => {
    const { series, xDomain } = createBenchmarkScene(24);
    const plot = group("History", series, xDomain);
    const toggle = vi.fn();
    const solo = vi.fn();
    render(
      <DashboardChartPanel
        group={plot}
        rangeLabel="1h"
        sharedCursorMs={null}
        resetDomain={xDomain}
        onSharedCursorChange={vi.fn()}
        {...actions}
        onToggleSeries={toggle}
        onSoloSeries={solo}
      />,
    );
    const legend = screen.getByTestId("chart-series-legend");
    expect(within(legend).getByRole("region", { name: "W5" })).toBeVisible();
    expect(within(legend).getByRole("region", { name: "W6" })).toBeVisible();
    expect(within(legend).getAllByRole("button", { name: /^Приховати / })).toHaveLength(24);

    const search = within(legend).getByRole("searchbox", { name: "Знайти серію" });
    fireEvent.change(search, { target: { value: "W6" } });
    expect(within(legend).getAllByRole("button", { name: /^Приховати / })).toHaveLength(12);
    fireEvent.change(search, { target: { value: "Fixture channel 24" } });
    fireEvent.click(within(legend).getByRole("button", { name: "Приховати Fixture channel 24" }));
    fireEvent.click(within(legend).getByRole("button", { name: "Лише Fixture channel 24" }));
    expect(toggle).toHaveBeenCalledWith(chartSeriesKey(series[23].identity));
    expect(solo).toHaveBeenCalledWith(chartSeriesKey(series[23].identity));
  });
});
