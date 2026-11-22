"use client";

import { useMemo } from "react";

import { ChartRendererHost } from "@/components/charts/chart-renderer-host";
import { downloadChartPng } from "@/components/charts/chart-png-export";
import { ChartShell } from "@/components/charts/chart-shell";
import type { ChartXDomain } from "@/features/charts/domain";
import { inspectChartAtTimestamp } from "@/features/charts/inspection";
import { EChartsRendererAdapter } from "@/features/charts/echarts-adapter";
import type { SavedDashboardChartGroup } from "@/features/live-dashboards/chart";
import { DashboardChartLegend } from "./dashboard-chart-legend";

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
  const inspection = useMemo(
    () =>
      sharedCursorMs === null
        ? null
        : inspectChartAtTimestamp(group.scene, sharedCursorMs, { withinObservedSpan: true }),
    [group.scene, sharedCursorMs],
  );
  const unitLabel = group.nativeUnits.join(" · ") || "без одиниць";

  return (
    <div data-testid="saved-dashboard-chart-panel">
      <ChartShell
        title={group.title}
        context={`${unitLabel} · ${group.nativeUnits.length} ${
          group.nativeUnits.length === 1 ? "динамічна вісь Y" : "динамічні осі Y"
        }`}
        selectedRange={rangeLabel}
        locale="uk"
        series={group.scene.series}
        inspection={inspection}
        legend={
          <DashboardChartLegend
            group={group}
            inspection={inspection}
            onToggleSeries={onToggleSeries}
            onSoloSeries={onSoloSeries}
          />
        }
        onToggleSeries={onToggleSeries}
        onSoloSeries={onSoloSeries}
        onExportImage={() => void downloadChartPng(adapter, group.title)}
        onResetZoom={() => {
          adapter.resetZoom();
          onXDomainChange(resetDomain);
          onResetView();
        }}
      >
        <ChartRendererHost
          adapter={adapter}
          scene={group.scene}
          // Rolling display refreshes must preserve the mounted Canvas without animated blank transitions.
          reducedMotion
          sharedCursorMs={sharedCursorMs}
          interactionDomain={resetDomain}
          onCursor={(nextInspection) => onSharedCursorChange(nextInspection?.timestampMs ?? null)}
          onXDomainChange={onXDomainChange}
        />
      </ChartShell>
    </div>
  );
}
