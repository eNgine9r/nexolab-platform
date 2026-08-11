import { describe, expect, it, vi } from "vitest";

import { chartSeriesKey, type ChartPoint } from "./domain";
import { EChartsRendererAdapter, type EChartsRuntimePort } from "./echarts-adapter";
import { BENCHMARK_INTERVAL_MS, BENCHMARK_START_MS, createBenchmarkScene } from "./fixtures";

class FakeEChartsInstance {
  options: unknown[] = [];
  actions: object[] = [];
  handlers = new Map<string, (event: unknown) => void>();
  resizeCount = 0;
  disposeCount = 0;

  setOption(option: unknown) {
    this.options.push(option);
  }

  on(eventName: string, handler: (event: unknown) => void) {
    this.handlers.set(eventName, handler);
  }

  off(eventName: string) {
    this.handlers.delete(eventName);
  }

  dispatchAction(action: object) {
    this.actions.push(action);
  }

  resize() {
    this.resizeCount += 1;
  }

  dispose() {
    this.disposeCount += 1;
  }

  isDisposed() {
    return this.disposeCount > 0;
  }
}

function optionSeries(instance: FakeEChartsInstance): Array<Record<string, unknown>> {
  const option = instance.options.at(-1) as { series: Array<Record<string, unknown>> };
  return option.series;
}

describe("ECharts renderer adapter lifecycle", () => {
  it("initializes one persistent instance and maps gaps to independent line series", () => {
    const instance = new FakeEChartsInstance();
    const init = vi.fn(() => instance);
    const adapter = new EChartsRendererAdapter({ init } satisfies EChartsRuntimePort);
    const scene = createBenchmarkScene(1, { withGap: true });
    const container = document.createElement("div");

    adapter.initialize({
      container,
      renderer: "canvas",
      reducedMotion: true,
      onCursor: vi.fn(),
      onXDomainChange: vi.fn(),
    });
    adapter.initialize({
      container,
      renderer: "canvas",
      reducedMotion: true,
      onCursor: vi.fn(),
      onXDomainChange: vi.fn(),
    });
    adapter.setScene(scene);

    expect(init).toHaveBeenCalledTimes(1);
    expect(optionSeries(instance)).toHaveLength(2);
    expect(
      optionSeries(instance).every((series) => series.connectNulls === false && series.smooth === false),
    ).toBe(true);
  });

  it("reuses the instance for bounded incremental live-tail updates", () => {
    const instance = new FakeEChartsInstance();
    const init = vi.fn(() => instance);
    const adapter = new EChartsRendererAdapter({ init } satisfies EChartsRuntimePort);
    const scene = createBenchmarkScene(1);
    adapter.initialize({
      container: document.createElement("div"),
      renderer: "canvas",
      reducedMotion: true,
      maximumLivePoints: 240,
      onCursor: vi.fn(),
      onXDomainChange: vi.fn(),
    });
    adapter.setScene(scene);

    const series = scene.series[0];
    const segmentId = series.segments[0].id;
    const additions = Array.from({ length: 300 }, (_, index) => ({
      segmentId,
      point: {
        id: `tail-${index}`,
        timestampMs: BENCHMARK_START_MS + (240 + index) * BENCHMARK_INTERVAL_MS,
        value: index,
        quality: "valid" as const,
      } satisfies ChartPoint,
    }));
    adapter.appendLiveTail(chartSeriesKey(series.identity), additions);

    expect(init).toHaveBeenCalledTimes(1);
    const data = optionSeries(instance)[0].data as unknown[];
    expect(data).toHaveLength(240);
  });

  it("translates cursor events and clears handlers on dispose", () => {
    const instance = new FakeEChartsInstance();
    const onCursor = vi.fn();
    const onXDomainChange = vi.fn();
    const adapter = new EChartsRendererAdapter({ init: () => instance } satisfies EChartsRuntimePort);
    const scene = createBenchmarkScene(1);
    adapter.initialize({
      container: document.createElement("div"),
      renderer: "canvas",
      reducedMotion: true,
      onCursor,
      onXDomainChange,
    });
    adapter.setScene(scene);

    instance.handlers.get("updateAxisPointer")?.({ axesInfo: [{ value: BENCHMARK_START_MS }] });
    expect(onCursor).toHaveBeenCalledWith(
      expect.objectContaining({
        timestampMs: BENCHMARK_START_MS,
        point: expect.objectContaining({ value: -12 }),
      }),
    );
    instance.handlers.get("dataZoom")?.({ start: 25, end: 75 });
    expect(onXDomainChange).toHaveBeenCalledWith({
      fromMs: scene.xDomain.fromMs + (scene.xDomain.toMs - scene.xDomain.fromMs) * 0.25,
      toMs: scene.xDomain.fromMs + (scene.xDomain.toMs - scene.xDomain.fromMs) * 0.75,
    });

    adapter.resize();
    adapter.setSharedCursor(BENCHMARK_START_MS);
    adapter.dispose();
    expect(instance.resizeCount).toBe(1);
    expect(instance.actions).toHaveLength(2);
    expect(instance.handlers).toHaveLength(0);
    expect(instance.disposeCount).toBe(1);
    expect(adapter.isDisposed()).toBe(true);
  });

  it("adds a new continuity segment after reconnect without recreating the renderer", () => {
    const instance = new FakeEChartsInstance();
    const init = vi.fn(() => instance);
    const adapter = new EChartsRendererAdapter({ init } satisfies EChartsRuntimePort);
    const scene = createBenchmarkScene(1);
    adapter.initialize({
      container: document.createElement("div"),
      renderer: "canvas",
      reducedMotion: true,
      onCursor: vi.fn(),
      onXDomainChange: vi.fn(),
    });
    adapter.setScene(scene);
    adapter.appendLiveTail(chartSeriesKey(scene.series[0].identity), [
      {
        segmentId: "reconnected-segment",
        point: {
          id: "after-reconnect",
          timestampMs: scene.xDomain.toMs + BENCHMARK_INTERVAL_MS,
          value: -9,
          quality: "valid",
        },
      },
    ]);

    expect(init).toHaveBeenCalledTimes(1);
    expect(optionSeries(instance)).toHaveLength(2);
  });

  it("renders threshold, event and alarm-region evidence and removes hidden series", () => {
    const instance = new FakeEChartsInstance();
    const adapter = new EChartsRendererAdapter({ init: () => instance } satisfies EChartsRuntimePort);
    const scene = {
      ...createBenchmarkScene(1, { withEvidence: true }),
      events: [
        {
          id: "door-open",
          timestampMs: BENCHMARK_START_MS + BENCHMARK_INTERVAL_MS,
          type: "door",
          label: "Door opened",
          severity: "warning" as const,
        },
      ],
      alarmRegions: [
        {
          id: "offline",
          fromMs: BENCHMARK_START_MS + BENCHMARK_INTERVAL_MS,
          toMs: BENCHMARK_START_MS + 2 * BENCHMARK_INTERVAL_MS,
          label: "Offline",
          severity: "offline" as const,
        },
      ],
    };
    adapter.initialize({
      container: document.createElement("div"),
      renderer: "canvas",
      reducedMotion: true,
      onCursor: vi.fn(),
      onXDomainChange: vi.fn(),
    });
    adapter.setScene(scene);

    const rendered = optionSeries(instance)[0];
    expect((rendered.markLine as { data: unknown[] }).data).toHaveLength(2);
    expect((rendered.markArea as { data: unknown[] }).data).toHaveLength(1);

    adapter.setScene({
      ...scene,
      series: scene.series.map((series) => ({ ...series, visible: false })),
    });
    expect(optionSeries(instance)).toHaveLength(0);
  });
});
