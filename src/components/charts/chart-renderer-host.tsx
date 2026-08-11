"use client";

import { useEffect, useRef } from "react";

import type { ChartCursorInspection, ChartXDomain } from "@/features/charts/domain";
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

  return (
    <div
      ref={containerRef}
      className="h-[320px] min-h-64 w-full min-w-0"
      data-testid="chart-renderer-host"
      role="application"
      aria-label="Interactive telemetry plot"
      tabIndex={0}
    />
  );
}
