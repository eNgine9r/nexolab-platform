"use client";

import { useEffect, useId, useRef, type KeyboardEvent } from "react";
import { useDisplayTimeZone } from "@/hooks/use-display-time-zone";

import type { ChartCursorInspection, ChartXDomain } from "@/features/charts/domain";
import { chartPointBudget } from "@/features/charts/point-budget";
import { chartInspectionTimestamps, inspectChartAtTimestamp } from "@/features/charts/inspection";
import type { ChartRendererAdapter, ChartRendererScene } from "@/features/charts/renderer-adapter";
import { CHART_GRID_INSETS } from "@/features/charts/echarts-adapter";
import { reportChartPlotWidth } from "@/features/charts/viewport-budget";

import { useChartView } from "./chart-view-context";

export function ChartRendererHost({
  adapter,
  scene,
  renderer = "canvas",
  reducedMotion = false,
  sharedCursorMs = null,
  interactionDomain = scene.xDomain,
  onCursor,
  onXDomainChange,
  onRangeSelectionChange,
}: {
  adapter: ChartRendererAdapter;
  scene: ChartRendererScene;
  renderer?: "canvas" | "svg";
  reducedMotion?: boolean;
  sharedCursorMs?: number | null;
  interactionDomain?: ChartXDomain;
  onCursor: (inspection: ChartCursorInspection | null) => void;
  onXDomainChange: (domain: ChartXDomain) => void;
  onRangeSelectionChange?: (domain: ChartXDomain | null) => void;
}) {
  const displayTimeZone = useDisplayTimeZone();
  const { yScale, reportVisibleDomain } = useChartView();
  const containerRef = useRef<HTMLDivElement>(null);
  const chartId = useId();
  const callbacksRef = useRef({ onCursor, onXDomainChange, onRangeSelectionChange });

  useEffect(() => {
    callbacksRef.current = { onCursor, onXDomainChange, onRangeSelectionChange };
  }, [onCursor, onRangeSelectionChange, onXDomainChange]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    adapter.initialize({
      container,
      renderer,
      reducedMotion,
      maximumLivePoints: chartPointBudget("renderer-live-tail"),
      onCursor: (inspection) => callbacksRef.current.onCursor(inspection),
      onXDomainChange: (domain) => callbacksRef.current.onXDomainChange(domain),
      onRangeSelectionChange: (domain) => callbacksRef.current.onRangeSelectionChange?.(domain),
    });
    // #1844: the plot-area width sizes zoomed detail (about two points per pixel).
    const reportWidth = () =>
      reportChartPlotWidth(chartId, container.clientWidth - CHART_GRID_INSETS.left - CHART_GRID_INSETS.right);
    reportWidth();
    const observer = new ResizeObserver(() => {
      adapter.resize();
      reportWidth();
    });
    observer.observe(container);
    return () => {
      observer.disconnect();
      reportChartPlotWidth(chartId, null);
      adapter.dispose();
    };
  }, [adapter, chartId, reducedMotion, renderer]);

  useEffect(() => {
    if (!adapter.isDisposed())
      adapter.setScene({
        ...scene,
        interactionDomain,
        displayTimeZone: scene.displayTimeZone ?? displayTimeZone,
        yScale: scene.yScale ?? yScale,
      });
  }, [adapter, displayTimeZone, interactionDomain, scene, yScale]);

  // #1843: the header names the interval actually shown, not only the selected period.
  const { fromMs: visibleFromMs, toMs: visibleToMs } = scene.xDomain;
  const { fromMs: fullFromMs, toMs: fullToMs } = interactionDomain;
  useEffect(() => {
    reportVisibleDomain({ fromMs: visibleFromMs, toMs: visibleToMs }, { fromMs: fullFromMs, toMs: fullToMs });
  }, [fullFromMs, fullToMs, reportVisibleDomain, visibleFromMs, visibleToMs]);

  useEffect(() => {
    if (!adapter.isDisposed()) adapter.setSharedCursor(sharedCursorMs);
  }, [adapter, displayTimeZone, sharedCursorMs]);

  const inspectWithKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End", "Escape"].includes(event.key)) return;
    event.preventDefault();
    if (event.key === "Escape") {
      adapter.setSharedCursor(null, { explicit: true });
      onCursor(null);
      return;
    }
    const timestamps = chartInspectionTimestamps(scene);
    if (timestamps.length === 0) return;
    let timestamp: number;
    if (event.key === "Home") timestamp = timestamps[0];
    else if (event.key === "End") timestamp = timestamps.at(-1)!;
    else if (sharedCursorMs === null)
      timestamp = event.key === "ArrowLeft" ? timestamps.at(-1)! : timestamps[0];
    else if (event.key === "ArrowLeft") {
      timestamp = [...timestamps].reverse().find((candidate) => candidate < sharedCursorMs) ?? timestamps[0];
    } else {
      timestamp = timestamps.find((candidate) => candidate > sharedCursorMs) ?? timestamps.at(-1)!;
    }
    adapter.setSharedCursor(timestamp, { explicit: true });
    onCursor(inspectChartAtTimestamp(scene, timestamp));
  };

  return (
    <div
      className="h-[320px] min-h-64 w-full min-w-0"
      data-testid="chart-renderer-host"
      data-chart-x-domain-from-ms={scene.xDomain.fromMs}
      data-chart-x-domain-to-ms={scene.xDomain.toMs}
      style={scene.rangeSelectionEnabled ? { touchAction: "pan-y" } : undefined}
      data-range-selection-enabled={scene.rangeSelectionEnabled ? "true" : "false"}
      role="application"
      aria-label="Interactive telemetry plot"
      aria-keyshortcuts="ArrowLeft ArrowRight Home End Escape"
      onKeyDown={inspectWithKeyboard}
      tabIndex={0}
    >
      <div ref={containerRef} className="h-full w-full min-w-0" data-testid="chart-renderer-surface" />
    </div>
  );
}
