import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RefrigerationControllerChart } from "@/components/refrigeration/refrigeration-controller-chart";
import { createBenchmarkScene } from "@/features/charts/fixtures";
import type { ChartRendererScene } from "@/features/charts/renderer-adapter";

vi.mock("@/components/charts/chart-shell", () => ({
  ChartShell: ({
    children,
    inspection,
  }: {
    children: React.ReactNode;
    inspection: { timestampMs: number; series: { point: unknown }[] } | null;
  }) => (
    <div
      data-testid="mock-inspection"
      data-timestamp={inspection?.timestampMs ?? ""}
      data-observations={inspection?.series.filter((entry) => entry.point).length}
    >
      {children}
    </div>
  ),
}));

vi.mock("@/components/charts/chart-renderer-host", () => ({
  ChartRendererHost: ({
    scene,
    sharedCursorMs,
    onCursor,
    onXDomainChange,
  }: {
    scene: ChartRendererScene;
    sharedCursorMs: number | null;
    onCursor: (inspection: { timestampMs: number; series: [] } | null) => void;
    onXDomainChange: (domain: { fromMs: number; toMs: number }) => void;
  }) => {
    const timestampMs = scene.series[0]?.segments[0]?.points[0]?.timestampMs ?? scene.xDomain.fromMs;
    return (
      <div>
        <button
          type="button"
          data-testid="mock-renderer"
          data-from={scene.xDomain.fromMs}
          data-to={scene.xDomain.toMs}
          data-shared-cursor={sharedCursorMs ?? ""}
          onClick={() =>
            onXDomainChange({
              fromMs: scene.xDomain.fromMs + 10_000,
              toMs: scene.xDomain.toMs - 10_000,
            })
          }
        >
          renderer
        </button>
        <button type="button" data-testid="mock-cursor" onClick={() => onCursor({ timestampMs, series: [] })}>
          cursor
        </button>
        <button type="button" data-testid="mock-clear-cursor" onClick={() => onCursor(null)}>
          clear cursor
        </button>
      </div>
    );
  },
}));

function chart(
  scene: ChartRendererScene,
  sharedCursorMs: number | null = null,
  onSharedCursorChange: (timestampMs: number | null) => void = vi.fn(),
  viewportDomain = scene.xDomain,
  onViewportChange = vi.fn(),
) {
  return (
    <RefrigerationControllerChart
      title="Compressor"
      context="test"
      rangeLabel="range"
      scene={scene}
      emptyMessage="empty"
      sharedCursorMs={sharedCursorMs}
      onSharedCursorChange={onSharedCursorChange}
      viewportDomain={viewportDomain}
      onViewportChange={onViewportChange}
      rangeSelection={null}
      onRangeSelectionChange={vi.fn()}
    />
  );
}

describe("RefrigerationControllerChart viewport lifecycle", () => {
  it("reports plot zoom and renders the parent-supplied shared time domain", async () => {
    const first = createBenchmarkScene(1);
    const onViewportChange = vi.fn();
    const { rerender } = render(chart(first, null, vi.fn(), first.xDomain, onViewportChange));

    fireEvent.click(screen.getByTestId("mock-renderer"));
    expect(onViewportChange).toHaveBeenCalledWith({
      fromMs: first.xDomain.fromMs + 10_000,
      toMs: first.xDomain.toMs - 10_000,
    });

    const second = {
      ...first,
      xDomain: {
        fromMs: first.xDomain.toMs + 60_000,
        toMs: first.xDomain.toMs + 180_000,
      },
    };
    rerender(chart(first, null, vi.fn(), second.xDomain, onViewportChange));

    await waitFor(() =>
      expect(screen.getByTestId("mock-renderer")).toHaveAttribute("data-from", String(second.xDomain.fromMs)),
    );
    expect(screen.getByTestId("mock-renderer")).toHaveAttribute("data-to", String(second.xDomain.toMs));
  });
});

describe("RefrigerationControllerChart shared Exact Inspector", () => {
  it("derives its own inspection from the externally shared timestamp", () => {
    const scene = createBenchmarkScene(1);
    const timestampMs = scene.series[0]!.segments[0]!.points[4]!.timestampMs;
    const { rerender } = render(chart(scene, timestampMs));

    expect(screen.getByTestId("mock-renderer")).toHaveAttribute("data-shared-cursor", String(timestampMs));
    expect(screen.getByTestId("mock-inspection")).toHaveAttribute("data-timestamp", String(timestampMs));

    rerender(chart(scene, null));
    expect(screen.getByTestId("mock-inspection")).toHaveAttribute("data-timestamp", "");
  });

  it("does not reuse the last measurement beyond the observed history", () => {
    const scene = createBenchmarkScene(1);
    const lastPoint = scene.series[0]!.segments.at(-1)!.points.at(-1)!;
    const { rerender } = render(chart(scene, lastPoint.timestampMs));
    expect(screen.getByTestId("mock-inspection")).toHaveAttribute("data-observations", "1");

    rerender(chart(scene, lastPoint.timestampMs + 1000));
    expect(screen.getByTestId("mock-inspection")).toHaveAttribute("data-observations", "0");
  });

  it("forwards local hover and clear events as shared timestamps", () => {
    const scene = createBenchmarkScene(1);
    const onSharedCursorChange = vi.fn();
    const timestampMs = scene.series[0]!.segments[0]!.points[0]!.timestampMs;
    render(chart(scene, null, onSharedCursorChange));

    fireEvent.click(screen.getByTestId("mock-cursor"));
    fireEvent.click(screen.getByTestId("mock-clear-cursor"));

    expect(onSharedCursorChange.mock.calls).toEqual([[timestampMs], [null]]);
  });
});
