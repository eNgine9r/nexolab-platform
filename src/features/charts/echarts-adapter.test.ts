import { describe, expect, it, vi } from "vitest";

import { chartSeriesKey, type ChartPoint } from "./domain";
import {
  EChartsRendererAdapter,
  ZOOM_COMMIT_IDLE_MS,
  sceneDataSignature,
  type EChartsRuntimePort,
} from "./echarts-adapter";
import { BENCHMARK_INTERVAL_MS, BENCHMARK_START_MS, createBenchmarkScene } from "./fixtures";

class FakeEChartsInstance {
  options: unknown[] = [];
  actions: object[] = [];
  handlers = new Map<string, (event: unknown) => void>();
  resizeCount = 0;
  disposeCount = 0;
  convertFinders: object[] = [];
  convertValues: Array<number | number[]> = [];

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

  containPixel() {
    return true;
  }

  convertFromPixel(finder: object, value: number | number[]) {
    this.convertFinders.push(finder);
    this.convertValues.push(value);
    const x = Array.isArray(value) ? value[0] : value;
    return BENCHMARK_START_MS + x;
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

function waitForZoomCommit(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ZOOM_COMMIT_IDLE_MS + 10));
}

function optionSeries(instance: FakeEChartsInstance): Array<Record<string, unknown>> {
  const option = instance.options.at(-1) as { series: Array<Record<string, unknown>> };
  return option.series;
}

async function nextAnimationFrame(): Promise<void> {
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
}

describe("ECharts renderer adapter lifecycle", () => {
  it("changes axis labels only when the display timezone changes", () => {
    const instance = new FakeEChartsInstance();
    const init = vi.fn(() => instance);
    const adapter = new EChartsRendererAdapter({ init });
    const scene = createBenchmarkScene(1);
    adapter.initialize({
      container: document.createElement("div"),
      renderer: "canvas",
      reducedMotion: true,
      onCursor: vi.fn(),
      onXDomainChange: vi.fn(),
    });
    adapter.setScene({ ...scene, displayTimeZone: "UTC" });
    const utc = instance.options.at(-1) as {
      xAxis: { axisLabel: { formatter: (value: number) => string } };
      series: unknown;
      dataZoom: unknown;
    };
    const timestamp = Date.parse("2026-07-01T10:20:30Z");
    expect(utc.xAxis.axisLabel.formatter(timestamp)).toContain("10:20");
    adapter.setScene({ ...scene, displayTimeZone: "Europe/Kyiv" });
    const local = instance.options.at(-1) as typeof utc;
    expect(local.xAxis.axisLabel.formatter(timestamp)).toContain("13:20");
    expect(local.series).toEqual(utc.series);
    expect(local.dataZoom).toEqual(utc.dataZoom);
    expect(init).toHaveBeenCalledTimes(1);
    adapter.dispose();
  });
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
    // #1810: one line series per channel; the continuity break is an explicit null point.
    expect(optionSeries(instance)).toHaveLength(1);
    expect(
      optionSeries(instance).every((series) => series.connectNulls === false && series.smooth === false),
    ).toBe(true);
    const lineData = optionSeries(instance)[0].data as Array<[number, number | null]>;
    expect(lineData.filter(([, value]) => value === null)).toHaveLength(1);
    expect(instance.options.at(-1)).toMatchObject({ animation: false });
    expect(instance.options.at(-1)).toMatchObject({
      tooltip: {
        trigger: "axis",
        showContent: false,
        axisPointer: { type: "line", snap: false },
        appendToBody: false,
        confine: true,
        transitionDuration: 0,
      },
      dataZoom: [
        {
          type: "inside",
          xAxisIndex: 0,
          filterMode: "none",
          rangeMode: ["value", "value"],
          startValue: scene.xDomain.fromMs,
          endValue: scene.xDomain.toMs,
          zoomOnMouseWheel: true,
          moveOnMouseMove: true,
          moveOnMouseWheel: false,
          preventDefaultMouseMove: true,
        },
      ],
    });
  });

  it("uses adapter-owned mouse drag selection without rendering a range slider", () => {
    const instance = new FakeEChartsInstance();
    const onRangeSelectionChange = vi.fn();
    const onXDomainChange = vi.fn();
    const adapter = new EChartsRendererAdapter({ init: () => instance } satisfies EChartsRuntimePort);
    const scene = {
      ...createBenchmarkScene(1),
      rangeSelectionEnabled: true,
      rangeSelection: null,
    };
    const container = document.createElement("div");
    document.body.appendChild(container);
    vi.spyOn(container, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 320,
      bottom: 200,
      width: 320,
      height: 200,
      toJSON: () => ({}),
    });

    adapter.initialize({
      container,
      renderer: "canvas",
      reducedMotion: true,
      onCursor: vi.fn(),
      onXDomainChange,
      onRangeSelectionChange,
    });
    adapter.setScene(scene);
    vi.spyOn(instance, "containPixel").mockReturnValue(false);

    const option = instance.options.at(-1) as { dataZoom: unknown[]; brush?: unknown };
    expect(option).toMatchObject({
      grid: { bottom: 58 },
      dataZoom: [
        {
          type: "inside",
          startValue: scene.xDomain.fromMs,
          endValue: scene.xDomain.toMs,
          moveOnMouseMove: false,
        },
      ],
    });
    expect(option.dataZoom).toHaveLength(1);
    expect(option.brush).toBeUndefined();

    const observedPointerDown = vi.fn();
    container.addEventListener("pointerdown", observedPointerDown);

    container.dispatchEvent(
      new MouseEvent("pointerdown", { button: 0, clientX: 90, clientY: 100, bubbles: true }),
    );
    instance.handlers.get("dataZoom")?.({ start: 10, end: 90 });
    window.dispatchEvent(new MouseEvent("pointermove", { buttons: 1, clientX: 30, clientY: 100 }));
    window.dispatchEvent(new MouseEvent("pointerup", { button: 0, clientX: 30, clientY: 100 }));

    expect(observedPointerDown).not.toHaveBeenCalled();
    expect(instance.convertFinders[0]).toEqual({ xAxisIndex: 0 });
    expect(instance.convertValues[0]).toBe(90);
    expect(onXDomainChange).not.toHaveBeenCalled();
    expect(onRangeSelectionChange).toHaveBeenCalledWith({
      fromMs: BENCHMARK_START_MS + 30,
      toMs: BENCHMARK_START_MS + 90,
    });

    adapter.setScene({
      ...scene,
      rangeSelection: { fromMs: BENCHMARK_START_MS + 30, toMs: BENCHMARK_START_MS + 90 },
    });
    expect(optionSeries(instance)[0]).toMatchObject({
      markArea: {
        silent: true,
        data: [
          [
            { name: "Selected analysis interval", xAxis: BENCHMARK_START_MS + 30 },
            { xAxis: BENCHMARK_START_MS + 90 },
          ],
        ],
      },
    });

    onRangeSelectionChange.mockClear();
    container.dispatchEvent(
      new MouseEvent("pointerdown", { button: 0, clientX: 40, clientY: 100, bubbles: true }),
    );
    window.dispatchEvent(new MouseEvent("pointermove", { buttons: 1, clientX: 100, clientY: 100 }));
    window.dispatchEvent(new Event("pointercancel"));
    window.dispatchEvent(new MouseEvent("pointerup", { clientX: 110, clientY: 100 }));
    expect(onRangeSelectionChange).not.toHaveBeenCalled();
    adapter.dispose();
    container.remove();
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

  it("returns one deterministic nearest-point inspection per visible series", async () => {
    const instance = new FakeEChartsInstance();
    const onCursor = vi.fn();
    const onXDomainChange = vi.fn();
    const adapter = new EChartsRendererAdapter({ init: () => instance } satisfies EChartsRuntimePort);
    const scene = createBenchmarkScene(2);
    const container = document.createElement("div");
    vi.spyOn(container, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 320,
      bottom: 200,
      width: 320,
      height: 200,
      toJSON: () => ({}),
    });
    adapter.initialize({
      container,
      renderer: "canvas",
      reducedMotion: true,
      onCursor,
      onXDomainChange,
    });
    adapter.setScene(scene);

    container.dispatchEvent(new MouseEvent("mousemove", { clientX: 0, clientY: 120 }));
    await nextAnimationFrame();
    expect(instance.convertFinders.at(-1)).toEqual({ xAxisIndex: 0 });
    expect(onCursor).toHaveBeenCalledWith({
      timestampMs: BENCHMARK_START_MS,
      series: scene.series.map((series) => ({
        seriesKey: chartSeriesKey(series.identity),
        point: series.segments[0].points[0],
        freshness: series.freshness,
      })),
    });

    const callsAfterHostPointer = onCursor.mock.calls.length;
    instance.handlers.get("updateAxisPointer")?.({ axesInfo: [] });
    expect(onCursor).toHaveBeenCalledTimes(callsAfterHostPointer);
    expect(onCursor.mock.calls.at(-1)?.[0]).toMatchObject({ timestampMs: BENCHMARK_START_MS });

    instance.handlers.get("dataZoom")?.({ start: 25, end: 75 });
    await waitForZoomCommit();
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

  it("coalesces pointer and axis-pointer bursts to one latest cursor commit per animation frame", async () => {
    const instance = new FakeEChartsInstance();
    const onCursor = vi.fn();
    const adapter = new EChartsRendererAdapter({ init: () => instance } satisfies EChartsRuntimePort);
    const scene = createBenchmarkScene(8);
    const container = document.createElement("div");
    vi.spyOn(container, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 320,
      bottom: 200,
      width: 320,
      height: 200,
      toJSON: () => ({}),
    });
    adapter.initialize({
      container,
      renderer: "canvas",
      reducedMotion: true,
      onCursor,
      onXDomainChange: vi.fn(),
    });
    adapter.setScene(scene);

    for (let index = 0; index < 120; index += 1) {
      container.dispatchEvent(new MouseEvent("mousemove", { clientX: index, clientY: 120 }));
    }
    // #1866: under the mouse, ECharts' own axis-pointer event (and shared-cursor echoes) never
    // compete with the mouse position: alternating sources made the inspected values flicker.
    instance.handlers.get("updateAxisPointer")?.({ axesInfo: [{ value: BENCHMARK_START_MS + 200 }] });
    expect(onCursor).not.toHaveBeenCalled();

    await nextAnimationFrame();
    expect(onCursor).toHaveBeenCalledTimes(1);
    expect(onCursor).toHaveBeenLastCalledWith(
      expect.objectContaining({ timestampMs: BENCHMARK_START_MS + 119 }),
    );

    container.dispatchEvent(new MouseEvent("mousemove", { clientX: 119, clientY: 120 }));
    await nextAnimationFrame();
    expect(onCursor).toHaveBeenCalledTimes(1);

    adapter.setScene(scene);
    container.dispatchEvent(new MouseEvent("mousemove", { clientX: 119, clientY: 120 }));
    await nextAnimationFrame();
    expect(onCursor).toHaveBeenCalledTimes(2);

    // Away from the mouse (touch, keyboard or another linked plot), the axis pointer drives it.
    container.dispatchEvent(new MouseEvent("mouseleave"));
    expect(onCursor).toHaveBeenCalledTimes(3);
    expect(onCursor).toHaveBeenLastCalledWith(null);
    const latestTimestamp = BENCHMARK_START_MS + 200;
    instance.handlers.get("updateAxisPointer")?.({ axesInfo: [{ value: latestTimestamp }] });
    await nextAnimationFrame();
    expect(onCursor).toHaveBeenCalledTimes(4);
    expect(onCursor).toHaveBeenLastCalledWith(expect.objectContaining({ timestampMs: latestTimestamp }));

    container.dispatchEvent(new MouseEvent("mousemove", { clientX: 210, clientY: 120 }));
    adapter.dispose();
    await nextAnimationFrame();
    expect(onCursor).toHaveBeenCalledTimes(4);
  });

  it("freezes Exact Inspector callbacks during primary-button native pan and resumes after release", async () => {
    const instance = new FakeEChartsInstance();
    const onCursor = vi.fn();
    const onXDomainChange = vi.fn();
    const adapter = new EChartsRendererAdapter({ init: () => instance } satisfies EChartsRuntimePort);
    const scene = createBenchmarkScene(1);
    const container = document.createElement("div");
    vi.spyOn(container, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 320,
      bottom: 200,
      width: 320,
      height: 200,
      toJSON: () => ({}),
    });
    adapter.initialize({
      container,
      renderer: "canvas",
      reducedMotion: true,
      onCursor,
      onXDomainChange,
    });
    adapter.setScene(scene);

    container.dispatchEvent(new MouseEvent("mousemove", { clientX: 20, clientY: 120 }));
    await nextAnimationFrame();
    expect(onCursor).toHaveBeenCalledTimes(1);

    container.dispatchEvent(new MouseEvent("mousedown", { button: 0, clientX: 20, clientY: 120 }));
    const callsBeforeDrag = onCursor.mock.calls.length;
    container.dispatchEvent(new MouseEvent("mousemove", { buttons: 1, clientX: 80, clientY: 120 }));
    instance.handlers.get("updateAxisPointer")?.({ axesInfo: [{ value: BENCHMARK_START_MS + 80 }] });
    expect(onCursor).toHaveBeenCalledTimes(callsBeforeDrag);

    instance.handlers.get("dataZoom")?.({ start: 10, end: 90 });
    instance.handlers.get("dataZoom")?.({ start: 20, end: 100 });
    expect(onXDomainChange).not.toHaveBeenCalled();

    const duration = scene.xDomain.toMs - scene.xDomain.fromMs;
    window.dispatchEvent(new MouseEvent("mouseup", { button: 0 }));
    expect(onXDomainChange).toHaveBeenCalledTimes(1);
    expect(onXDomainChange).toHaveBeenLastCalledWith({
      fromMs: scene.xDomain.fromMs + duration * 0.2,
      toMs: scene.xDomain.toMs,
    });
    container.dispatchEvent(new MouseEvent("mousemove", { clientX: 80, clientY: 120 }));
    await nextAnimationFrame();
    expect(onCursor).toHaveBeenCalledTimes(callsBeforeDrag + 1);

    container.dispatchEvent(new MouseEvent("mousedown", { button: 0, clientX: 80, clientY: 120 }));
    instance.handlers.get("dataZoom")?.({ start: 30, end: 90 });
    container.dispatchEvent(new MouseEvent("mousemove", { buttons: 0, clientX: 90, clientY: 120 }));
    await nextAnimationFrame();
    expect(onXDomainChange).toHaveBeenCalledTimes(2);
    expect(onXDomainChange).toHaveBeenLastCalledWith({
      fromMs: scene.xDomain.fromMs + duration * 0.3,
      toMs: scene.xDomain.fromMs + duration * 0.9,
    });
    expect(onCursor).toHaveBeenCalledTimes(callsBeforeDrag + 2);

    container.dispatchEvent(new MouseEvent("mousedown", { button: 2, clientX: 90, clientY: 120 }));
    container.dispatchEvent(new MouseEvent("mousemove", { clientX: 100, clientY: 120 }));
    await nextAnimationFrame();
    expect(onCursor).toHaveBeenCalledTimes(callsBeforeDrag + 3);

    adapter.dispose();
  });

  it("keeps a constant pan span against the stable interaction domain after zoom", async () => {
    const instance = new FakeEChartsInstance();
    const onXDomainChange = vi.fn();
    const adapter = new EChartsRendererAdapter({ init: () => instance } satisfies EChartsRuntimePort);
    const scene = createBenchmarkScene(1);
    const interactionDomain = scene.xDomain;
    const container = document.createElement("div");
    vi.spyOn(container, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 320,
      bottom: 200,
      width: 320,
      height: 200,
      toJSON: () => ({}),
    });
    adapter.initialize({
      container,
      renderer: "canvas",
      reducedMotion: true,
      onCursor: vi.fn(),
      onXDomainChange,
    });
    adapter.setScene({ ...scene, interactionDomain });

    instance.handlers.get("dataZoom")?.({ start: 25, end: 75 });
    await waitForZoomCommit();
    const zoomedDomain = onXDomainChange.mock.calls.at(-1)?.[0];
    expect(zoomedDomain).toEqual({
      fromMs: interactionDomain.fromMs + (interactionDomain.toMs - interactionDomain.fromMs) * 0.25,
      toMs: interactionDomain.fromMs + (interactionDomain.toMs - interactionDomain.fromMs) * 0.75,
    });

    adapter.setScene({ ...scene, xDomain: zoomedDomain, interactionDomain });
    expect(instance.options.at(-1)).toMatchObject({
      xAxis: { min: interactionDomain.fromMs, max: interactionDomain.toMs },
      dataZoom: [
        {
          rangeMode: ["value", "value"],
          startValue: zoomedDomain.fromMs,
          endValue: zoomedDomain.toMs,
        },
      ],
    });

    container.dispatchEvent(new MouseEvent("mousedown", { button: 0, clientX: 80, clientY: 120 }));
    instance.handlers.get("dataZoom")?.({ start: 30, end: 80 });
    instance.handlers.get("dataZoom")?.({ start: 35, end: 85 });
    expect(onXDomainChange).toHaveBeenCalledTimes(1);
    window.dispatchEvent(new MouseEvent("mouseup", { button: 0 }));

    const pannedDomain = onXDomainChange.mock.calls.at(-1)?.[0];
    expect(pannedDomain).toEqual({
      fromMs: interactionDomain.fromMs + (interactionDomain.toMs - interactionDomain.fromMs) * 0.35,
      toMs: interactionDomain.fromMs + (interactionDomain.toMs - interactionDomain.fromMs) * 0.85,
    });
    expect(pannedDomain.toMs - pannedDomain.fromMs).toBe(zoomedDomain.toMs - zoomedDomain.fromMs);

    adapter.dispose();
  });

  it("keeps the shared cursor while marking explicitly out-of-tolerance samples unavailable", async () => {
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
    await nextAnimationFrame();

    expect(onCursor).toHaveBeenCalledWith({
      timestampMs: cursor,
      series: scene.series.map((series) => ({
        seriesKey: chartSeriesKey(series.identity),
        point: null,
        freshness: series.freshness,
      })),
    });
  });

  it("derives cursor tolerance from a slow valid source cadence so inspection does not flicker between samples", async () => {
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
    await nextAnimationFrame();

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

  it("never borrows a sample across an explicit continuity gap", async () => {
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
    const cursor =
      firstSegmentLast.timestampMs + (secondSegmentFirst.timestampMs - firstSegmentLast.timestampMs) / 2;
    instance.handlers.get("updateAxisPointer")?.({ axesInfo: [{ value: cursor }] });
    await nextAnimationFrame();

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
    const lines = optionSeries(instance).filter((series) => series.type === "line");
    expect(lines).toHaveLength(1);
    const data = lines[0].data as Array<[number, number | null]>;
    expect(data.some(([, value]) => value === null)).toBe(true);
    expect(data.at(-1)).toEqual([scene.xDomain.toMs + BENCHMARK_INTERVAL_MS, -9]);
    // The isolated post-reconnect measurement has no line yet, so it is drawn as a marker.
    const markers = optionSeries(instance).find((series) => series.type === "scatter");
    expect(markers?.data).toEqual([
      { value: [scene.xDomain.toMs + BENCHMARK_INTERVAL_MS, -9], symbolSize: 6 },
    ]);
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

  it("coalesces a wheel-zoom burst into one viewport commit (#1810)", async () => {
    const instance = new FakeEChartsInstance();
    const onXDomainChange = vi.fn();
    const adapter = new EChartsRendererAdapter({ init: () => instance } satisfies EChartsRuntimePort);
    const scene = createBenchmarkScene(1);
    adapter.initialize({
      container: document.createElement("div"),
      renderer: "canvas",
      reducedMotion: false,
      onCursor: vi.fn(),
      onXDomainChange,
    });
    adapter.setScene(scene);
    for (let step = 0; step < 10; step += 1) {
      instance.handlers.get("dataZoom")?.({ start: step, end: 100 - step });
    }
    expect(onXDomainChange).not.toHaveBeenCalled();
    await waitForZoomCommit();
    expect(onXDomainChange).toHaveBeenCalledTimes(1);
    const duration = scene.xDomain.toMs - scene.xDomain.fromMs;
    expect(onXDomainChange).toHaveBeenLastCalledWith({
      fromMs: scene.xDomain.fromMs + duration * 0.09,
      toMs: scene.xDomain.fromMs + duration * 0.91,
    });
    adapter.dispose();
  });

  it("moves only the window when the data is unchanged (#1810)", () => {
    const instance = new FakeEChartsInstance();
    const adapter = new EChartsRendererAdapter({ init: () => instance } satisfies EChartsRuntimePort);
    const scene = createBenchmarkScene(4, { withGap: true });
    adapter.initialize({
      container: document.createElement("div"),
      renderer: "canvas",
      reducedMotion: true,
      onCursor: vi.fn(),
      onXDomainChange: vi.fn(),
    });
    adapter.setScene(scene);
    const zoomed = { fromMs: scene.xDomain.fromMs + 1_000, toMs: scene.xDomain.toMs - 1_000 };
    // A rebuilt but identical scene object (as React produces on every viewport change).
    const rebuilt = structuredClone({ ...scene, xDomain: zoomed, interactionDomain: scene.xDomain });
    adapter.setScene(rebuilt);
    const windowOnly = instance.options.at(-1) as Record<string, unknown>;
    expect(windowOnly.series).toBeUndefined();
    expect(windowOnly).toMatchObject({
      xAxis: { min: scene.xDomain.fromMs, max: scene.xDomain.toMs },
      dataZoom: [{ startValue: zoomed.fromMs, endValue: zoomed.toMs }],
    });

    const changedPoint = structuredClone(rebuilt);
    changedPoint.series[0].segments[0].points[3].value += 0.001;
    expect(sceneDataSignature(changedPoint)).not.toBe(sceneDataSignature(rebuilt));
    adapter.setScene(changedPoint);
    expect((instance.options.at(-1) as Record<string, unknown>).series).toBeDefined();
    adapter.dispose();
  });

  it("keeps an uncommitted wheel zoom when a live refresh arrives first (#1810)", () => {
    const instance = new FakeEChartsInstance();
    const adapter = new EChartsRendererAdapter({ init: () => instance } satisfies EChartsRuntimePort);
    const scene = createBenchmarkScene(1);
    adapter.initialize({
      container: document.createElement("div"),
      renderer: "canvas",
      reducedMotion: true,
      onCursor: vi.fn(),
      onXDomainChange: vi.fn(),
    });
    adapter.setScene(scene);
    instance.handlers.get("dataZoom")?.({ start: 25, end: 75 });
    const duration = scene.xDomain.toMs - scene.xDomain.fromMs;
    // A refresh with the pre-zoom window, before the idle commit.
    adapter.setScene(structuredClone(scene));
    expect(instance.options.at(-1)).toMatchObject({
      dataZoom: [
        {
          startValue: scene.xDomain.fromMs + duration * 0.25,
          endValue: scene.xDomain.fromMs + duration * 0.75,
        },
      ],
    });
    adapter.dispose();
  });

  it("fingerprints pin reason contents, not only their number (#1810)", () => {
    const scene = createBenchmarkScene(1, { withEvidence: true });
    const changed = structuredClone(scene);
    const pinned = changed.series[0].segments
      .flatMap((segment) => segment.points)
      .find((point) => point.pinReasons?.length);
    expect(pinned).toBeDefined();
    pinned!.pinReasons = pinned!.pinReasons!.map(() => "alarm" as const);
    expect(sceneDataSignature(changed)).not.toBe(sceneDataSignature(scene));
  });

  it("commits a programmatic reset synchronously and lets a pan supersede a pending wheel commit (#1810)", async () => {
    const instance = new FakeEChartsInstance();
    const onXDomainChange = vi.fn();
    // The real runtime emits dataZoom synchronously from dispatchAction.
    instance.dispatchAction = (action: object) => {
      instance.actions.push(action);
      if ((action as { type?: string }).type === "dataZoom") instance.handlers.get("dataZoom")?.(action);
    };
    const adapter = new EChartsRendererAdapter({ init: () => instance } satisfies EChartsRuntimePort);
    const scene = createBenchmarkScene(1);
    const container = document.createElement("div");
    adapter.initialize({
      container,
      renderer: "canvas",
      reducedMotion: true,
      onCursor: vi.fn(),
      onXDomainChange,
    });
    adapter.setScene(scene);

    instance.handlers.get("dataZoom")?.({ start: 25, end: 75 });
    adapter.resetZoom();
    expect(onXDomainChange).toHaveBeenCalledTimes(1);
    expect(onXDomainChange).toHaveBeenLastCalledWith(scene.xDomain);
    await waitForZoomCommit();
    expect(onXDomainChange).toHaveBeenCalledTimes(1);

    instance.handlers.get("dataZoom")?.({ start: 10, end: 90 });
    container.dispatchEvent(new MouseEvent("mousedown", { button: 0, clientX: 80, clientY: 120 }));
    instance.handlers.get("dataZoom")?.({ start: 20, end: 100 });
    window.dispatchEvent(new MouseEvent("mouseup", { button: 0 }));
    await waitForZoomCommit();
    const duration = scene.xDomain.toMs - scene.xDomain.fromMs;
    expect(onXDomainChange).toHaveBeenLastCalledWith({
      fromMs: scene.xDomain.fromMs + duration * 0.2,
      toMs: scene.xDomain.toMs,
    });
    adapter.dispose();
  });

  it("drops a pending wheel commit when an explicit range replaces the window (#1810)", async () => {
    const instance = new FakeEChartsInstance();
    const onXDomainChange = vi.fn();
    const adapter = new EChartsRendererAdapter({ init: () => instance } satisfies EChartsRuntimePort);
    const scene = createBenchmarkScene(1);
    adapter.initialize({
      container: document.createElement("div"),
      renderer: "canvas",
      reducedMotion: true,
      onCursor: vi.fn(),
      onXDomainChange,
    });
    adapter.setScene(scene);
    instance.handlers.get("dataZoom")?.({ start: 25, end: 75 });
    const duration = scene.xDomain.toMs - scene.xDomain.fromMs;
    const longer = { fromMs: scene.xDomain.toMs - duration * 4, toMs: scene.xDomain.toMs };
    adapter.setScene({ ...scene, xDomain: longer, interactionDomain: longer });
    await waitForZoomCommit();
    expect(onXDomainChange).not.toHaveBeenCalled();
    expect(instance.options.at(-1)).toMatchObject({
      dataZoom: [{ startValue: longer.fromMs, endValue: longer.toMs }],
    });
    adapter.dispose();
  });
});

describe("#1843 Y axes fitted to the visible window", () => {
  function setup() {
    const instance = new FakeEChartsInstance();
    const adapter = new EChartsRendererAdapter({ init: () => instance } satisfies EChartsRuntimePort);
    const container = document.createElement("div");
    adapter.initialize({
      container,
      renderer: "canvas",
      reducedMotion: true,
      onCursor: vi.fn(),
      onXDomainChange: vi.fn(),
    });
    return { instance, adapter, container };
  }

  function yAxes(instance: FakeEChartsInstance): Array<{ id: string; min: number; max: number }> {
    return (instance.options.at(-1) as { yAxis: Array<{ id: string; min: number; max: number }> }).yAxis;
  }

  /** Visible-window extent of every visible series, straight from the scene points. */
  function extentIn(scene: ReturnType<typeof createBenchmarkScene>, fromMs: number, toMs: number) {
    const values = scene.series
      .filter((series) => series.visible)
      .flatMap((series) => series.segments.flatMap((segment) => segment.points))
      .filter((point) => point.timestampMs >= fromMs && point.timestampMs <= toMs)
      .map((point) => point.value);
    return { min: Math.min(...values), max: Math.max(...values) };
  }

  it("fits a zoomed window, returns on reset and ignores hidden series", () => {
    const { instance, adapter, container } = setup();
    const scene = createBenchmarkScene(2);
    adapter.setScene(scene);
    const full = yAxes(instance)[0];
    const whole = extentIn(scene, scene.xDomain.fromMs, scene.xDomain.toMs);
    expect(full.min).toBeLessThanOrEqual(whole.min);
    expect(full.max).toBeGreaterThanOrEqual(whole.max);

    // Zoom into 30 s of the 20-minute window: the axis narrows to that part of the data.
    const zoomed = { fromMs: scene.xDomain.fromMs + 100_000, toMs: scene.xDomain.fromMs + 130_000 };
    adapter.setScene({ ...scene, xDomain: zoomed, interactionDomain: scene.xDomain });
    const fitted = yAxes(instance)[0];
    const visible = extentIn(scene, zoomed.fromMs, zoomed.toMs);
    expect(fitted.min).toBeLessThanOrEqual(visible.min);
    expect(fitted.max).toBeGreaterThanOrEqual(visible.max);
    expect(fitted.max - fitted.min).toBeLessThan(full.max - full.min);
    expect(JSON.parse(container.dataset.chartYBounds!)[0]).toMatchObject({
      min: fitted.min,
      max: fitted.max,
    });

    // Reset to the full window: the full-range axis comes back.
    adapter.setScene({ ...scene, interactionDomain: scene.xDomain });
    expect(yAxes(instance)[0].max - yAxes(instance)[0].min).toBe(full.max - full.min);

    // Hiding the higher series refits to the remaining one.
    const hidden = {
      ...scene,
      series: scene.series.map((series, index) => ({ ...series, visible: index === 0 })),
    };
    adapter.setScene(hidden);
    const solo = extentIn(hidden, scene.xDomain.fromMs, scene.xDomain.toMs);
    expect(JSON.parse(container.dataset.chartYBounds!)[0]).toMatchObject({
      dataMin: solo.min,
      dataMax: solo.max,
    });
    expect(solo.max).toBeLessThan(whole.max);
    expect(yAxes(instance)[0].max).toBeGreaterThanOrEqual(solo.max);
    adapter.dispose();
  });

  it("keeps the full-period axis while zooming in 'full' mode", () => {
    const { instance, adapter } = setup();
    const scene = { ...createBenchmarkScene(1), yScale: { mode: "full" as const } };
    adapter.setScene(scene);
    const full = yAxes(instance)[0];
    adapter.setScene({
      ...scene,
      xDomain: { fromMs: scene.xDomain.fromMs + 100_000, toMs: scene.xDomain.fromMs + 200_000 },
      interactionDomain: scene.xDomain,
    });
    expect(yAxes(instance)[0]).toMatchObject({ min: full.min, max: full.max });
    adapter.dispose();
  });

  it("names a distant threshold off-scale instead of squashing the data", () => {
    const { instance, adapter } = setup();
    const base = createBenchmarkScene(1);
    const seriesKey = chartSeriesKey(base.series[0].identity);
    adapter.setScene({
      ...base,
      thresholds: [{ id: "far", seriesKey, kind: "upper", value: 500, label: "Аварійна межа" }],
    });
    const option = instance.options.at(-1) as {
      series: Array<{ markLine?: unknown }>;
      graphic: Array<{ id: string; style: { text: string } }>;
    };
    expect(yAxes(instance)[0].max).toBeLessThan(100);
    expect(option.series[0].markLine).toBeUndefined();
    expect(option.graphic.find((item) => item.id === "y-off-scale-above")?.style.text).toContain(
      "Аварійна межа",
    );
    adapter.dispose();
  });
});

describe("#1866 cursor without flicker", () => {
  function setup() {
    const instance = new FakeEChartsInstance();
    const onCursor = vi.fn();
    const adapter = new EChartsRendererAdapter({ init: () => instance } satisfies EChartsRuntimePort);
    const container = document.createElement("div");
    adapter.initialize({
      container,
      renderer: "canvas",
      reducedMotion: true,
      onCursor,
      onXDomainChange: vi.fn(),
    });
    adapter.setScene(createBenchmarkScene(3));
    return { instance, onCursor, adapter, container };
  }

  it("never re-commits its own shared-cursor dispatch (no echo loop)", async () => {
    const { instance, onCursor, adapter } = setup();
    // The real ECharts emits updateAxisPointer synchronously from dispatchAction.
    instance.dispatchAction = (action: object) => {
      instance.actions.push(action);
      const value = (action as { value?: number }).value;
      if (value !== undefined) instance.handlers.get("updateAxisPointer")?.({ axesInfo: [{ value }] });
    };
    adapter.setSharedCursor(BENCHMARK_START_MS + 50_000);
    await nextAnimationFrame();
    expect(onCursor).not.toHaveBeenCalled();
    // The same shared value again is not re-dispatched.
    adapter.setSharedCursor(BENCHMARK_START_MS + 50_000);
    expect(
      instance.actions.filter((action) => (action as { type: string }).type === "updateAxisPointer"),
    ).toHaveLength(1);
    adapter.dispose();
  });

  it("does not dispatch the shared cursor back into the plot under the mouse", async () => {
    const { instance, adapter, container } = setup();
    container.dispatchEvent(new MouseEvent("mousemove", { clientX: 40, clientY: 50 }));
    adapter.setSharedCursor(BENCHMARK_START_MS + 40);
    expect(instance.actions).toHaveLength(0);
    container.dispatchEvent(new MouseEvent("mouseleave"));
    adapter.setSharedCursor(BENCHMARK_START_MS + 80);
    expect(instance.actions).toHaveLength(1);
    adapter.dispose();
  });

  it("disables series emphasis so hovering one line never dims the others", () => {
    const { instance, adapter, container } = setup();
    const series = (instance.options.at(-1) as { series: Array<{ type: string; emphasis?: object }> }).series;
    for (const line of series.filter((item) => item.type === "line"))
      expect(line.emphasis).toEqual({ disabled: true });
    // Cursor moves never rebuild the chart.
    const renders = container.dataset.chartFullRenders;
    for (let index = 0; index < 50; index += 1)
      container.dispatchEvent(new MouseEvent("mousemove", { clientX: index, clientY: 50 }));
    expect(container.dataset.chartFullRenders).toBe(renders);
    expect(instance.options).toHaveLength(1);
    adapter.dispose();
  });
});
