import { fireEvent, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createBenchmarkScene } from "@/features/charts/fixtures";
import type { ChartRendererAdapter } from "@/features/charts/renderer-adapter";

import { ChartRendererHost } from "./chart-renderer-host";

const observerState = { callbacks: [] as ResizeObserverCallback[], disconnects: 0 };

class ResizeObserverMock {
  constructor(callback: ResizeObserverCallback) {
    observerState.callbacks.push(callback);
  }
  observe() {}
  unobserve() {}
  disconnect() {
    observerState.disconnects += 1;
  }
}

function fakeAdapter(): ChartRendererAdapter & {
  initialize: ReturnType<typeof vi.fn<ChartRendererAdapter["initialize"]>>;
  setScene: ReturnType<typeof vi.fn<ChartRendererAdapter["setScene"]>>;
  resize: ReturnType<typeof vi.fn<ChartRendererAdapter["resize"]>>;
  dispose: ReturnType<typeof vi.fn<ChartRendererAdapter["dispose"]>>;
} {
  let disposed = true;
  return {
    initialize: vi.fn<ChartRendererAdapter["initialize"]>(() => {
      disposed = false;
    }),
    setScene: vi.fn<ChartRendererAdapter["setScene"]>(),
    appendLiveTail: vi.fn<ChartRendererAdapter["appendLiveTail"]>(),
    setSharedCursor: vi.fn<ChartRendererAdapter["setSharedCursor"]>(),
    setSharedXDomain: vi.fn<ChartRendererAdapter["setSharedXDomain"]>(),
    resize: vi.fn<ChartRendererAdapter["resize"]>(),
    resetZoom: vi.fn<ChartRendererAdapter["resetZoom"]>(),
    dispose: vi.fn<ChartRendererAdapter["dispose"]>(() => {
      disposed = true;
    }),
    isDisposed: () => disposed,
  };
}

describe("ChartRendererHost", () => {
  beforeEach(() => {
    observerState.callbacks = [];
    observerState.disconnects = 0;
    vi.stubGlobal("ResizeObserver", ResizeObserverMock);
  });

  it("keeps one renderer instance through scene updates and disposes on true unmount", () => {
    const adapter = fakeAdapter();
    const firstScene = createBenchmarkScene(1);
    const secondScene = createBenchmarkScene(8);
    const view = render(
      <ChartRendererHost adapter={adapter} scene={firstScene} onCursor={vi.fn()} onXDomainChange={vi.fn()} />,
    );
    view.rerender(
      <ChartRendererHost
        adapter={adapter}
        scene={secondScene}
        onCursor={vi.fn()}
        onXDomainChange={vi.fn()}
      />,
    );

    expect(adapter.initialize).toHaveBeenCalledTimes(1);
    expect(adapter.setScene).toHaveBeenLastCalledWith(secondScene);
    expect(observerState.callbacks).toHaveLength(1);
    observerState.callbacks[0]([], {} as ResizeObserver);
    expect(adapter.resize).toHaveBeenCalledTimes(1);

    view.unmount();
    expect(observerState.disconnects).toBe(1);
    expect(adapter.dispose).toHaveBeenCalledTimes(1);
  });
  it("supports deterministic keyboard inspection over real visible chart points", () => {
    const adapter = fakeAdapter();
    const scene = createBenchmarkScene(2);
    const onCursor = vi.fn();
    const view = render(
      <ChartRendererHost adapter={adapter} scene={scene} onCursor={onCursor} onXDomainChange={vi.fn()} />,
    );
    const host = view.getByRole("application", { name: "Interactive telemetry plot" });
    const firstTimestamp = scene.series[0].segments[0].points[0].timestampMs;
    const lastTimestamp = scene.series.at(-1)!.segments.at(-1)!.points.at(-1)!.timestampMs;
    fireEvent.keyDown(host, { key: "Home" });
    expect(adapter.setSharedCursor).toHaveBeenLastCalledWith(firstTimestamp);
    expect(onCursor.mock.calls.at(-1)?.[0]).toMatchObject({ timestampMs: firstTimestamp });
    fireEvent.keyDown(host, { key: "End" });
    expect(adapter.setSharedCursor).toHaveBeenLastCalledWith(lastTimestamp);
    expect(onCursor.mock.calls.at(-1)?.[0]).toMatchObject({ timestampMs: lastTimestamp });
    fireEvent.keyDown(host, { key: "Escape" });
    expect(adapter.setSharedCursor).toHaveBeenLastCalledWith(null);
    expect(onCursor).toHaveBeenLastCalledWith(null);
  });
});
