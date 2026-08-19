import { LineChart } from "echarts/charts";
import {
  AriaComponent,
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components";
import { init, use as registerEChartsModules, type EChartsCoreOption, type EChartsType } from "echarts/core";
import { CanvasRenderer, SVGRenderer } from "echarts/renderers";

import { chartSeriesKey, type ChartEventMarker, type ChartPoint, type ChartSeries } from "./domain";
import type { ChartRendererAdapter, ChartRendererInitOptions, ChartRendererScene } from "./renderer-adapter";
import { formatChartAxisTimestamp } from "./format";
import { inspectChartAtTimestamp } from "./inspection";
import { buildChartYAxisModel } from "./units";

registerEChartsModules([
  LineChart,
  AriaComponent,
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
  CanvasRenderer,
  SVGRenderer,
]);

interface EChartsInstancePort {
  setOption(
    option: EChartsCoreOption,
    settings?: { notMerge?: boolean; lazyUpdate?: boolean; replaceMerge?: string[] },
  ): void;
  on(eventName: string, handler: (event: unknown) => void): void;
  off(eventName: string, handler?: (event: unknown) => void): void;
  dispatchAction(action: object): void;
  containPixel(finder: object, value: [number, number]): boolean;
  convertFromPixel(finder: object, value: [number, number]): number | number[];
  resize(): void;
  dispose(): void;
  isDisposed(): boolean;
}

export interface EChartsRuntimePort {
  init(container: HTMLElement, renderer: "canvas" | "svg"): EChartsInstancePort;
}

const defaultRuntime: EChartsRuntimePort = {
  init(container, renderer) {
    return init(container, undefined, { renderer }) as EChartsType as EChartsInstancePort;
  },
};

interface AxisPointerEvent {
  axesInfo?: Array<{ value?: number | string }>;
}

interface DataZoomEvent {
  start?: number;
  end?: number;
  startValue?: number;
  endValue?: number;
  batch?: DataZoomEvent[];
}

function axisPointerTimestamp(event: unknown): number | null {
  if (!event || typeof event !== "object") return null;
  const value = (event as AxisPointerEvent).axesInfo?.[0]?.value;
  const timestamp = typeof value === "string" ? Number(value) : value;
  return typeof timestamp === "number" && Number.isFinite(timestamp) ? timestamp : null;
}

function canonicalEvents(events: readonly ChartEventMarker[]): ChartEventMarker[] {
  const byId = new Map<string, ChartEventMarker>();
  for (const event of events) {
    if (
      !event.id.trim() ||
      !Number.isFinite(event.timestampMs) ||
      !event.type.trim() ||
      !event.label.trim() ||
      !event.source.entityId.trim() ||
      !event.source.entityType.trim()
    ) {
      continue;
    }
    if (!byId.has(event.id)) byId.set(event.id, event);
  }
  return [...byId.values()].sort(
    (left, right) => left.timestampMs - right.timestampMs || left.id.localeCompare(right.id),
  );
}

function zoomDomain(event: unknown, scene: ChartRendererScene): ChartRendererScene["xDomain"] | null {
  if (!event || typeof event !== "object") return null;
  const payload = (event as DataZoomEvent).batch?.[0] ?? (event as DataZoomEvent);
  if (Number.isFinite(payload.startValue) && Number.isFinite(payload.endValue)) {
    return { fromMs: payload.startValue!, toMs: payload.endValue! };
  }
  if (!Number.isFinite(payload.start) || !Number.isFinite(payload.end)) return null;
  const duration = scene.xDomain.toMs - scene.xDomain.fromMs;
  return {
    fromMs: scene.xDomain.fromMs + duration * (payload.start! / 100),
    toMs: scene.xDomain.fromMs + duration * (payload.end! / 100),
  };
}

function rendererOption(scene: ChartRendererScene, reducedMotion: boolean): EChartsCoreOption {
  const visibleSeries = scene.series.filter((series) => series.visible);
  const axisModel = buildChartYAxisModel(scene.series);
  const legendNames = visibleSeries.map((series) => series.name);
  const events = canonicalEvents(scene.events ?? []);
  const lineSeries = visibleSeries.flatMap((series, visibleSeriesIndex) => {
    const seriesKey = chartSeriesKey(series.identity);
    const thresholds = scene.thresholds?.filter((threshold) => threshold.seriesKey === seriesKey) ?? [];
    return series.segments.map((segment, segmentIndex) => ({
      id: `${seriesKey}:${segment.id}`,
      name: series.name,
      type: "line" as const,
      yAxisId: axisModel.axisIdBySeriesKey.get(seriesKey),
      data: segment.points.map((point) => ({
        value: [point.timestampMs, point.value],
        pointId: point.id,
        quality: point.quality,
        sourceEventId: point.sourceEventId,
        symbolSize: point.pinReasons?.length ? 9 : segment.points.length <= 24 ? 6 : 0,
        ...(point.pinReasons?.length
          ? {
              itemStyle: {
                color: point.pinReasons.includes("alarm") ? "#FF4D4F" : "#F5B301",
                borderColor: "#E6ECF2",
                borderWidth: 1,
              },
            }
          : {}),
      })),
      showSymbol: true,
      symbol: series.markerShape,
      symbolSize: 6,
      smooth: false,
      connectNulls: false,
      animation: !reducedMotion,
      lineStyle: {
        color: series.colorToken,
        width: 2.25,
        type: series.dashStyle,
      },
      ...(series.areaFillOpacity !== undefined && series.areaFillOpacity > 0
        ? {
            areaStyle: {
              color: series.colorToken,
              opacity: Math.min(1, series.areaFillOpacity),
            },
          }
        : {}),
      itemStyle: { color: series.colorToken },
      emphasis: { focus: "series" as const, lineStyle: { width: 3 } },
      ...(segmentIndex === 0 && (thresholds.length > 0 || (visibleSeriesIndex === 0 && events.length > 0))
        ? {
            markLine: {
              silent: true,
              symbol: "none",
              label: { color: "#F5B301", formatter: "{b}" },
              lineStyle: { color: "#F5B301", type: "dashed", width: 1.25 },
              data: [
                ...thresholds.map((threshold) => ({
                  name: threshold.label,
                  yAxis: threshold.value,
                })),
                ...(visibleSeriesIndex === 0
                  ? events.map((event) => ({
                      name: event.label,
                      xAxis: event.timestampMs,
                      eventId: event.id,
                      eventSourceId: event.source.entityId,
                      label: { show: false },
                      lineStyle: {
                        color:
                          event.severity === "alarm"
                            ? "#FF4D4F"
                            : event.severity === "warning"
                              ? "#F5B301"
                              : "#00C6E0",
                        type: "dotted" as const,
                      },
                    }))
                  : []),
              ],
            },
          }
        : {}),
      ...(visibleSeriesIndex === 0 && segmentIndex === 0 && scene.alarmRegions?.length
        ? {
            markArea: {
              silent: true,
              data: scene.alarmRegions.map((region) => [
                {
                  name: region.label,
                  xAxis: region.fromMs,
                  itemStyle: {
                    color:
                      region.severity === "alarm"
                        ? "rgba(255,77,79,.12)"
                        : region.severity === "offline"
                          ? "rgba(148,163,184,.12)"
                          : "rgba(245,179,1,.10)",
                  },
                  label: { color: "#E6ECF2" },
                },
                { xAxis: region.toMs },
              ]),
            },
          }
        : {}),
    }));
  });

  return {
    animation: !reducedMotion,
    backgroundColor: "transparent",
    aria: {
      enabled: true,
      decal: { show: true },
      label: { description: `Telemetry chart with ${scene.series.length} series.` },
    },
    grid: {
      left:
        64 +
        Math.max(
          0,
          ...axisModel.visibleAxes.filter((axis) => axis.position === "left").map((axis) => axis.offset),
        ),
      right:
        40 +
        Math.max(
          0,
          ...axisModel.visibleAxes.filter((axis) => axis.position === "right").map((axis) => axis.offset),
        ),
      top: 28,
      bottom: 58,
      containLabel: false,
    },
    legend: { show: false, data: legendNames },
    tooltip: {
      trigger: "axis",
      showContent: false,
      axisPointer: { type: "line", snap: false },
      appendToBody: false,
      confine: true,
      transitionDuration: 0,
    },
    xAxis: {
      type: "time",
      min: scene.xDomain.fromMs,
      max: scene.xDomain.toMs,
      axisLine: { lineStyle: { color: "rgba(148,163,184,.34)" } },
      axisLabel: {
        color: "#94A3B8",
        hideOverlap: true,
        formatter: (value: number | string) => formatChartAxisTimestamp(Number(value), scene.xDomain),
      },
      splitLine: { show: true, lineStyle: { color: "rgba(148,163,184,.10)" } },
    },
    yAxis:
      axisModel.visibleAxes.length > 0
        ? axisModel.visibleAxes.map((axis, visibleIndex) => ({
            id: axis.id,
            type: "value" as const,
            scale: true,
            position: axis.position,
            offset: axis.offset,
            name: axis.nativeUnit,
            nameLocation: "middle" as const,
            nameGap: 38,
            nameTextStyle: { color: "#CBD5E1", fontWeight: 600 },
            axisLine: { show: true, lineStyle: { color: "rgba(148,163,184,.42)" } },
            axisTick: { show: true },
            axisLabel: { color: "#94A3B8", hideOverlap: true },
            splitLine: {
              show: visibleIndex === 0,
              lineStyle: { color: "rgba(148,163,184,.10)" },
            },
          }))
        : [
            {
              id: "__nexolab-empty-axis__",
              type: "value" as const,
              show: false,
              min: 0,
              max: 1,
            },
          ],
    dataZoom: [
      {
        type: "inside",
        xAxisIndex: 0,
        filterMode: "none",
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
      },
    ],
    series: lineSeries,
  };
}

export class EChartsRendererAdapter implements ChartRendererAdapter {
  private instance: EChartsInstancePort | null = null;
  private container: HTMLElement | null = null;
  private scene: ChartRendererScene | null = null;
  private options: ChartRendererInitOptions | null = null;
  private maximumLivePoints = 240;

  constructor(private readonly runtime: EChartsRuntimePort = defaultRuntime) {}

  private readonly handleContainerPointer = (event: MouseEvent) => {
    if (!this.scene || !this.instance || !this.container) return;
    const bounds = this.container.getBoundingClientRect();
    const pixel: [number, number] = [event.clientX - bounds.left, event.clientY - bounds.top];
    if (!this.instance.containPixel({ gridIndex: 0 }, pixel)) {
      this.options?.onCursor(null);
      return;
    }
    const converted = this.instance.convertFromPixel({ xAxisIndex: 0 }, pixel);
    const timestampMs = Array.isArray(converted) ? Number(converted[0]) : Number(converted);
    if (!Number.isFinite(timestampMs)) return;
    this.options?.onCursor(inspectChartAtTimestamp(this.scene, timestampMs));
  };

  private readonly handleContainerLeave = () => {
    this.options?.onCursor(null);
  };

  private readonly handleAxisPointer = (event: unknown) => {
    if (!this.scene) return;
    const timestampMs = axisPointerTimestamp(event);
    if (timestampMs === null) return;
    this.options?.onCursor(inspectChartAtTimestamp(this.scene, timestampMs));
  };

  private readonly handleDataZoom = (event: unknown) => {
    if (!this.scene) return;
    const domain = zoomDomain(event, this.scene);
    if (domain) this.options?.onXDomainChange(domain);
  };

  initialize(options: ChartRendererInitOptions): void {
    if (this.instance && !this.instance.isDisposed()) return;
    this.options = options;
    this.maximumLivePoints = options.maximumLivePoints ?? 240;
    this.container = options.container;
    this.instance = this.runtime.init(options.container, options.renderer);
    this.instance.on("updateAxisPointer", this.handleAxisPointer);
    this.instance.on("dataZoom", this.handleDataZoom);
    this.container.addEventListener("mousemove", this.handleContainerPointer);
    this.container.addEventListener("mouseleave", this.handleContainerLeave);
  }

  setScene(scene: ChartRendererScene): void {
    if (!this.instance) throw new Error("Chart renderer must be initialized before setting a scene");
    this.scene = scene;
    this.instance.setOption(rendererOption(scene, this.options?.reducedMotion ?? false), {
      notMerge: false,
      lazyUpdate: false,
      replaceMerge: ["series", "yAxis"],
    });
  }

  appendLiveTail(seriesKey: string, additions: readonly { segmentId: string; point: ChartPoint }[]): void {
    if (!this.scene || additions.length === 0) return;
    const series = this.scene.series.map((item) => {
      if (chartSeriesKey(item.identity) !== seriesKey) return item;
      const segments = item.segments.map((segment) => {
        const incoming = additions.filter((addition) => addition.segmentId === segment.id);
        if (incoming.length === 0) return segment;
        const byId = new Map(segment.points.map((point) => [point.id, point]));
        for (const addition of incoming) byId.set(addition.point.id, addition.point);
        const points = [...byId.values()]
          .sort((left, right) => left.timestampMs - right.timestampMs || left.id.localeCompare(right.id))
          .slice(-this.maximumLivePoints);
        return { ...segment, points };
      });
      const knownSegmentIds = new Set(segments.map((segment) => segment.id));
      const newSegments = additions
        .filter((addition) => !knownSegmentIds.has(addition.segmentId))
        .reduce<ChartSeries["segments"][number][]>((created, addition) => {
          const existing = created.find((segment) => segment.id === addition.segmentId);
          if (existing) {
            return created.map((segment) =>
              segment.id === addition.segmentId
                ? {
                    ...segment,
                    points: [...segment.points, addition.point]
                      .sort(
                        (left, right) =>
                          left.timestampMs - right.timestampMs || left.id.localeCompare(right.id),
                      )
                      .slice(-this.maximumLivePoints),
                  }
                : segment,
            );
          }
          return [...created, { id: addition.segmentId, seriesKey, points: [addition.point] }];
        }, []);
      return { ...item, segments: [...segments, ...newSegments] };
    });
    this.setScene({ ...this.scene, series });
  }

  setSharedCursor(timestampMs: number | null): void {
    if (!this.instance) return;
    if (timestampMs === null) {
      this.instance.dispatchAction({ type: "hideTip" });
      return;
    }
    this.instance.dispatchAction({
      type: "updateAxisPointer",
      xAxisIndex: 0,
      value: timestampMs,
    });
  }

  setSharedXDomain(domain: ChartRendererScene["xDomain"]): void {
    if (!this.scene) return;
    this.setScene({ ...this.scene, xDomain: domain });
  }

  resize(): void {
    this.instance?.resize();
  }

  resetZoom(): void {
    this.instance?.dispatchAction({ type: "dataZoom", start: 0, end: 100 });
  }

  dispose(): void {
    if (!this.instance) return;
    this.instance.off("updateAxisPointer", this.handleAxisPointer);
    this.instance.off("dataZoom", this.handleDataZoom);
    this.container?.removeEventListener("mousemove", this.handleContainerPointer);
    this.container?.removeEventListener("mouseleave", this.handleContainerLeave);
    this.instance.dispose();
    this.instance = null;
    this.container = null;
    this.scene = null;
    this.options = null;
  }

  isDisposed(): boolean {
    return this.instance === null || this.instance.isDisposed();
  }
}
