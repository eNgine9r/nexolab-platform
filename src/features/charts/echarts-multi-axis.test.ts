import { describe, expect, it, vi } from "vitest";

import { chartSeriesKey } from "./domain";
import { EChartsRendererAdapter, type EChartsRuntimePort } from "./echarts-adapter";
import { createBenchmarkScene } from "./fixtures";
import { chartYAxisId } from "./units";

class FakeEChartsInstance {
  calls: Array<{ option: unknown; options: unknown }> = [];
  handlers = new Map<string, (event: unknown) => void>();
  disposeCount = 0;

  setOption(option: unknown, options?: unknown) {
    this.calls.push({ option, options });
  }

  on(eventName: string, handler: (event: unknown) => void) {
    this.handlers.set(eventName, handler);
  }

  off(eventName: string) {
    this.handlers.delete(eventName);
  }

  dispatchAction() {}

  containPixel() {
    return true;
  }

  convertFromPixel(_finder: object, value: [number, number]) {
    return value[0];
  }

  resize() {}

  dispose() {
    this.disposeCount += 1;
  }

  isDisposed() {
    return this.disposeCount > 0;
  }
}

function mixedScene() {
  const scene = createBenchmarkScene(3);
  const definitions = [
    { channelId: "voltage", metric: "electrical.voltage", unit: "V" },
    { channelId: "current", metric: "electrical.current", unit: "A" },
    { channelId: "power", metric: "electrical.active_power", unit: "W" },
  ];
  return {
    ...scene,
    series: scene.series.map((series, index) => ({
      ...series,
      identity: {
        ...series.identity,
        equipmentId: "meter-01",
        channelId: definitions[index].channelId,
        metric: definitions[index].metric,
        nativeUnit: definitions[index].unit,
      },
    })),
  };
}

function latestOption(instance: FakeEChartsInstance) {
  return instance.calls.at(-1)!.option as {
    yAxis: Array<{ id: string; name: string }>;
    series: Array<{ name: string; yAxisId: string }>;
  };
}

describe("ECharts equipment-centric multi-axis rendering", () => {
  it("binds V/A/W series to stable axes and removes hidden axes without remounting", () => {
    const instance = new FakeEChartsInstance();
    const init = vi.fn(() => instance);
    const adapter = new EChartsRendererAdapter({ init } satisfies EChartsRuntimePort);
    const scene = mixedScene();

    adapter.initialize({
      container: document.createElement("div"),
      renderer: "canvas",
      reducedMotion: true,
      onCursor: vi.fn(),
      onXDomainChange: vi.fn(),
    });
    adapter.setScene(scene);

    const initial = latestOption(instance);
    expect((instance.calls.at(-1)?.option as { aria?: { enabled?: boolean; decal?: { show?: boolean } } }).aria).toEqual(
      expect.objectContaining({ enabled: true, decal: { show: false } }),
    );
    expect(initial.yAxis).toHaveLength(3);
    for (const sourceSeries of scene.series) {
      const rendered = initial.series.find((series) => series.name === sourceSeries.name);
      expect(rendered?.yAxisId).toBe(chartYAxisId(sourceSeries.identity));
    }
    expect(instance.calls.at(-1)?.options).toMatchObject({ replaceMerge: ["series", "yAxis"] });

    adapter.setScene({
      ...scene,
      series: scene.series.map((series, index) => ({ ...series, visible: index !== 1 })),
    });
    expect(instance.calls.at(-1)?.options).toEqual({ notMerge: true, lazyUpdate: false });
    expect(latestOption(instance).yAxis.map((axis) => axis.id)).not.toContain(
      chartYAxisId(scene.series[1].identity),
    );

    adapter.setScene(scene);
    expect(instance.calls.at(-1)?.options).toEqual({ notMerge: true, lazyUpdate: false });
    expect(latestOption(instance).yAxis.map((axis) => axis.id)).toEqual(initial.yAxis.map((axis) => axis.id));

    const sameStructureScene = {
      ...scene,
      series: scene.series.map((series) => ({
        ...series,
        freshness: "stale" as const,
      })),
    };
    adapter.setScene(sameStructureScene);
    expect(instance.calls.at(-1)?.options).toEqual({
      notMerge: false,
      lazyUpdate: false,
      replaceMerge: ["series", "yAxis"],
    });

    adapter.setScene({
      ...scene,
      series: scene.series.map((series, index) => ({ ...series, visible: index === 2 })),
    });
    expect(latestOption(instance).yAxis.map((axis) => axis.id)).toEqual([
      chartYAxisId(scene.series[2].identity),
    ]);
    expect(latestOption(instance).series).toHaveLength(1);
    expect(chartSeriesKey(scene.series[2].identity)).toContain("power");
    expect(init).toHaveBeenCalledTimes(1);
  });
});
