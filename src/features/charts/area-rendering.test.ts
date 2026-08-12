import { describe, expect, it } from "vitest";

import type { ChartRendererScene } from "./renderer-adapter";
import { EChartsRendererAdapter, type EChartsRuntimePort } from "./echarts-adapter";

class FakeInstance {
  options: unknown[] = [];
  handlers = new Map<string, (event: unknown) => void>();
  disposed = false;

  setOption(option: unknown) {
    this.options.push(option);
  }
  on(eventName: string, handler: (event: unknown) => void) {
    this.handlers.set(eventName, handler);
  }
  off(eventName: string) {
    this.handlers.delete(eventName);
  }
  dispatchAction() {}
  resize() {}
  dispose() {
    this.disposed = true;
  }
  isDisposed() {
    return this.disposed;
  }
}

function scene(areaFillOpacity?: number): ChartRendererScene {
  return {
    xDomain: { fromMs: 1_000, toMs: 2_000 },
    series: [
      {
        identity: {
          nodeId: "node",
          equipmentId: "equipment",
          channelId: "channel",
          metric: "temperature.probe",
          nativeUnit: "degC",
        },
        name: "Saved area",
        colorToken: "#123456",
        dashStyle: "solid",
        markerShape: "circle",
        freshness: "live",
        visible: true,
        semanticMode: "instantaneous",
        ...(areaFillOpacity === undefined ? {} : { areaFillOpacity }),
        segments: [
          {
            id: "segment",
            seriesKey: "series",
            points: [{ id: "point", timestampMs: 1_500, value: 4.2, quality: "valid" }],
          },
        ],
      },
    ],
  };
}

describe("canonical area rendering", () => {
  it("adds deterministic ECharts areaStyle only for area-enabled series", () => {
    const instance = new FakeInstance();
    const adapter = new EChartsRendererAdapter({ init: () => instance } satisfies EChartsRuntimePort);
    adapter.initialize({
      container: document.createElement("div"),
      renderer: "canvas",
      reducedMotion: true,
      onCursor: () => undefined,
      onXDomainChange: () => undefined,
    });

    adapter.setScene(scene(0.14));
    const areaOption = instance.options.at(-1) as {
      series: Array<{ areaStyle?: { color: string; opacity: number } }>;
    };
    expect(areaOption.series[0].areaStyle).toEqual({ color: "#123456", opacity: 0.14 });

    adapter.setScene(scene());
    const lineOption = instance.options.at(-1) as { series: Array<{ areaStyle?: unknown }> };
    expect(lineOption.series[0].areaStyle).toBeUndefined();
  });
});
