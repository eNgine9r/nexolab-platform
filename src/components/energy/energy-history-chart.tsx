"use client";

import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { ChartRendererHost } from "@/components/charts/chart-renderer-host";
import { ChartShell } from "@/components/charts/chart-shell";
import {
  chartSeriesKey,
  type ChartCursorInspection,
  type ChartSeries,
  type ChartXDomain,
} from "@/features/charts/domain";
import { EChartsRendererAdapter } from "@/features/charts/echarts-adapter";
import { inspectChartAtTimestamp } from "@/features/charts/inspection";
import { partitionChartSeriesByAxisBudget } from "@/features/charts/units";
import { buildEnergyChartScene } from "@/features/energy/energy-chart";
import {
  energySeriesDisplayUnit,
  type EnergySeriesSelection,
} from "@/features/energy/energy-series-selection";
import { ENERGY_METRICS } from "@/features/energy/energy-telemetry";
import type { EnergyTelemetryModel } from "@/hooks/use-energy-telemetry";

const NARROW_CHART_QUERY = "(max-width: 767px)";
function subscribeAxisBudget(onChange: () => void): () => void {
  if (!window.matchMedia) return () => undefined;
  const query = window.matchMedia(NARROW_CHART_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}
function axisBudgetSnapshot(): number {
  return window.matchMedia?.(NARROW_CHART_QUERY).matches ? 3 : 5;
}
function serverAxisBudgetSnapshot(): number {
  return 5;
}

export function EnergyHistoryChart({
  telemetry,
  selectedUnitIds,
  selectedPairs,
  visibilityRevision = 0,
}: {
  telemetry: EnergyTelemetryModel;
  selectedUnitIds: readonly number[];
  selectedPairs?: readonly EnergySeriesSelection[];
  visibilityRevision?: number;
}) {
  const [sharedCursorMs, setSharedCursorMs] = useState<number | null>(null);
  const [viewportDomain, setViewportDomain] = useState<ChartXDomain | null>(null);
  const [hiddenSeriesKeys, setHiddenSeriesKeys] = useState<Set<string>>(() => new Set());
  const [soloSeriesKey, setSoloSeriesKey] = useState<string | null>(null);
  const [resetRevision, setResetRevision] = useState(0);
  const axisBudget = useSyncExternalStore(subscribeAxisBudget, axisBudgetSnapshot, serverAxisBudgetSnapshot);
  const baseScene = useMemo(
    () =>
      buildEnergyChartScene({
        samples: telemetry.historySamples,
        selectedMetrics: telemetry.selectedMetrics,
        selectedPairs,
        selectedUnitIds,
        status: telemetry.status,
        historyWindow: telemetry.historyWindow,
      }),
    [
      selectedPairs,
      selectedUnitIds,
      telemetry.historySamples,
      telemetry.historyWindow,
      telemetry.selectedMetrics,
      telemetry.status,
    ],
  );
  const scene = useMemo(
    () => ({
      ...baseScene,
      xDomain: viewportDomain ?? baseScene.xDomain,
      series: baseScene.series.map((series) => {
        const key = chartSeriesKey(series.identity);
        return { ...series, visible: soloSeriesKey ? soloSeriesKey === key : !hiddenSeriesKeys.has(key) };
      }),
    }),
    [baseScene, hiddenSeriesKeys, soloSeriesKey, viewportDomain],
  );
  const panels = useMemo(
    () => partitionChartSeriesByAxisBudget(scene.series, axisBudget),
    [axisBudget, scene.series],
  );
  const inspection = useMemo(
    () => (sharedCursorMs === null ? null : inspectChartAtTimestamp(scene, sharedCursorMs)),
    [scene, sharedCursorMs],
  );

  useEffect(() => {
    let disposed = false;
    void Promise.resolve().then(() => {
      if (disposed) return;
      setSharedCursorMs(null);
      setViewportDomain(null);
      setHiddenSeriesKeys(new Set());
      setSoloSeriesKey(null);
      setResetRevision((current) => current + 1);
    });
    return () => {
      disposed = true;
    };
  }, [telemetry.historyRange]);
  useEffect(() => {
    let disposed = false;
    void Promise.resolve().then(() => {
      if (disposed) return;
      setHiddenSeriesKeys(new Set());
      setSoloSeriesKey(null);
    });
    return () => {
      disposed = true;
    };
  }, [visibilityRevision]);

  const toggleSeries = (key: string) => {
    setSoloSeriesKey(null);
    setHiddenSeriesKeys((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };
  const resetZoom = () => {
    setViewportDomain(null);
    setResetRevision((current) => current + 1);
  };
  const changeDomain = (domain: ChartXDomain) =>
    setViewportDomain(
      domain.fromMs === baseScene.xDomain.fromMs && domain.toMs === baseScene.xDomain.toMs ? null : domain,
    );
  return (
    <div
      data-testid="energy-history-chart"
      className="min-w-0 space-y-3 [&_[aria-label='Легенда_графіка']>div]:grid [&_[aria-label='Легенда_графіка']>div]:grid-cols-[auto_1fr_1fr] [&_[aria-label='Легенда_графіка']>div>button]:min-h-10 [&_[aria-label='Легенда_графіка']>div>button:first-of-type]:col-start-2 [&_[aria-label='Легенда_графіка']>div>span:nth-of-type(2)]:col-span-2"
    >
      {panels.map((series, index) => (
        <EnergyChartPanel
          key={index}
          series={series}
          xDomain={scene.xDomain}
          interactionDomain={baseScene.xDomain}
          range={telemetry.historyRange}
          panelIndex={index}
          panelCount={panels.length}
          inspection={inspection}
          sharedCursorMs={sharedCursorMs}
          resetRevision={resetRevision}
          onToggle={toggleSeries}
          onSolo={(key) => setSoloSeriesKey((current) => (current === key ? null : key))}
          onReset={resetZoom}
          onCursor={(next) => setSharedCursorMs(next?.timestampMs ?? null)}
          onDomainChange={changeDomain}
        />
      ))}
    </div>
  );
}

function EnergyChartPanel({
  series,
  xDomain,
  interactionDomain,
  range,
  panelIndex,
  panelCount,
  inspection,
  sharedCursorMs,
  resetRevision,
  onToggle,
  onSolo,
  onReset,
  onCursor,
  onDomainChange,
}: {
  series: ChartSeries[];
  xDomain: ChartXDomain;
  interactionDomain: ChartXDomain;
  range: string;
  panelIndex: number;
  panelCount: number;
  inspection: ChartCursorInspection | null;
  sharedCursorMs: number | null;
  resetRevision: number;
  onToggle: (key: string) => void;
  onSolo: (key: string) => void;
  onReset: () => void;
  onCursor: (inspection: ChartCursorInspection | null) => void;
  onDomainChange: (domain: ChartXDomain) => void;
}) {
  const adapter = useMemo(() => new EChartsRendererAdapter(), []);
  useEffect(() => {
    adapter.resetZoom();
  }, [adapter, resetRevision]);
  const scene = useMemo(() => ({ series, xDomain }), [series, xDomain]);
  const metrics = ENERGY_METRICS.filter((metric) =>
    series.some((item) => item.identity.metric === metric.id),
  );
  const units = metrics.map((metric) => energySeriesDisplayUnit(metric.id)).join(" / ");
  const title =
    panelCount > 1
      ? `Енергомоніторинг · ${panelIndex + 1}/${panelCount}`
      : "Енергомоніторинг · Порівняння параметрів";
  return (
    <ChartShell
      title={title}
      context={`${units || "Параметри"} · Збережена історія`}
      selectedRange={range}
      series={series}
      inspection={inspection}
      locale="uk"
      onToggleSeries={onToggle}
      onSoloSeries={onSolo}
      onResetZoom={onReset}
    >
      <ChartRendererHost
        adapter={adapter}
        scene={scene}
        reducedMotion
        sharedCursorMs={sharedCursorMs}
        interactionDomain={interactionDomain}
        onCursor={onCursor}
        onXDomainChange={onDomainChange}
      />
    </ChartShell>
  );
}
