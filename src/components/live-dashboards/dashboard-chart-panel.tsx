"use client";

import { useMemo } from "react";

import { ChartRendererHost } from "@/components/charts/chart-renderer-host";
import { downloadChartPng } from "@/components/charts/chart-png-export";
import type { ChartLegendGroup } from "@/components/charts/chart-series-legend";
import { ChartShell } from "@/components/charts/chart-shell";
import type { ChartXDomain } from "@/features/charts/domain";
import { inspectChartAtTimestamp } from "@/features/charts/inspection";
import { EChartsRendererAdapter } from "@/features/charts/echarts-adapter";
import type { SavedDashboardChartGroup } from "@/features/live-dashboards/chart";

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
  onShowAllSeries,
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
  onShowAllSeries?: () => void;
}) {
  const adapter = useMemo(() => new EChartsRendererAdapter(), []);
  const inspection = useMemo(
    () =>
      sharedCursorMs === null
        ? null
        : inspectChartAtTimestamp(group.scene, sharedCursorMs, { withinObservedSpan: true }),
    [group.scene, sharedCursorMs],
  );
  const legendGroups = useMemo(() => {
    const byKey = new Map<string, ChartLegendGroup>();
    for (const [seriesKey, instrument] of group.instruments)
      byKey.set(seriesKey, { key: instrument.key, label: instrument.label, secondary: instrument.node });
    return byKey;
  }, [group.instruments]);
  const unitLabel = group.nativeUnits.join(" · ") || "без одиниць";

  return (
    <div data-testid="saved-dashboard-chart-panel">
      <ChartShell
        title={group.title}
        context={unitLabel}
        selectedRange={rangeLabel}
        locale="uk"
        series={group.scene.series}
        requestedWindow={resetDomain}
        inspection={inspection}
        legendGroups={legendGroups}
        onToggleSeries={onToggleSeries}
        onSoloSeries={onSoloSeries}
        onShowAllSeries={onShowAllSeries}
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
