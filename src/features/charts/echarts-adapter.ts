import { LineChart, ScatterChart } from "echarts/charts";
import {
  AriaComponent,
  AxisPointerComponent,
  DataZoomComponent,
  GraphicComponent,
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
import { chartPointBudget } from "./point-budget";
import { buildChartYAxisModel, displayUnit, type ChartYAxisModel } from "./units";
import { recordChartRenderCost } from "./viewport-budget";
import { chartYScaleKey, computeChartYAxisBounds, type ChartYAxisBounds } from "./y-axis-bounds";

registerEChartsModules([
  LineChart,
  // #1810: pinned evidence and isolated single measurements are drawn as a marker scatter.
  ScatterChart,
  AriaComponent,
  AxisPointerComponent,
  DataZoomComponent,
  GraphicComponent,
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
  convertFromPixel(finder: object, value: number | number[]): number | number[] | null | undefined;
  resize(): void;
  /** Optional: only the real ECharts instance provides it; test doubles may omit it. */
  getDataURL?(options: { type: "png"; pixelRatio: number; backgroundColor: string }): string;
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

export const CHART_GRID_INSETS = { left: 64, right: 40 } as const;
/** Series with at most this many points draw a symbol on every measured point. */
const SYMBOL_POINT_LIMIT = 24;
/**
 * #1810: wheel zoom and keyboard/inside zoom render natively in ECharts at once; the React
 * viewport (statistics, shared domain, other charts) follows once the gesture pauses instead of
 * rebuilding every chart on every wheel tick.
 */
export const ZOOM_COMMIT_IDLE_MS = 120;

const signatureFloat = new Float64Array(1);
const signatureWords = new Uint32Array(signatureFloat.buffer);

/**
 * Exact fingerprint of everything a scene renders EXCEPT the visible x window. When only the
 * window changes (zoom, pan, shared domain), the adapter moves the view without rebuilding and
 * re-uploading every series.
 */
export function sceneDataSignature(scene: ChartRendererScene): string {
  let hash = 0x811c9dc5;
  const mix = (word: number) => {
    hash = Math.imul(hash ^ word, 0x01000193);
  };
  const mixNumber = (value: number) => {
    signatureFloat[0] = value;
    mix(signatureWords[0]);
    mix(signatureWords[1]);
  };
  let points = 0;
  for (const series of scene.series) {
    for (const segment of series.segments) {
      mix(segment.points.length);
      for (const point of segment.points) {
        mixNumber(point.timestampMs);
        mixNumber(point.value);
        mix(point.pinReasons?.length ?? 0);
        for (const reason of point.pinReasons ?? []) {
          for (let index = 0; index < reason.length; index += 1) mix(reason.charCodeAt(index));
          mix(0);
        }
        points += 1;
      }
    }
  }
  // Everything except the visible window and the (separately hashed) series points.
  const rest: Record<string, unknown> = { ...scene };
  delete rest.xDomain;
  delete rest.interactionDomain;
  delete rest.series;
  const series = scene.series;
  const metadata = JSON.stringify({
    rest,
    series: series.map(({ segments, ...meta }) => ({
      ...meta,
      segments: segments.map((segment) => [
        segment.id,
        segment.points.length,
        segment.precedingBreak?.reason,
      ]),
    })),
  });
  return `${points}:${hash >>> 0}:${metadata}`;
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

/**
 * True when the full interaction window was replaced (new range preset or custom range), not merely
 * slid forward by a live-follow tick: its duration changed or it moved by more than 10 %.
 */
function windowReplaced(previous: ChartRendererScene, next: ChartRendererScene): boolean {
  const before = previous.interactionDomain ?? previous.xDomain;
  const after = next.interactionDomain ?? next.xDomain;
  const duration = before.toMs - before.fromMs;
  if (Math.abs(after.toMs - after.fromMs - duration) > 1) return true;
  return Math.abs(after.fromMs - before.fromMs) > duration * 0.1;
}

function intervalDecimals(interval: number): number {
  const text = String(Number(interval.toPrecision(6)));
  const dot = text.indexOf(".");
  return dot < 0 ? 0 : Math.min(text.length - dot - 1, 12);
}

function offScaleText(bounds: readonly ChartYAxisBounds[], direction: "above" | "below"): string {
  const arrow = direction === "above" ? "▲" : "▼";
  const where = direction === "above" ? "вище шкали" : "нижче шкали";
  return bounds
    .flatMap((axis) => axis.offScaleThresholds.filter((threshold) => threshold.direction === direction))
    .map((threshold) => `${arrow} ${threshold.label}: ${threshold.value} (${where})`)
    .join("   ");
}

/**
 * #1843: explicit Y bounds per visible axis (fitted to the visible window by default) and the
 * off-scale threshold notices. Merged by axis id, so the fast zoom/pan path updates only these.
 */
function yWindowOption(axisModel: ChartYAxisModel, bounds: ReadonlyMap<string, ChartYAxisBounds>) {
  const all = [...bounds.values()];
  return {
    yAxis: axisModel.visibleAxes.map((axis) => {
      const axisBounds = bounds.get(axis.id);
      if (!axisBounds) return { id: axis.id, min: null, max: null, interval: null };
      const decimals = intervalDecimals(axisBounds.interval);
      return {
        id: axis.id,
        min: axisBounds.min,
        max: axisBounds.max,
        interval: axisBounds.interval,
        axisLabel: {
          color: "#94A3B8",
          hideOverlap: true,
          formatter: (value: number) => Number(value).toFixed(decimals),
        },
      };
    }),
    graphic: [
      {
        id: "y-off-scale-above",
        type: "text",
        left: CHART_GRID_INSETS.left + 4,
        top: 6,
        silent: true,
        style: { text: offScaleText(all, "above"), fill: "#F5B301", fontSize: 11 },
      },
      {
        id: "y-off-scale-below",
        type: "text",
        left: CHART_GRID_INSETS.left + 4,
        bottom: 36,
        silent: true,
        style: { text: offScaleText(all, "below"), fill: "#F5B301", fontSize: 11 },
      },
    ],
  };
}

/** The parts of the option that depend on the visible window only (#1810 fast path). */
function xWindowOption(scene: ChartRendererScene) {
  const interactionDomain = scene.interactionDomain ?? scene.xDomain;
  return {
    xAxis: {
      min: interactionDomain.fromMs,
      max: interactionDomain.toMs,
      axisLabel: {
        color: "#94A3B8",
        hideOverlap: true,
        formatter: (value: number | string) =>
          formatChartAxisTimestamp(Number(value), scene.xDomain, { timeZone: scene.displayTimeZone }),
      },
    },
    dataZoom: [
      { rangeMode: ["value", "value"], startValue: scene.xDomain.fromMs, endValue: scene.xDomain.toMs },
    ],
  };
}

function rendererOption(
  scene: ChartRendererScene,
  axisModel: ChartYAxisModel,
  yBounds: ReadonlyMap<string, ChartYAxisBounds>,
): EChartsCoreOption {
  const visibleSeries = scene.series.filter((series) => series.visible);
  const offScaleIds = new Set(
    [...yBounds.values()].flatMap((axis) => axis.offScaleThresholds.map((threshold) => threshold.id)),
  );
  const legendNames = visibleSeries.map((series) => series.name);
  const events = canonicalEvents(scene.events ?? []);
  const lineSeries = visibleSeries.flatMap((series, visibleSeriesIndex) => {
    const seriesKey = chartSeriesKey(series.identity);
    // Off-scale thresholds are named in the plot corner instead of drawn outside the grid (#1843).
    const thresholds =
      scene.thresholds?.filter(
        (threshold) => threshold.seriesKey === seriesKey && !offScaleIds.has(threshold.id),
      ) ?? [];
    // #1810: ONE line series per channel. Continuity breaks are explicit null points between
    // segments (connectNulls: false), so a gap still breaks the line, but the renderer no longer
    // creates one ECharts series per segment (hundreds per channel when a history has many
    // gaps). Plain [time, value] tuples keep ECharts on its fast data path.
    const lineData: Array<[number, number | null]> = [];
    const markerData: Array<{ value: [number, number]; symbolSize: number; itemStyle?: object }> = [];
    const totalPoints = series.segments.reduce((sum, segment) => sum + segment.points.length, 0);
    series.segments.forEach((segment, segmentIndex) => {
      const first = segment.points[0];
      const previousLast = lineData.at(-1);
      if (segmentIndex > 0 && first && previousLast) {
        lineData.push([(previousLast[0] + first.timestampMs) / 2, null]);
      }
      for (const point of segment.points) {
        lineData.push([point.timestampMs, point.value]);
        if (point.pinReasons?.length) {
          markerData.push({
            value: [point.timestampMs, point.value],
            symbolSize: 9,
            itemStyle: {
              color: point.pinReasons.includes("alarm") ? "#FF4D4F" : "#F5B301",
              borderColor: "#E6ECF2",
              borderWidth: 1,
            },
          });
        } else if (segment.points.length === 1 && totalPoints > SYMBOL_POINT_LIMIT) {
          // An isolated measurement between two breaks has no line; keep it visible.
          markerData.push({ value: [point.timestampMs, point.value], symbolSize: 6 });
        }
      }
    });
    const line = {
      id: seriesKey,
      name: series.name,
      type: "line" as const,
      yAxisId: axisModel.axisIdBySeriesKey.get(seriesKey),
      data: lineData,
      showSymbol: totalPoints <= SYMBOL_POINT_LIMIT,
      symbol: series.markerShape,
      symbolSize: 6,
      smooth: false,
      connectNulls: false,
      animation: false,
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
      // #1866: hovering a line must not dim or highlight other channels (the "focus: series" blur
      // flashed every other line on each pointer move across overlapping series).
      emphasis: { disabled: true },
      ...(thresholds.length > 0 || (visibleSeriesIndex === 0 && events.length > 0)
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
      ...(visibleSeriesIndex === 0 && (scene.rangeSelection || scene.alarmRegions?.length)
        ? {
            markArea: {
              silent: true,
              data: [
                ...(scene.rangeSelection
                  ? [
                      [
                        {
                          name: "Selected analysis interval",
                          xAxis: scene.rangeSelection.fromMs,
                          itemStyle: {
                            color: "rgba(0,198,224,.14)",
                            borderColor: "rgba(103,232,249,.85)",
                            borderWidth: 1,
                          },
                          label: { show: false },
                        },
                        { xAxis: scene.rangeSelection.toMs },
                      ],
                    ]
                  : []),
                ...(scene.alarmRegions ?? []).map((region) => [
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
              ],
            },
          }
        : {}),
    };
    if (markerData.length === 0) return [line];
    return [
      line,
      {
        id: `${seriesKey}:markers`,
        name: series.name,
        type: "scatter" as const,
        yAxisId: line.yAxisId,
        data: markerData,
        symbol: series.markerShape,
        itemStyle: { color: series.colorToken },
        silent: true,
        animation: false,
        z: 3,
      },
    ];
  });

  const yWindow = yWindowOption(axisModel, yBounds);
  const yWindowById = new Map(yWindow.yAxis.map((axis) => [axis.id, axis] as const));
  return {
    // #1810: telemetry updates and zoom/pan must not tween. Animated transitions on every
    // setOption were the visible flicker and lag of zoom, pan and live updates.
    animation: false,
    backgroundColor: "transparent",
    aria: {
      enabled: true,
      decal: { show: true },
      label: { description: `Telemetry chart with ${scene.series.length} series.` },
    },
    grid: {
      left:
        CHART_GRID_INSETS.left +
        Math.max(
          0,
          ...axisModel.visibleAxes.filter((axis) => axis.position === "left").map((axis) => axis.offset),
        ),
      right:
        CHART_GRID_INSETS.right +
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
      ...xWindowOption(scene).xAxis,
      axisLine: { lineStyle: { color: "rgba(148,163,184,.34)" } },
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
            name: displayUnit(axis.nativeUnit),
            nameLocation: "middle" as const,
            nameGap: 38,
            nameTextStyle: { color: "#CBD5E1", fontWeight: 600 },
            axisLine: { show: true, lineStyle: { color: "rgba(148,163,184,.42)" } },
            axisTick: { show: true },
            axisLabel: { color: "#94A3B8", hideOverlap: true },
            ...yWindowById.get(axis.id),
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
        rangeMode: ["value", "value"],
        startValue: scene.xDomain.fromMs,
        endValue: scene.xDomain.toMs,
        zoomOnMouseWheel: true,
        moveOnMouseMove: !scene.rangeSelectionEnabled,
        moveOnMouseWheel: false,
        preventDefaultMouseMove: true,
      },
    ],
    graphic: yWindow.graphic,
    series: lineSeries,
  };
}

/** Extents ECharts actually applied to each Y axis (real instance only; test doubles lack it). */
function renderedYExtents(instance: EChartsInstancePort): Array<[number, number]> | null {
  const model = (instance as unknown as { getModel?: () => unknown }).getModel?.() as
    | {
        getComponent(
          type: string,
          index: number,
        ): { axis?: { scale?: { getExtent(): number[] } } } | undefined;
      }
    | undefined;
  if (!model) return null;
  const extents: Array<[number, number]> = [];
  for (let index = 0; ; index += 1) {
    const component = model.getComponent("yAxis", index);
    if (!component) break;
    const extent = component.axis?.scale?.getExtent();
    if (extent) extents.push([extent[0], extent[1]]);
  }
  return extents;
}

export class EChartsRendererAdapter implements ChartRendererAdapter {
  private instance: EChartsInstancePort | null = null;
  private container: HTMLElement | null = null;
  private scene: ChartRendererScene | null = null;
  private options: ChartRendererInitOptions | null = null;
  private maximumLivePoints = chartPointBudget("renderer-live-tail");
  private primaryDragActive = false;
  private primaryDragBaseDomain: ChartRendererScene["xDomain"] | null = null;
  private pendingPrimaryDragDomain: ChartRendererScene["xDomain"] | null = null;
  private rangeSelectionDragActive = false;
  private rangeSelectionStartMs: number | null = null;
  private rangeSelectionLastMs: number | null = null;
  private rangeSelectionStartClientX: number | null = null;
  private rangeSelectionLastClientX: number | null = null;
  private cursorAnimationFrame: number | null = null;
  private pendingCursorTimestampMs: number | null | undefined;
  private lastCommittedCursorTimestampMs: number | null | undefined;
  /** #1866: the pointer is over this plot, so its own mouse position is the only cursor source. */
  private pointerInside = false;
  /** #1866: set while this adapter dispatches a shared cursor, so its own echo is ignored. */
  private dispatchingCursor = false;
  private lastSharedCursorMs: number | null | undefined;
  private cursorCommits = 0;
  private fullRenders = 0;
  private renderedSignature: string | null = null;
  private zoomCommitTimer: ReturnType<typeof setTimeout> | null = null;
  private pendingZoomDomain: ChartRendererScene["xDomain"] | null = null;
  private programmaticZoom = false;
  private yBounds = new Map<string, ChartYAxisBounds>();
  private yBoundsContext: string | null = null;
  private renderedOffScaleKey = "";

  /**
   * #1843: Y bounds for the rendered window. The previous bounds are kept while the data still
   * fills them (no jitter from live samples or small pans); a new period, another Y mode or a
   * hidden/shown series starts afresh.
   */
  private computeYBounds(rendered: ChartRendererScene, axisModel: ChartYAxisModel) {
    const fullDomain = rendered.interactionDomain ?? rendered.xDomain;
    const context = [
      chartYScaleKey(rendered.yScale),
      fullDomain.toMs - fullDomain.fromMs,
      rendered.series
        .map((series) => `${chartSeriesKey(series.identity)}:${series.visible ? 1 : 0}`)
        .join(","),
    ].join("|");
    const previous = context === this.yBoundsContext ? this.yBounds : undefined;
    this.yBounds = computeChartYAxisBounds({
      series: rendered.series,
      axisModel,
      visibleDomain: rendered.xDomain,
      fullDomain,
      scale: rendered.yScale,
      thresholds: rendered.thresholds,
      previous,
    });
    this.yBoundsContext = context;
    return this.yBounds;
  }

  private publishYBounds(): void {
    if (!this.container || !this.instance) return;
    this.container.dataset.chartYBounds = JSON.stringify(
      [...this.yBounds.values()].map((axis) => ({
        axisId: axis.axisId,
        min: axis.min,
        max: axis.max,
        dataMin: axis.dataMin,
        dataMax: axis.dataMax,
        offScale: axis.offScaleThresholds.map((threshold) => threshold.id),
      })),
    );
    const extents = renderedYExtents(this.instance);
    if (extents) this.container.dataset.chartYRendered = JSON.stringify(extents);
  }

  private cancelPendingZoomCommit(): void {
    if (this.zoomCommitTimer !== null) clearTimeout(this.zoomCommitTimer);
    this.zoomCommitTimer = null;
    this.pendingZoomDomain = null;
  }

  constructor(private readonly runtime: EChartsRuntimePort = defaultRuntime) {}

  private timestampAtPointer(event: MouseEvent): number | null {
    if (!this.instance || !this.container || !this.scene) return null;
    const bounds = this.container.getBoundingClientRect();
    const pixel: [number, number] = [event.clientX - bounds.left, event.clientY - bounds.top];
    if (!this.instance.containPixel({ gridIndex: 0 }, pixel)) return null;
    const converted = this.instance.convertFromPixel({ xAxisIndex: 0 }, pixel);
    const timestampMs = Array.isArray(converted) ? Number(converted[0]) : Number(converted);
    if (!Number.isFinite(timestampMs)) return null;
    const domain = this.scene.interactionDomain ?? this.scene.xDomain;
    return Math.max(domain.fromMs, Math.min(timestampMs, domain.toMs));
  }

  private cancelPendingCursor(): void {
    const view = this.container?.ownerDocument.defaultView;
    if (this.cursorAnimationFrame !== null && view) view.cancelAnimationFrame(this.cursorAnimationFrame);
    this.cursorAnimationFrame = null;
    this.pendingCursorTimestampMs = undefined;
  }

  private commitCursor(timestampMs: number | null): void {
    if (timestampMs === this.lastCommittedCursorTimestampMs) return;
    this.lastCommittedCursorTimestampMs = timestampMs;
    this.cursorCommits += 1;
    if (this.container) this.container.dataset.chartCursorCommits = String(this.cursorCommits);
    if (timestampMs === null || !this.scene) {
      this.options?.onCursor(null);
      return;
    }
    this.options?.onCursor(inspectChartAtTimestamp(this.scene, timestampMs));
  }

  private queueCursor(timestampMs: number | null): void {
    this.pendingCursorTimestampMs = timestampMs;
    if (this.cursorAnimationFrame !== null) return;
    const view = this.container?.ownerDocument.defaultView;
    if (!view) {
      const pending = this.pendingCursorTimestampMs;
      this.pendingCursorTimestampMs = undefined;
      if (pending !== undefined) this.commitCursor(pending);
      return;
    }
    this.cursorAnimationFrame = view.requestAnimationFrame(() => {
      this.cursorAnimationFrame = null;
      const pending = this.pendingCursorTimestampMs;
      this.pendingCursorTimestampMs = undefined;
      if (pending !== undefined) this.commitCursor(pending);
    });
  }

  private timestampAtRangePointer(event: MouseEvent): number | null {
    if (!this.instance || !this.container || !this.scene) return null;
    const bounds = this.container.getBoundingClientRect();
    if (bounds.width <= 0 || bounds.height <= 0) return null;
    const localX = Math.max(0, Math.min(event.clientX - bounds.left, bounds.width));
    const converted = this.instance.convertFromPixel({ xAxisIndex: 0 }, localX);
    const timestampMs = Array.isArray(converted) ? Number(converted[0]) : Number(converted);
    if (!Number.isFinite(timestampMs)) return null;
    const domain = this.scene.interactionDomain ?? this.scene.xDomain;
    return Math.max(domain.fromMs, Math.min(timestampMs, domain.toMs));
  }

  private finishRangeSelection(cancelled = false): void {
    const startMs = this.rangeSelectionStartMs;
    const endMs = this.rangeSelectionLastMs;
    const startClientX = this.rangeSelectionStartClientX;
    const endClientX = this.rangeSelectionLastClientX;
    this.rangeSelectionDragActive = false;
    this.rangeSelectionStartMs = null;
    this.rangeSelectionLastMs = null;
    this.rangeSelectionStartClientX = null;
    this.rangeSelectionLastClientX = null;
    if (
      cancelled ||
      startMs === null ||
      endMs === null ||
      startClientX === null ||
      endClientX === null ||
      Math.abs(endClientX - startClientX) < 4
    ) {
      if (this.container) this.container.dataset.rangeSelectionInput = "rejected";
      return;
    }
    const fromMs = Math.min(startMs, endMs);
    const toMs = Math.max(startMs, endMs);
    if (toMs > fromMs) {
      if (this.container) {
        this.container.dataset.rangeSelectionInput = "committed";
        this.container.dataset.rangeSelectionFromMs = String(fromMs);
        this.container.dataset.rangeSelectionToMs = String(toMs);
      }
      this.options?.onRangeSelectionChange?.({ fromMs, toMs });
    } else if (this.container) {
      this.container.dataset.rangeSelectionInput = "rejected";
    }
  }

  private readonly handleWindowPointerDown = (event: PointerEvent) => {
    if (event.button !== 0 || !this.instance || !this.container || !this.scene?.rangeSelectionEnabled) return;
    const target = event.target;
    if (!(target instanceof Node) || !this.container.contains(target)) return;
    const timestampMs = this.timestampAtRangePointer(event);
    if (timestampMs === null) {
      this.container.dataset.rangeSelectionInput = "pointerdown-unmapped";
      return;
    }
    this.container.dataset.rangeSelectionInput = "pointerdown";
    this.container.dataset.rangeSelectionStartMs = String(timestampMs);
    this.rangeSelectionDragActive = true;
    this.rangeSelectionStartMs = timestampMs;
    this.rangeSelectionLastMs = timestampMs;
    this.rangeSelectionStartClientX = event.clientX;
    this.rangeSelectionLastClientX = event.clientX;
    this.cancelPendingCursor();
    this.commitCursor(null);
    event.preventDefault();
    event.stopImmediatePropagation();
  };

  private readonly handleWindowRangePointerMove = (event: PointerEvent) => {
    if (!this.rangeSelectionDragActive) return;
    const timestampMs = this.timestampAtRangePointer(event);
    if (timestampMs !== null) {
      this.rangeSelectionLastMs = timestampMs;
      this.rangeSelectionLastClientX = event.clientX;
      if (this.container) {
        this.container.dataset.rangeSelectionInput = "dragging";
        this.container.dataset.rangeSelectionLastMs = String(timestampMs);
      }
    }
    event.preventDefault();
    event.stopImmediatePropagation();
  };

  private readonly handleWindowPointerUp = (event: PointerEvent) => {
    if (event.button !== 0 || !this.rangeSelectionDragActive) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    this.finishRangeSelection();
  };

  private readonly handleWindowPointerCancel = () => {
    if (this.rangeSelectionDragActive) this.finishRangeSelection(true);
  };

  private readonly handleContainerMouseDown = (event: MouseEvent) => {
    if (event.button !== 0 || !this.instance || !this.container || !this.scene) return;
    if (this.scene.rangeSelectionEnabled) {
      const timestampMs = this.timestampAtRangePointer(event);
      if (timestampMs === null) return;
      this.rangeSelectionDragActive = true;
      this.rangeSelectionStartMs = timestampMs;
      this.rangeSelectionLastMs = timestampMs;
      this.rangeSelectionStartClientX = event.clientX;
      this.rangeSelectionLastClientX = event.clientX;
      this.cancelPendingCursor();
      this.commitCursor(null);
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }
    const bounds = this.container.getBoundingClientRect();
    const pixel: [number, number] = [event.clientX - bounds.left, event.clientY - bounds.top];
    if (!this.instance.containPixel({ gridIndex: 0 }, pixel)) return;
    this.cancelPendingCursor();
    this.primaryDragActive = true;
    this.primaryDragBaseDomain = { ...(this.scene.interactionDomain ?? this.scene.xDomain) };
    this.pendingPrimaryDragDomain = null;
  };

  private finishPrimaryDrag(): void {
    const pendingDomain = this.pendingPrimaryDragDomain;
    this.primaryDragActive = false;
    this.primaryDragBaseDomain = null;
    this.pendingPrimaryDragDomain = null;
    if (pendingDomain) this.options?.onXDomainChange(pendingDomain);
  }

  private readonly handleWindowMouseUp = (event: MouseEvent) => {
    if (event.button !== 0) return;
    if (this.rangeSelectionDragActive) {
      this.finishRangeSelection();
      return;
    }
    this.finishPrimaryDrag();
  };

  private readonly handleContainerPointer = (event: MouseEvent) => {
    if (!this.scene || !this.instance || !this.container) return;
    if (this.rangeSelectionDragActive) {
      if ((event.buttons & 1) === 0) {
        this.finishRangeSelection();
        return;
      }
      const timestampMs = this.timestampAtRangePointer(event);
      if (timestampMs !== null) {
        this.rangeSelectionLastMs = timestampMs;
        this.rangeSelectionLastClientX = event.clientX;
      }
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }
    if (this.primaryDragActive && (event.buttons & 1) === 0) this.finishPrimaryDrag();
    if (this.primaryDragActive || (event.buttons & 1) === 1) return;
    const bounds = this.container.getBoundingClientRect();
    const pixel: [number, number] = [event.clientX - bounds.left, event.clientY - bounds.top];
    if (!this.instance.containPixel({ gridIndex: 0 }, pixel)) {
      this.pointerInside = false;
      this.queueCursor(null);
      return;
    }
    this.pointerInside = true;
    const converted = this.instance.convertFromPixel({ xAxisIndex: 0 }, pixel);
    const timestampMs = Array.isArray(converted) ? Number(converted[0]) : Number(converted);
    if (!Number.isFinite(timestampMs)) return;
    this.queueCursor(timestampMs);
  };

  private readonly handleContainerLeave = () => {
    this.pointerInside = false;
    if (this.primaryDragActive || this.rangeSelectionDragActive) return;
    this.cancelPendingCursor();
    this.commitCursor(null);
  };

  private readonly handleAxisPointer = (event: unknown) => {
    if (!this.scene || this.primaryDragActive || this.rangeSelectionDragActive) return;
    // #1866: two cursor sources (the mouse position and ECharts' own axis-pointer event, plus the
    // echo of a shared cursor this adapter dispatched) alternated between neighbouring timestamps
    // and made the inspected values flicker. Under the mouse only the mouse counts; echoes never.
    if (this.pointerInside || this.dispatchingCursor) return;
    const timestampMs = axisPointerTimestamp(event);
    if (timestampMs === null) return;
    this.queueCursor(timestampMs);
  };

  private readonly handleDataZoom = (event: unknown) => {
    if (!this.scene || this.rangeSelectionDragActive) return;
    const baseDomain = this.primaryDragBaseDomain ?? this.scene.interactionDomain ?? this.scene.xDomain;
    const domain = zoomDomain(event, { ...this.scene, xDomain: baseDomain });
    if (!domain) return;
    if (this.primaryDragActive) {
      // ECharts already renders the native pan while the pointer moves. Deferring the React
      // domain callback until release avoids feeding each intermediate percentage range back
      // through a newly narrowed x-axis, which would otherwise make the visible span drift.
      this.pendingPrimaryDragDomain = domain;
      // A pan that takes over from a wheel zoom supersedes its pending commit.
      this.cancelPendingZoomCommit();
      return;
    }
    if (this.programmaticZoom) {
      // resetZoom(): keep the synchronous commit so the caller's follow-up (e.g. return to Live)
      // runs after it and is not overwritten by a delayed commit.
      this.cancelPendingZoomCommit();
      this.options?.onXDomainChange(domain);
      return;
    }
    // #1810: ECharts already shows the zoomed window. Commit it to the React viewport once the
    // wheel gesture pauses, not on every tick.
    this.pendingZoomDomain = domain;
    if (this.zoomCommitTimer !== null) clearTimeout(this.zoomCommitTimer);
    this.zoomCommitTimer = setTimeout(() => {
      this.zoomCommitTimer = null;
      const pending = this.pendingZoomDomain;
      this.pendingZoomDomain = null;
      if (pending) this.options?.onXDomainChange(pending);
    }, ZOOM_COMMIT_IDLE_MS);
  };

  initialize(options: ChartRendererInitOptions): void {
    if (this.instance && !this.instance.isDisposed()) return;
    this.options = options;
    this.maximumLivePoints = options.maximumLivePoints ?? chartPointBudget("renderer-live-tail");
    this.container = options.container;
    this.container.dataset.rangeSelectionInput = "idle";
    this.instance = this.runtime.init(options.container, options.renderer);
    this.instance.on("updateAxisPointer", this.handleAxisPointer);
    this.instance.on("dataZoom", this.handleDataZoom);
    this.container.ownerDocument.defaultView?.addEventListener(
      "pointerdown",
      this.handleWindowPointerDown,
      true,
    );
    this.container.addEventListener("mousedown", this.handleContainerMouseDown, true);
    this.container.addEventListener("mousemove", this.handleContainerPointer, true);
    this.container.addEventListener("mouseleave", this.handleContainerLeave);
    this.container.ownerDocument.defaultView?.addEventListener(
      "pointermove",
      this.handleWindowRangePointerMove,
      true,
    );
    this.container.ownerDocument.defaultView?.addEventListener("pointerup", this.handleWindowPointerUp, true);
    this.container.ownerDocument.defaultView?.addEventListener(
      "pointercancel",
      this.handleWindowPointerCancel,
      true,
    );
    this.container.ownerDocument.defaultView?.addEventListener("mouseup", this.handleWindowMouseUp, true);
  }

  setScene(scene: ChartRendererScene): void {
    if (!this.instance) throw new Error("Chart renderer must be initialized before setting a scene");
    const signature = sceneDataSignature(scene);
    const unchangedData = this.scene !== null && signature === this.renderedSignature;
    if (this.scene && windowReplaced(this.scene, scene)) {
      // An explicit range selection replaced the whole window: a gesture on the old window is void.
      this.cancelPendingZoomCommit();
      this.pendingPrimaryDragDomain = null;
      this.yBoundsContext = null;
    }
    this.scene = scene;
    this.lastCommittedCursorTimestampMs = undefined;
    // #1810: a wheel zoom or drag pan that ECharts already shows but has not been committed to
    // React yet must survive a scene refresh (live sample, clock tick); otherwise the refresh
    // would write the pre-gesture window back and undo the user's zoom.
    const pendingWindow = this.pendingZoomDomain ?? this.pendingPrimaryDragDomain;
    const rendered = pendingWindow ? { ...scene, xDomain: pendingWindow } : scene;
    const axisModel = buildChartYAxisModel(rendered.series);
    const yBounds = this.computeYBounds(rendered, axisModel);
    const offScaleKey = [...yBounds.values()]
      .flatMap((axis) => axis.offScaleThresholds.map((threshold) => threshold.id))
      .sort()
      .join(",");
    // A threshold that moved into or out of the fitted scale changes the drawn mark lines.
    if (unchangedData && offScaleKey === this.renderedOffScaleKey) {
      // Only the visible window moved (zoom, pan, shared domain, live-follow tick without new
      // data). Merge the window and the fitted Y bounds into the existing chart; series data is
      // not rebuilt.
      this.instance.setOption(
        { ...xWindowOption(rendered), ...yWindowOption(axisModel, yBounds) },
        { notMerge: false, lazyUpdate: false },
      );
      this.publishYBounds();
      return;
    }
    this.renderedSignature = signature;
    this.renderedOffScaleKey = offScaleKey;
    // #1844: the actual number of drawn points, and the measured cost of drawing them.
    const drawnPoints = rendered.series.reduce(
      (total, series) =>
        series.visible
          ? total + series.segments.reduce((sum, segment) => sum + segment.points.length, 0)
          : total,
      0,
    );
    const startedAt = performance.now();
    this.instance.setOption(rendererOption(rendered, axisModel, yBounds), {
      notMerge: false,
      lazyUpdate: false,
      replaceMerge: ["series", "yAxis"],
    });
    const renderMs = performance.now() - startedAt;
    this.fullRenders += 1;
    // A rebuilt option drops the previous axis pointer; the next shared value is shown again.
    this.lastSharedCursorMs = undefined;
    recordChartRenderCost(drawnPoints, renderMs);
    if (this.container) {
      this.container.dataset.chartRenderedPoints = String(drawnPoints);
      this.container.dataset.chartFullRenders = String(this.fullRenders);
      this.container.dataset.chartRenderMs = renderMs.toFixed(1);
    }
    this.publishYBounds();
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
    // #1866: the plot under the mouse already shows its own pointer; re-dispatching the shared value
    // back into it (and the same value again) only repainted and echoed.
    if (this.pointerInside || timestampMs === this.lastSharedCursorMs) return;
    this.lastSharedCursorMs = timestampMs;
    this.dispatchingCursor = true;
    try {
      if (timestampMs === null) {
        this.instance.dispatchAction({ type: "hideTip" });
        return;
      }
      this.instance.dispatchAction({
        type: "updateAxisPointer",
        xAxisIndex: 0,
        value: timestampMs,
      });
    } finally {
      this.dispatchingCursor = false;
    }
  }

  setSharedXDomain(domain: ChartRendererScene["xDomain"]): void {
    if (!this.scene) return;
    this.setScene({ ...this.scene, xDomain: domain });
  }

  resize(): void {
    this.instance?.resize();
  }

  resetZoom(): void {
    this.programmaticZoom = true;
    try {
      this.instance?.dispatchAction({ type: "dataZoom", start: 0, end: 100 });
    } finally {
      this.programmaticZoom = false;
    }
    this.cancelPendingZoomCommit();
  }

  /**
   * PNG of the currently visible plot (#1658): rendered locally from the mounted Canvas, so it
   * works offline and never touches telemetry, acquisition or the network. Returns null when the
   * renderer is disposed or cannot export.
   */
  exportImage(): string | null {
    if (!this.instance || this.instance.isDisposed() || !this.instance.getDataURL) return null;
    return this.instance.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: "#06142a" });
  }

  dispose(): void {
    if (!this.instance) return;
    this.instance.off("updateAxisPointer", this.handleAxisPointer);
    this.instance.off("dataZoom", this.handleDataZoom);
    this.container?.ownerDocument.defaultView?.removeEventListener(
      "pointerdown",
      this.handleWindowPointerDown,
      true,
    );
    this.container?.removeEventListener("mousedown", this.handleContainerMouseDown, true);
    this.container?.removeEventListener("mousemove", this.handleContainerPointer, true);
    this.container?.removeEventListener("mouseleave", this.handleContainerLeave);
    this.container?.ownerDocument.defaultView?.removeEventListener(
      "pointermove",
      this.handleWindowRangePointerMove,
      true,
    );
    this.container?.ownerDocument.defaultView?.removeEventListener(
      "pointerup",
      this.handleWindowPointerUp,
      true,
    );
    this.container?.ownerDocument.defaultView?.removeEventListener(
      "pointercancel",
      this.handleWindowPointerCancel,
      true,
    );
    this.container?.ownerDocument.defaultView?.removeEventListener("mouseup", this.handleWindowMouseUp, true);
    this.cancelPendingCursor();
    this.cancelPendingZoomCommit();
    this.renderedSignature = null;
    this.yBounds = new Map();
    this.yBoundsContext = null;
    this.renderedOffScaleKey = "";
    this.lastCommittedCursorTimestampMs = undefined;
    this.pointerInside = false;
    this.lastSharedCursorMs = undefined;
    this.primaryDragActive = false;
    this.primaryDragBaseDomain = null;
    this.pendingPrimaryDragDomain = null;
    this.rangeSelectionDragActive = false;
    this.rangeSelectionStartMs = null;
    this.rangeSelectionLastMs = null;
    this.rangeSelectionStartClientX = null;
    this.rangeSelectionLastClientX = null;
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
