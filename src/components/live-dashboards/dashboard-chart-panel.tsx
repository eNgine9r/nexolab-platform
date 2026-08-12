"use client";

import { useMemo, useState } from "react";

import { ChartRendererHost } from "@/components/charts/chart-renderer-host";
import { ChartShell } from "@/components/charts/chart-shell";
import type { ChartCursorInspection, ChartXDomain } from "@/features/charts/domain";
import { EChartsRendererAdapter } from "@/features/charts/echarts-adapter";
import type { SavedDashboardChartGroup } from "@/features/live-dashboards/chart";

const CURSOR_TOLERANCE_MS = 30_000;

function withinTolerance(inspection: ChartCursorInspection | null): ChartCursorInspection | null {
  if (!inspection?.point) return inspection;
  if (Math.abs(inspection.point.timestampMs - inspection.timestampMs) <= CURSOR_TOLERANCE_MS) {
    return inspection;
  }
  return { ...inspection, point: null };
}

export function DashboardChartPanel({
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
  group: SavedDashboardChartGroup;
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
    <div data-testid="saved-dashboard-chart-panel">
      <ChartShell
        title={`Saved Dashboard · ${group.nativeUnit}`}
        context={`${group.physicalQuantity} · synchronized scale`}
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
          sharedCursorMs={sharedCursorMs}
          onCursor={(nextInspection) => {
            const truthful = withinTolerance(nextInspection);
            setInspection(truthful);
            onSharedCursorChange(truthful?.timestampMs ?? null);
          }}
          onXDomainChange={onXDomainChange}
        />
      </ChartShell>
    </div>
  );
}
