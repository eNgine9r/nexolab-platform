import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RefrigerationControllerChart } from "@/components/refrigeration/refrigeration-controller-chart";
import { createBenchmarkScene } from "@/features/charts/fixtures";
import type { ChartRendererScene } from "@/features/charts/renderer-adapter";

vi.mock("@/components/charts/chart-shell", () => ({
  ChartShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/components/charts/chart-renderer-host", () => ({
  ChartRendererHost: ({
    scene,
    onXDomainChange,
  }: {
    scene: ChartRendererScene;
    onXDomainChange: (domain: { fromMs: number; toMs: number }) => void;
  }) => (
    <button
      type="button"
      data-testid="mock-renderer"
      data-from={scene.xDomain.fromMs}
      data-to={scene.xDomain.toMs}
      onClick={() =>
        onXDomainChange({
          fromMs: scene.xDomain.fromMs + 10_000,
          toMs: scene.xDomain.toMs - 10_000,
        })
      }
    >
      renderer
    </button>
  ),
}));

function chart(scene: ChartRendererScene) {
  return (
    <RefrigerationControllerChart
      title="Compressor"
      context="test"
      rangeLabel="range"
      scene={scene}
      emptyMessage="empty"
    />
  );
}

describe("RefrigerationControllerChart viewport lifecycle", () => {
  it("clears a stale local viewport when the loaded base domain changes", async () => {
    const first = createBenchmarkScene(1);
    const { rerender } = render(chart(first));

    fireEvent.click(screen.getByTestId("mock-renderer"));
    expect(screen.getByTestId("mock-renderer")).toHaveAttribute(
      "data-from",
      String(first.xDomain.fromMs + 10_000),
    );

    const second = {
      ...first,
      xDomain: {
        fromMs: first.xDomain.toMs + 60_000,
        toMs: first.xDomain.toMs + 180_000,
      },
    };
    rerender(chart(second));

    await waitFor(() =>
      expect(screen.getByTestId("mock-renderer")).toHaveAttribute("data-from", String(second.xDomain.fromMs)),
    );
    expect(screen.getByTestId("mock-renderer")).toHaveAttribute("data-to", String(second.xDomain.toMs));
  });
});
