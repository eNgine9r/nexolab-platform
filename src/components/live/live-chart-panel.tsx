"use client";

import { useMemo, useState } from "react";

import { ChartRendererHost } from "@/components/charts/chart-renderer-host";
import { ChartShell } from "@/components/charts/chart-shell";
import type { ChartCursorInspection, ChartXDomain } from "@/features/charts/domain";
import { EChartsRendererAdapter } from "@/features/charts/echarts-adapter";
import { displayUnit } from "@/features/charts/units";
import type { LiveChartGroup } from "@/features/live/live-chart";

export function LiveChartPanel({
  group,
  rangeLabel,
  sharedCursorMs,
  resetDomain,
  onSharedCursorChange,
  onXDomainChange,
  onResetView,
  onToggleSeries,
  onSoloSeries,
}: {
  group: LiveChartGroup;
  rangeLabel: string;
  sharedCursorMs: number | null;
  resetDomain: ChartXDomain;
  onSharedCursorChange: (timestampMs: number | null) => void;
  onXDomainChange: (domain: ChartXDomain) => void;
  onResetView: () => void;
  onToggleSeries: (seriesKey: string) => void;
  onSoloSeries: (seriesKey: string) => void;
}) {
  const adapter = useMemo(() => new EChartsRendererAdapter(), []);
  const [inspection, setInspection] = useState<ChartCursorInspection | null>(null);
  const unitLabel = group.nativeUnits.map(displayUnit).join(" · ") || "no units";
  const axisCount = group.nativeUnits.length;

  return (
    <ChartShell
      title={`Live Data · ${group.equipmentId}`}
      context={`${unitLabel} · ${axisCount} dynamic Y ${axisCount === 1 ? "axis" : "axes"}`}
      selectedRange={rangeLabel}
      series={group.scene.series}
      inspection={inspection}
      onToggleSeries={onToggleSeries}
      onSoloSeries={onSoloSeries}
      onResetZoom={() => {
        adapter.resetZoom();
        onResetView();
      }}
    >
      <ChartRendererHost
        adapter={adapter}
        scene={group.scene}
        reducedMotion
        sharedCursorMs={sharedCursorMs}
        interactionDomain={resetDomain}
        onCursor={(nextInspection) => {
          setInspection(nextInspection);
          onSharedCursorChange(nextInspection?.timestampMs ?? null);
        }}
        onXDomainChange={onXDomainChange}
      />
    </ChartShell>
  );
}
