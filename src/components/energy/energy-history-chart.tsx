"use client";

import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { ChartRendererHost } from "@/components/charts/chart-renderer-host";
import { downloadChartPng } from "@/components/charts/chart-png-export";
import { ChartShell } from "@/components/charts/chart-shell";
import {
  chartSeriesKey,
  type ChartCursorInspection,
  type ChartSeries,
  type ChartXDomain,
} from "@/features/charts/domain";
import { EChartsRendererAdapter } from "@/features/charts/echarts-adapter";
import { inspectChartAtTimestamp } from "@/features/charts/inspection";
import { displayUnit, partitionChartSeriesByAxisBudget } from "@/features/charts/units";
import { DashboardAlertEvents } from "@/components/live-dashboards/dashboard-alert-events";
import { applyAlertAnnotations } from "@/features/charts/alert-events";
import { flipExpiredSeries } from "@/features/charts/series-freshness";
import type { ChartRendererScene } from "@/features/charts/renderer-adapter";
import { useDashboardAlertEvents } from "@/features/live-dashboards/use-dashboard-alert-events";
import { DashboardIntervalStatistics } from "@/components/live-dashboards/dashboard-interval-statistics";
import { energySeriesStatisticsKey } from "@/features/energy/energy-raw-statistics";
import { customHistoryRangeKey, formatCustomHistoryWindow } from "@/features/charts/custom-history-range";
import { useDisplayTimeZone } from "@/hooks/use-display-time-zone";
import { buildEnergyChartScene } from "@/features/energy/energy-chart";
import {
  energySeriesDisplayUnit,
  type EnergySeriesSelection,
} from "@/features/energy/energy-series-selection";
import { ENERGY_METRICS } from "@/features/energy/energy-telemetry";
import type { CommissionedEnergyMeter } from "@/features/energy/energy-commissioned-meters";
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
  selectedMeterKeys,
  meters,
  selectedPairs,
  visibilityRevision = 0,
}: {
  telemetry: EnergyTelemetryModel;
  selectedUnitIds: readonly number[];
  selectedMeterKeys?: readonly string[];
  meters?: readonly CommissionedEnergyMeter[];
  selectedPairs?: readonly EnergySeriesSelection[];
  visibilityRevision?: number;
}) {
  const [sharedCursorMs, setSharedCursorMs] = useState<number | null>(null);
  const [viewportDomain, setViewportDomain] = useState<ChartXDomain | null>(null);
  const [hiddenSeriesKeys, setHiddenSeriesKeys] = useState<Set<string>>(() => new Set());
  const [soloSeriesKey, setSoloSeriesKey] = useState<string | null>(null);
  const [resetRevision, setResetRevision] = useState(0);
  const axisBudget = useSyncExternalStore(subscribeAxisBudget, axisBudgetSnapshot, serverAxisBudgetSnapshot);
  const displayTimeZone = useDisplayTimeZone();
  const historical = telemetry.historyRange === "custom";
  const customWindow = historical ? telemetry.historyWindow : null;
  // Presets keep their bare range keys; a fixed custom window is identified by its bounds.
  const rangeIdentity = customWindow ? customHistoryRangeKey(customWindow) : telemetry.historyRange;
  const rangeLabel = customWindow
    ? formatCustomHistoryWindow(customWindow, displayTimeZone)
    : telemetry.historyRange;
  const baseScene = useMemo(
    () =>
      buildEnergyChartScene({
        samples: telemetry.historySamples,
        selectedMetrics: telemetry.selectedMetrics,
        selectedPairs,
        selectedUnitIds,
        selectedMeterKeys,
        meters,
        status: telemetry.status,
        historyWindow: telemetry.historyWindow,
        cadenceAuthority: telemetry.cadenceAuthority,
        historical,
      }),
    [
      historical,
      selectedPairs,
      selectedUnitIds,
      selectedMeterKeys,
      meters,
      telemetry.cadenceAuthority,
      telemetry.historySamples,
      telemetry.historyWindow,
      telemetry.selectedMetrics,
      telemetry.status,
    ],
  );
  // The clock only flips silent series to stale; it never rebuilds the scene (#1677).
  const [clockMs, setClockMs] = useState(() => Date.now());
  useEffect(() => {
    const timer = globalThis.setInterval(() => setClockMs(Date.now()), 5_000);
    return () => globalThis.clearInterval(timer);
  }, []);
  const clockedSeries = useMemo(
    () => flipExpiredSeries(baseScene.series, clockMs),
    [baseScene.series, clockMs],
  );
  const alertEvents = useDashboardAlertEvents({
    enabled: baseScene.series.length > 0,
    rangeKey: `energy:${rangeIdentity}`,
  });
  // A fixed period ends at its own `to`: open alerts extend to the end of the shown window, not to now.
  const fixedWindowEndMs = customWindow ? Date.parse(customWindow.to) : Number.NaN;
  const annotationNowMs = Number.isFinite(fixedWindowEndMs) ? fixedWindowEndMs : clockMs;
  const scene = useMemo(
    () => ({
      ...baseScene,
      xDomain: viewportDomain ?? baseScene.xDomain,
      series: clockedSeries.map((series) => {
        const key = chartSeriesKey(series.identity);
        return { ...series, visible: soloSeriesKey ? soloSeriesKey === key : !hiddenSeriesKeys.has(key) };
      }),
    }),
    [baseScene, clockedSeries, hiddenSeriesKeys, soloSeriesKey, viewportDomain],
  );
  const panels = useMemo(
    () => partitionChartSeriesByAxisBudget(scene.series, axisBudget),
    [axisBudget, scene.series],
  );
  const inspection = useMemo(
    () => (sharedCursorMs === null ? null : inspectChartAtTimestamp(scene, sharedCursorMs)),
    [scene, sharedCursorMs],
  );
  // Exact statistics come from raw measurements, never from the reduced chart series (#1675).
  const statisticsRows = useMemo(
    () =>
      scene.series
        .filter((series) => series.visible)
        .map((series) => ({
          seriesKey: chartSeriesKey(series.identity),
          color: series.colorToken,
          name: series.name,
          unit: displayUnit(series.identity.nativeUnit),
          statistics:
            telemetry.intervalStatistics?.(
              energySeriesStatisticsKey(series.identity),
              series.identity.metric,
              scene.xDomain.fromMs,
              scene.xDomain.toMs,
            ) ?? null,
        })),
    // historySamples changes whenever raw history or live tail is recorded.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [scene, telemetry.intervalStatistics, telemetry.historySamples],
  );
  const statisticsUnavailable = statisticsRows.some((row) => row.statistics === null);

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
  }, [rangeIdentity]);
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

  const annotationsFor = (series: ChartSeries[], xDomain: ChartXDomain) => {
    const annotated = applyAlertAnnotations({ series, xDomain }, alertEvents.alerts, annotationNowMs);
    return annotated.events || annotated.thresholds || annotated.alarmRegions
      ? {
          events: annotated.events,
          thresholds: annotated.thresholds,
          alarmRegions: annotated.alarmRegions,
        }
      : undefined;
  };
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
          range={rangeLabel}
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
          annotations={annotationsFor(series, scene.xDomain)}
        />
      ))}
      <DashboardAlertEvents
        events={panels.flatMap((series) => annotationsFor(series, scene.xDomain)?.events ?? [])}
        status={alertEvents.status}
        message={alertEvents.message}
        displayTimeZone={displayTimeZone}
      />
      {statisticsRows.length > 0 ? (
        <>
          {statisticsUnavailable ? (
            <div
              role="status"
              data-testid="energy-statistics-unavailable"
              className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber-300/25 bg-amber-300/[0.06] px-4 py-3 text-xs text-amber-100"
            >
              <span>
                Точна статистика недоступна: історія взята з кешу або для цього інтервалу немає повного набору
                вимірювань. Оновіть історію — статистика ніколи не рахується зі стиснутих точок графіка.
              </span>
              <button
                type="button"
                onClick={telemetry.retryHistory}
                className="min-h-9 rounded-xl border border-amber-200/30 px-3 text-xs font-medium hover:bg-amber-200/10"
              >
                Оновити історію
              </button>
            </div>
          ) : null}
          <DashboardIntervalStatistics
            rows={statisticsRows.filter((row) => row.statistics !== null)}
            fromMs={scene.xDomain.fromMs}
            toMs={scene.xDomain.toMs}
            isViewport={viewportDomain !== null}
            displayTimeZone={displayTimeZone}
          />
        </>
      ) : null}
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
  annotations,
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
  /** Canonical alert markers/regions/thresholds for this panel's series (#1677). */
  annotations?: Pick<ChartRendererScene, "events" | "thresholds" | "alarmRegions">;
}) {
  const adapter = useMemo(() => new EChartsRendererAdapter(), []);
  useEffect(() => {
    adapter.resetZoom();
  }, [adapter, resetRevision]);
  const scene = useMemo(() => ({ series, xDomain, ...annotations }), [annotations, series, xDomain]);
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
      onExportImage={() => void downloadChartPng(adapter, title)}
      context={`${units || "Параметри"} · Збережена історія`}
      selectedRange={range}
      series={series}
      requestedWindow={interactionDomain}
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
