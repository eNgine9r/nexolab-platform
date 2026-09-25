import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { createBenchmarkScene } from "@/features/charts/fixtures";
import type { LiveChartGroup } from "@/features/live/live-chart";

import { LiveChartPanel } from "./live-chart-panel";

vi.mock("@/components/charts/chart-renderer-host", () => ({
  ChartRendererHost: (props: { reducedMotion?: boolean }) => (
    <div data-testid="mock-chart-renderer" data-reduced-motion={String(Boolean(props.reducedMotion))} />
  ),
}));

vi.mock("@/components/charts/chart-shell", () => ({
  ChartShell: ({ children, onResetZoom }: { children: React.ReactNode; onResetZoom: () => void }) => (
    <section>
      <button type="button" onClick={onResetZoom}>
        Reset zoom
      </button>
      {children}
    </section>
  ),
}));

vi.mock("@/features/charts/echarts-adapter", () => ({
  EChartsRendererAdapter: class {
    resetZoom() {}
  },
}));

function group(): LiveChartGroup {
  return {
    id: "equipment:fixture:axes:0",
    equipmentId: "fixture-equipment",
    nativeUnits: ["degC"],
    physicalQuantities: ["temperature"],
    scene: createBenchmarkScene(1),
  };
}

describe("LiveChartPanel rolling render stability", () => {
  it("disables renderer animation for rolling Live Data updates", () => {
    render(
      <LiveChartPanel
        group={group()}
        rangeLabel="Live"
        sharedCursorMs={null}
        resetDomain={group().scene.xDomain}
        onSharedCursorChange={vi.fn()}
        onXDomainChange={vi.fn()}
        onResetView={vi.fn()}
        onToggleSeries={vi.fn()}
        onSoloSeries={vi.fn()}
      />,
    );

    expect(screen.getByTestId("mock-chart-renderer")).toHaveAttribute("data-reduced-motion", "true");
  });
  it("routes reset through the dedicated reset callback instead of a manual domain change", () => {
    const onResetView = vi.fn();
    const onXDomainChange = vi.fn();

    render(
      <LiveChartPanel
        group={group()}
        rangeLabel="Live"
        sharedCursorMs={null}
        resetDomain={group().scene.xDomain}
        onSharedCursorChange={vi.fn()}
        onXDomainChange={onXDomainChange}
        onResetView={onResetView}
        onToggleSeries={vi.fn()}
        onSoloSeries={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Reset zoom" }));

    expect(onResetView).toHaveBeenCalledTimes(1);
    expect(onXDomainChange).not.toHaveBeenCalled();
  });
});
