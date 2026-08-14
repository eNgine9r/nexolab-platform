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
    expect(instance.options.at(-1)).toMatchObject({
      tooltip: {
        trigger: "axis",
        showContent: false,
        axisPointer: { type: "line", snap: false },
        appendToBody: false,
        confine: true,
        transitionDuration: 0,
      },
    });
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

  it("returns one deterministic nearest-point inspection per visible series", () => {
    const instance = new FakeEChartsInstance();
    const onCursor = vi.fn();
    const onXDomainChange = vi.fn();
    const adapter = new EChartsRendererAdapter({ init: () => instance } satisfies EChartsRuntimePort);
    const scene = createBenchmarkScene(2);
    adapter.initialize({
      container: document.createElement("div"),
      renderer: "canvas",
      reducedMotion: true,
      onCursor,
      onXDomainChange,
    });
    adapter.setScene(scene);

    instance.handlers.get("updateAxisPointer")?.({ axesInfo: [{ value: BENCHMARK_START_MS }] });
    expect(onCursor).toHaveBeenCalledWith({
      timestampMs: BENCHMARK_START_MS,
      series: scene.series.map((series) => ({
        seriesKey: chartSeriesKey(series.identity),
        point: series.segments[0].points[0],
        freshness: series.freshness,
      })),
    });

    instance.handlers.get("dataZoom")?.({ start: 25, end: 75 });
    expect(onXDomainChange).toHaveBeenCalledWith({
      fromMs: scene.xDomain.fromMs + (scene.xDomain.toMs - scene.xDomain.fromMs) * 0.25,
      toMs: scene.xDomain.fromMs + (scene.xDomain.toMs - scene.xDomain.fromMs) * 0.75,
    });

    adapter.resize();
    adapter.setSharedCursor(BENCHMARK_START_MS);
    adapter.dispose();
    expect(instance.resizeCount).toBe(1);
    expect(instance.actions).toEqual([
      { type: "updateAxisPointer", xAxisIndex: 0, value: BENCHMARK_START_MS },
    ]);
    expect(instance.handlers).toHaveLength(0);
    expect(instance.disposeCount).toBe(1);
    expect(adapter.isDisposed()).toBe(true);
  });

  it("keeps the shared cursor while marking explicitly out-of-tolerance samples unavailable", () => {
    const instance = new FakeEChartsInstance();
    const onCursor = vi.fn();
    const adapter = new EChartsRendererAdapter({ init: () => instance } satisfies EChartsRuntimePort);
    const scene = { ...createBenchmarkScene(2), cursorToleranceMs: 1_000 };
    adapter.initialize({
      container: document.createElement("div"),
      renderer: "canvas",
      reducedMotion: true,
      onCursor,
      onXDomainChange: vi.fn(),
    });
    adapter.setScene(scene);

    const cursor = BENCHMARK_START_MS + BENCHMARK_INTERVAL_MS / 2;
    instance.handlers.get("updateAxisPointer")?.({ axesInfo: [{ value: cursor }] });

    expect(onCursor).toHaveBeenCalledWith({
      timestampMs: cursor,
      series: scene.series.map((series) => ({
        seriesKey: chartSeriesKey(series.identity),
        point: null,
        freshness: series.freshness,
      })),
    });
  });

  it("derives cursor tolerance from a slow valid source cadence so inspection does not flicker between samples", () => {
    const instance = new FakeEChartsInstance();
    const onCursor = vi.fn();
    const adapter = new EChartsRendererAdapter({ init: () => instance } satisfies EChartsRuntimePort);
    const scene = createBenchmarkScene(1);
    const baseSeries = scene.series[0];
    const slowPoints = [0, 60_000, 120_000].map((offset, index) => ({
      ...baseSeries.segments[0].points[0],
      id: `slow-${index}`,
      timestampMs: BENCHMARK_START_MS + offset,
      value: index,
    }));
    const slowScene = {
      ...scene,
      series: [
        {
          ...baseSeries,
          segments: [{ ...baseSeries.segments[0], points: slowPoints }],
        },
      ],
    };
    adapter.initialize({
      container: document.createElement("div"),
      renderer: "canvas",
      reducedMotion: true,
      onCursor,
      onXDomainChange: vi.fn(),
    });
    adapter.setScene(slowScene);

    const cursor = BENCHMARK_START_MS + 30_000;
    instance.handlers.get("updateAxisPointer")?.({ axesInfo: [{ value: cursor }] });

    expect(onCursor).toHaveBeenCalledWith({
      timestampMs: cursor,
      series: [
        {
          seriesKey: chartSeriesKey(baseSeries.identity),
          point: slowPoints[0],
          freshness: baseSeries.freshness,
        },
      ],
    });
  });

  it("never borrows a sample across an explicit continuity gap", () => {
    const instance = new FakeEChartsInstance();
    const onCursor = vi.fn();
    const adapter = new EChartsRendererAdapter({ init: () => instance } satisfies EChartsRuntimePort);
    const scene = createBenchmarkScene(1, { withGap: true });
    adapter.initialize({
      container: document.createElement("div"),
      renderer: "canvas",
      reducedMotion: true,
      onCursor,
      onXDomainChange: vi.fn(),
    });
    adapter.setScene(scene);

    const firstSegmentLast = scene.series[0].segments[0].points.at(-1)!;
    const secondSegmentFirst = scene.series[0].segments[1].points[0];
    const cursor = firstSegmentLast.timestampMs + (secondSegmentFirst.timestampMs - firstSegmentLast.timestampMs) / 2;
    instance.handlers.get("updateAxisPointer")?.({ axesInfo: [{ value: cursor }] });

    expect(onCursor).toHaveBeenCalledWith({
      timestampMs: cursor,
      series: [
        {
          seriesKey: chartSeriesKey(scene.series[0].identity),
          point: null,
          freshness: scene.series[0].freshness,
        },
      ],
    });
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

  it("renders only canonical deduplicated event evidence and hides collision-prone labels", () => {
    const instance = new FakeEChartsInstance();
    const adapter = new EChartsRendererAdapter({ init: () => instance } satisfies EChartsRuntimePort);
    const canonicalEvent = {
      id: "door-open",
      timestampMs: BENCHMARK_START_MS + BENCHMARK_INTERVAL_MS,
      type: "door",
      label: "Door opened",
      source: { entityId: "door-event-1", entityType: "door_event" },
      severity: "warning" as const,
    };
    const scene = {
      ...createBenchmarkScene(1, { withEvidence: true }),
      events: [
        canonicalEvent,
        { ...canonicalEvent },
        {
          ...canonicalEvent,
          id: "invalid-source",
          source: { entityId: "", entityType: "door_event" },
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
    const markLineData = (rendered.markLine as { data: Array<Record<string, unknown>> }).data;
    expect(markLineData).toHaveLength(2);
    expect(markLineData.filter((entry) => entry.eventId === "door-open")).toHaveLength(1);
    expect(markLineData.find((entry) => entry.eventId === "door-open")?.label).toEqual({ show: false });
    expect((rendered.markArea as { data: unknown[] }).data).toHaveLength(1);

    adapter.setScene({
      ...scene,
      series: scene.series.map((series) => ({ ...series, visible: false })),
    });
    expect(optionSeries(instance)).toHaveLength(0);
  });
});
