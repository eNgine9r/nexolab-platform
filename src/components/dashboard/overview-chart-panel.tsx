"use client";

import { useMemo, useState } from "react";

import { ChartRendererHost } from "@/components/charts/chart-renderer-host";
import { ChartShell } from "@/components/charts/chart-shell";
import type { ChartCursorInspection, ChartXDomain } from "@/features/charts/domain";
import { EChartsRendererAdapter } from "@/features/charts/echarts-adapter";
import type { OverviewChartGroup } from "@/features/dashboard/overview-chart";

export function OverviewChartPanel({
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
  group: OverviewChartGroup;
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

  return (
    <div data-testid="overview-chart-panel">
      <ChartShell
        title={`XJP60D temperature history · ${group.nativeUnit}`}
        context={`${group.physicalQuantity} · Overview`}
        selectedRange={rangeLabel}
        series={group.scene.series}
        inspection={inspection}
        onToggleSeries={onToggleSeries}
        onSoloSeries={onSoloSeries}
        onResetZoom={() => {
          adapter.resetZoom();
          onXDomainChange(resetDomain);
          onResetView();
        }}
      >
        <ChartRendererHost
          adapter={adapter}
          scene={group.scene}
          reducedMotion
          sharedCursorMs={sharedCursorMs}
          onCursor={(nextInspection) => {
            setInspection(nextInspection);
            onSharedCursorChange(nextInspection?.timestampMs ?? null);
          }}
          onXDomainChange={onXDomainChange}
        />
      </ChartShell>
    </div>
  );
}
