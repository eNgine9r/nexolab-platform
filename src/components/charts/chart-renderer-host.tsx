"use client";

import { useEffect, useRef, type KeyboardEvent } from "react";

import type { ChartCursorInspection, ChartXDomain } from "@/features/charts/domain";
import { chartInspectionTimestamps, inspectChartAtTimestamp } from "@/features/charts/inspection";
import type { ChartRendererAdapter, ChartRendererScene } from "@/features/charts/renderer-adapter";

export function ChartRendererHost({
  adapter,
  scene,
  renderer = "canvas",
  reducedMotion = false,
  sharedCursorMs = null,
  onCursor,
  onXDomainChange,
}: {
  adapter: ChartRendererAdapter;
  scene: ChartRendererScene;
  renderer?: "canvas" | "svg";
  reducedMotion?: boolean;
  sharedCursorMs?: number | null;
  onCursor: (inspection: ChartCursorInspection | null) => void;
  onXDomainChange: (domain: ChartXDomain) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const callbacksRef = useRef({ onCursor, onXDomainChange });

  useEffect(() => {
    callbacksRef.current = { onCursor, onXDomainChange };
  }, [onCursor, onXDomainChange]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    adapter.initialize({
      container,
      renderer,
      reducedMotion,
      maximumLivePoints: 240,
      onCursor: (inspection) => callbacksRef.current.onCursor(inspection),
      onXDomainChange: (domain) => callbacksRef.current.onXDomainChange(domain),
    });
    const observer = new ResizeObserver(() => adapter.resize());
    observer.observe(container);
    return () => {
      observer.disconnect();
      adapter.dispose();
    };
  }, [adapter, reducedMotion, renderer]);

  useEffect(() => {
    if (!adapter.isDisposed()) adapter.setScene(scene);
  }, [adapter, scene]);

  useEffect(() => {
    if (!adapter.isDisposed()) adapter.setSharedCursor(sharedCursorMs);
  }, [adapter, sharedCursorMs]);

  const inspectWithKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End", "Escape"].includes(event.key)) return;
    event.preventDefault();
    if (event.key === "Escape") {
      adapter.setSharedCursor(null);
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
    adapter.setSharedCursor(timestamp);
    onCursor(inspectChartAtTimestamp(scene, timestamp));
  };

  return (
    <div
      ref={containerRef}
      className="h-[320px] min-h-64 w-full min-w-0"
      data-testid="chart-renderer-host"
      role="application"
      aria-label="Interactive telemetry plot"
      aria-keyshortcuts="ArrowLeft ArrowRight Home End Escape"
      onKeyDown={inspectWithKeyboard}
      tabIndex={0}
    />
  );
}
