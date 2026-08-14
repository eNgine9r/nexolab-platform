"use client";

import { useMemo, useState } from "react";

import { ChartRendererHost } from "@/components/charts/chart-renderer-host";
import { ChartShell } from "@/components/charts/chart-shell";
import type { ChartCursorInspection, ChartXDomain } from "@/features/charts/domain";
import { EChartsRendererAdapter } from "@/features/charts/echarts-adapter";
import type { LiveChartGroup } from "@/features/live/live-chart";

export function LiveChartPanel({
  group,
  rangeLabel,
  sharedCursorMs,
  resetDomain,
  onSharedCursorChange,
  onXDomainChange,
  onToggleSeries,
  onSoloSeries,
}: {
  group: LiveChartGroup;
  rangeLabel: string;
  sharedCursorMs: number | null;
  resetDomain: ChartXDomain;
  onSharedCursorChange: (timestampMs: number | null) => void;
  onXDomainChange: (domain: ChartXDomain) => void;
  onToggleSeries: (seriesKey: string) => void;
  onSoloSeries: (seriesKey: string) => void;
}) {
  const adapter = useMemo(() => new EChartsRendererAdapter(), []);
  const [inspection, setInspection] = useState<ChartCursorInspection | null>(null);
  const unitLabel = group.nativeUnits.join(" · ") || "no units";

  return (
    <ChartShell
      title={`Live Data · ${group.equipmentId}`}
      context={`${unitLabel} · ${group.nativeUnits.length} dynamic Y ${group.nativeUnits.length === 1 ? "axis" : "axes"}`}
      selectedRange={rangeLabel}
      series={group.scene.series}
      inspection={inspection}
      onToggleSeries={onToggleSeries}
      onSoloSeries={onSoloSeries}
      onResetZoom={() => {
        adapter.resetZoom();
        onXDomainChange(resetDomain);
      }}
    >
      <ChartRendererHost
        adapter={adapter}
        scene={group.scene}
        sharedCursorMs={sharedCursorMs}
        onCursor={(nextInspection) => {
          setInspection(nextInspection);
          onSharedCursorChange(nextInspection?.timestampMs ?? null);
        }}
        onXDomainChange={onXDomainChange}
      />
    </ChartShell>
  );
}
