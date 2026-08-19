"use client";

import { useEffect, useMemo, useState } from "react";

import { ChartRendererHost } from "@/components/charts/chart-renderer-host";
import { ChartShell } from "@/components/charts/chart-shell";
import { chartSeriesKey, type ChartCursorInspection, type ChartXDomain } from "@/features/charts/domain";
import { EChartsRendererAdapter } from "@/features/charts/echarts-adapter";
import { formatChartExactTimestamp } from "@/features/charts/format";
import { buildEnergyChartScene } from "@/features/energy/energy-chart";
import { ENERGY_METRICS } from "@/features/energy/energy-telemetry";
import type { EnergyTelemetryModel } from "@/hooks/use-energy-telemetry";

export function EnergyHistoryChart({
  telemetry,
  selectedUnitIds,
}: {
  telemetry: EnergyTelemetryModel;
  selectedUnitIds: readonly number[];
}) {
  const adapter = useMemo(() => new EChartsRendererAdapter(), []);
  const [inspection, setInspection] = useState<ChartCursorInspection | null>(null);
  const [sharedCursorMs, setSharedCursorMs] = useState<number | null>(null);
  const [viewportDomain, setViewportDomain] = useState<ChartXDomain | null>(null);
  const [hiddenSeriesKeys, setHiddenSeriesKeys] = useState<Set<string>>(() => new Set());
  const [soloSeriesKey, setSoloSeriesKey] = useState<string | null>(null);
  const baseScene = useMemo(
    () =>
      buildEnergyChartScene({
        samples: telemetry.historySamples,
        selectedMetric: telemetry.selectedMetric,
        selectedUnitIds,
        status: telemetry.status,
        historyWindow: telemetry.historyWindow,
      }),
    [
      selectedUnitIds,
      telemetry.historySamples,
      telemetry.historyWindow,
      telemetry.selectedMetric,
      telemetry.status,
    ],
  );
  const scene = useMemo(
    () => ({
      ...baseScene,
      xDomain: viewportDomain ?? baseScene.xDomain,
      series: baseScene.series.map((series) => {
        const key = chartSeriesKey(series.identity);
        return {
          ...series,
          visible: soloSeriesKey ? soloSeriesKey === key : !hiddenSeriesKeys.has(key),
        };
      }),
    }),
    [baseScene, hiddenSeriesKeys, soloSeriesKey, viewportDomain],
  );
  const metric = ENERGY_METRICS.find((item) => item.id === telemetry.selectedMetric)!;
  const viewKey = `${telemetry.selectedMetric}:${telemetry.historyRange}`;

  useEffect(() => {
    let disposed = false;
    void Promise.resolve().then(() => {
      if (disposed) return;
      setInspection(null);
      setSharedCursorMs(null);
      setViewportDomain(null);
      setHiddenSeriesKeys(new Set());
      setSoloSeriesKey(null);
    });
    return () => {
      disposed = true;
    };
  }, [viewKey]);

  const toggleSeries = (seriesKey: string) => {
    setSoloSeriesKey(null);
    setHiddenSeriesKeys((current) => {
      const next = new Set(current);
      if (next.has(seriesKey)) next.delete(seriesKey);
      else next.add(seriesKey);
      return next;
    });
  };

  const soloSeries = (seriesKey: string) => {
    setSoloSeriesKey((current) => (current === seriesKey ? null : seriesKey));
  };

  return (
    <div data-testid="energy-history-chart">
      <ChartShell
        title={`Енергомоніторинг · ${metric.label}`}
        context={`${metric.expectedUnit} · canonical persisted history`}
        selectedRange={telemetry.historyRange}
        series={scene.series}
        inspection={inspection}
        formatTimestamp={(timestampMs) => formatChartExactTimestamp(timestampMs)}
        onToggleSeries={toggleSeries}
        onSoloSeries={soloSeries}
        onResetZoom={() => {
          adapter.resetZoom();
          setViewportDomain(null);
        }}
      >
        <ChartRendererHost
          adapter={adapter}
          scene={scene}
          reducedMotion
          sharedCursorMs={sharedCursorMs}
          onCursor={(nextInspection) => {
            setInspection(nextInspection);
            setSharedCursorMs(nextInspection?.timestampMs ?? null);
          }}
          onXDomainChange={setViewportDomain}
        />
      </ChartShell>
    </div>
  );
}
