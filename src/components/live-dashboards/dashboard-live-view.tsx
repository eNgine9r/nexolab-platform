"use client";

import { fromZonedInputValue, toZonedInputValue } from "@/features/display-time/zoned-input";
import { formatOperationalTimestamp } from "@/features/display-time/format";
import { useDisplayTimeZone } from "@/hooks/use-display-time-zone";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  CalendarRange,
  Clock3,
  Download,
  Edit3,
  Gauge,
  Radio,
  RefreshCw,
  Signal,
  WifiOff,
} from "lucide-react";

import { DashboardChartPanel } from "@/components/live-dashboards/dashboard-chart-panel";
import { applyFreshnessClock } from "@/features/charts/series-freshness";
import { ChartDensityControl } from "@/components/charts/chart-density-control";
import type { ChartDensityMode, ChartPointBudgetResolution } from "@/features/charts/density";
import { DashboardStateLanes } from "@/components/live-dashboards/dashboard-state-lanes";
import { buildDashboardStateLanes } from "@/features/live-dashboards/state-lanes";
import { DashboardAlertEvents } from "@/components/live-dashboards/dashboard-alert-events";
import { DashboardIntervalStatistics } from "@/components/live-dashboards/dashboard-interval-statistics";
import { useDashboardAlertEvents } from "@/features/live-dashboards/use-dashboard-alert-events";
import { buildDashboardStatisticsRows } from "@/features/live-dashboards/statistics-rows";
import { chartSeriesKey, type ChartXDomain } from "@/features/charts/domain";
import {
  captureViewSettings,
  rangeMatches,
  resolveViewSettings,
  viewportOverlapsWindow,
} from "@/features/live-dashboards/view-settings";
import { XLSX_MEDIA_TYPE, dashboardCsvToXlsx, xlsxFilenameFromCsv } from "@/features/export/dashboard-xlsx";
import { triggerBrowserBlobDownload } from "@/features/live-dashboards/browser-download";
import {
  buildSavedDashboardChartGroups,
  savedDashboardChartIdentity,
} from "@/features/live-dashboards/chart";
import {
  isOperatorEmbracoTemperature,
  savedDashboardChannelLabel,
  savedDashboardDisplaySample,
  savedDashboardSeriesLabel,
} from "@/features/live-dashboards/embraco-series";
import {
  LIVE_DASHBOARD_HISTORY_PRESETS,
  LIVE_DASHBOARD_PRESET_LABELS,
} from "@/features/live-dashboards/history-range";
import type {
  LiveDashboard,
  LiveDashboardTelemetryStatus,
  LiveDashboardViewSettings,
} from "@/features/live-dashboards/types";
import {
  EMPTY_CADENCE_OBSERVATIONS,
  liveFreshnessFor,
  type CadenceObservations,
} from "@/features/live/freshness";
import { liveTelemetryState } from "@/features/live/live-telemetry";
import { dashboardItemIdentity } from "@/features/live-dashboards/model";
import type { LiveDashboardTelemetryModel } from "@/hooks/use-live-dashboard-telemetry";
import { describeHistoryLoadError } from "@/lib/telemetry/history";

function formatValue(series: LiveDashboardTelemetryModel["series"][number]): string {
  const displayed = savedDashboardDisplaySample(series.item, series.latest);
  if (!displayed) return "—";
  const absolute = Math.abs(displayed.value);
  const digits = displayed.operatorDerived ? 1 : absolute >= 100 ? 0 : absolute >= 10 ? 1 : 2;
  return `${new Intl.NumberFormat("uk-UA", { minimumFractionDigits: displayed.operatorDerived ? 1 : 0, maximumFractionDigits: digits }).format(displayed.value)} ${displayed.unit}`;
}

function formatTimestamp(value: string | null, displayTimeZone: string): string {
  if (!value) return "Даних ще немає";
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return "Невідомий час";
  return formatOperationalTimestamp(parsed, displayTimeZone, {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function statusPresentation(status: LiveDashboardTelemetryStatus): {
  label: string;
  detail: string;
  classes: string;
  icon: typeof Radio;
} {
  if (status === "live") {
    return {
      label: "Live",
      detail: "Selected-series WebSocket і persisted snapshots синхронізовані.",
      classes: "border-emerald-300/20 bg-emerald-400/[0.07] text-emerald-100",
      icon: Radio,
    };
  }
  if (status === "connecting") {
    return {
      label: "Підключення",
      detail: "Завантажуються тільки вибрані latest/history series.",
      classes: "border-cyan-300/20 bg-cyan-400/[0.07] text-cyan-100",
      icon: Signal,
    };
  }
  if (status === "reconnecting") {
    return {
      label: "Reconnecting",
      detail: "Останні значення збережено, але нові події тимчасово не підтверджені.",
      classes: "border-amber-300/20 bg-amber-400/[0.07] text-amber-100",
      icon: RefreshCw,
    };
  }
  if (status === "stale") {
    return {
      label: "Застарілі дані",
      detail: "Значення залишаються видимими, але не позначаються як live.",
      classes: "border-amber-300/20 bg-amber-400/[0.07] text-amber-100",
      icon: Clock3,
    };
  }
  if (status === "offline") {
    return {
      label: "Offline",
      detail: "Persisted values збережено. Live delivery зараз недоступна.",
      classes: "border-slate-300/15 bg-slate-400/[0.06] text-slate-200",
      icon: WifiOff,
    };
  }
  return {
    label: status === "forbidden" ? "Доступ заборонено" : "Помилка live delivery",
    detail: "Перевірте локальний API, авторизацію та WebSocket path.",
    classes: "border-red-300/20 bg-red-400/[0.07] text-red-100",
    icon: AlertTriangle,
  };
}

function seriesState(
  series: LiveDashboardTelemetryModel["series"][number],
  cadence: CadenceObservations | undefined,
): string {
  if (!series.latest) return "Немає persisted sample";
  if (savedDashboardDisplaySample(series.item, series.latest)?.operatorDerived) {
    return "Попередня оцінка °C ×0,01 · датчик на дисплеї не підтверджено";
  }
  const freshness = liveFreshnessFor(series.latest, dashboardItemIdentity(series.item), cadence);
  const state = liveTelemetryState(series.latest, undefined, freshness.staleAfterMs);
  if (state === "live") return "Live";
  if (state === "stale") return "Застарілі";
  if (state === "sensor_error") return "Помилка датчика";
  if (state === "communication_error") return "Помилка зв’язку";
  return "Невідомий стан";
}

export function DashboardLiveView({
  dashboard,
  telemetry,
  density,
  densityResolution,
  detailPointsPerSeries,
  onDensityChange,
  canManage,
  onBack,
  onEdit,
  onSaveView,
}: {
  dashboard: LiveDashboard;
  telemetry: LiveDashboardTelemetryModel;
  density: ChartDensityMode;
  densityResolution: ChartPointBudgetResolution;
  /** #1844: points per series of zoomed viewport detail. */
  detailPointsPerSeries?: number;
  onDensityChange: (mode: ChartDensityMode) => void;
  canManage: boolean;
  onBack: () => void;
  onEdit: () => void;
  /** Persists (or with null clears) the saved analysis view of this dashboard (#1666). */
  onSaveView?: (settings: LiveDashboardViewSettings | null) => Promise<void>;
}) {
  const displayTimeZone = useDisplayTimeZone();
  const status = statusPresentation(telemetry.status);
  const StatusIcon = status.icon;
  const [hiddenSeriesKeys, setHiddenSeriesKeys] = useState<Set<string>>(() => new Set());
  const [soloSeriesKey, setSoloSeriesKey] = useState<string | null>(null);
  const [sharedCursorMs, setSharedCursorMs] = useState<number | null>(null);
  const [viewportDomain, setViewportDomain] = useState<ChartXDomain | null>(null);
  const [customOpen, setCustomOpen] = useState(false);
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [customError, setCustomError] = useState<string | null>(null);
  const restoredView = useMemo(
    () => resolveViewSettings(dashboard.view_settings, dashboard.items),
    [dashboard.items, dashboard.view_settings],
  );
  const [pendingRestore, setPendingRestore] = useState<boolean>(restoredView !== null);
  const [viewSaveState, setViewSaveState] = useState<"idle" | "saving" | "saved" | "cleared" | "error">(
    "idle",
  );
  const [viewSaved, setViewSaved] = useState<boolean>(Boolean(dashboard.view_settings));
  const dashboardViewKey = `${dashboard.id}:${dashboard.version}:${telemetry.historyRange.kind}:${telemetry.historyRange.from}:${telemetry.historyRange.to}`;
  const resetDomain = useMemo(
    () => ({
      fromMs: Date.parse(telemetry.historyWindow.from),
      toMs: Date.parse(telemetry.historyWindow.to),
    }),
    [telemetry.historyWindow.from, telemetry.historyWindow.to],
  );
  const effectiveDomain = viewportDomain ?? resetDomain;
  // #1821: a committed zoom/pan shows the original measurements of the visible window (raw
  // columns in the browser, no request); the full range keeps its coarse points.
  const setDetailViewport = telemetry.setDetailViewport;
  useEffect(() => {
    setDetailViewport?.(viewportDomain);
  }, [setDetailViewport, viewportDomain]);
  const alertEvents = useDashboardAlertEvents({
    enabled: dashboard.items.length > 0,
    rangeKey: `${dashboard.id}:${telemetry.historyRange.kind}:${telemetry.historyRange.from}:${telemetry.historyRange.to}`,
  });
  const builtChartGroups = useMemo(
    () =>
      buildSavedDashboardChartGroups({
        dashboardId: dashboard.id,
        series: telemetry.series,
        status: telemetry.status,
        xDomain: effectiveDomain,
        hiddenSeriesKeys,
        soloSeriesKey,
        cadenceObservations: telemetry.cadenceObservations ?? EMPTY_CADENCE_OBSERVATIONS,
        alerts: alertEvents.alerts,
        pointsPerSeries: densityResolution.perSeries,
        detailPointsPerSeries,
      }),
    [
      dashboard.id,
      effectiveDomain,
      hiddenSeriesKeys,
      soloSeriesKey,
      telemetry.cadenceObservations,
      telemetry.series,
      telemetry.status,
      alertEvents.alerts,
      densityResolution.perSeries,
      detailPointsPerSeries,
    ],
  );
  // The clock only flips silent series to stale; it never rebuilds scenes (see series-freshness.ts).
  const chartGroups = useMemo(
    () =>
      telemetry.now === undefined ? builtChartGroups : applyFreshnessClock(builtChartGroups, telemetry.now),
    [builtChartGroups, telemetry.now],
  );
  const statisticsRows = useMemo(
    () =>
      buildDashboardStatisticsRows(
        dashboard.id,
        telemetry.series,
        chartGroups,
        effectiveDomain,
        telemetry.intervalStatistics,
      ),
    [chartGroups, dashboard.id, effectiveDomain, telemetry.intervalStatistics, telemetry.series],
  );
  // Exact statistics state the range they were computed for (a sliding live window answered by the
  // server may be up to 30 s older than the view, P0 charts).
  const statisticsRange = useMemo(() => {
    const computed = statisticsRows.find((row) => row.statistics !== null)?.statistics;
    return computed ? { fromMs: computed.fromMs, toMs: computed.toMs } : effectiveDomain;
  }, [effectiveDomain, statisticsRows]);
  const densityCounts = useMemo(() => {
    const visibleRows = buildDashboardStatisticsRows(
      dashboard.id,
      telemetry.series,
      chartGroups,
      resetDomain,
      telemetry.intervalStatistics,
    );
    if (visibleRows.length === 0 || visibleRows.some((row) => row.statistics === null)) {
      return { displayed: null, available: null };
    }
    const displayed = chartGroups.reduce(
      (total, group) =>
        total +
        group.scene.series
          .filter((entry) => entry.visible)
          .reduce(
            (sum, entry) =>
              sum + entry.segments.reduce((points, segment) => points + segment.points.length, 0),
            0,
          ),
      0,
    );
    const available = visibleRows.reduce((total, row) => total + (row.statistics?.validCount ?? 0), 0);
    return { displayed, available };
  }, [chartGroups, dashboard.id, resetDomain, telemetry.intervalStatistics, telemetry.series]);
  const stateLanes = useMemo(
    () => buildDashboardStateLanes(telemetry.series, telemetry.intervalColumns, effectiveDomain),
    [effectiveDomain, telemetry.intervalColumns, telemetry.series],
  );
  const containsOperatorTemperatures = dashboard.items.some(isOperatorEmbracoTemperature);
  const valueSeries = telemetry.series.filter(
    (item) => item.item.visualization === "value" || item.item.visualization === "gauge",
  );

  useEffect(() => {
    void Promise.resolve().then(() => {
      setHiddenSeriesKeys(new Set());
      setSoloSeriesKey(null);
      setSharedCursorMs(null);
      setViewportDomain(null);
    });
  }, [dashboardViewKey]);

  // Saved analysis view (#1666): re-apply the saved range once, then — after the range has settled and
  // the window is loaded — the hidden series and the zoom (the range change resets both).
  useEffect(() => {
    const range = restoredView?.range;
    if (!range || rangeMatches(range, telemetry.historyRange)) return;
    void Promise.resolve().then(() => {
      if (range.kind === "preset") telemetry.selectHistoryPreset(range.preset);
      else telemetry.applyCustomHistoryRange(range.from, range.to);
    });
    // Mount-only on purpose: the saved view is applied when the dashboard is opened.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!pendingRestore || !restoredView) return;
    if (restoredView.range && !rangeMatches(restoredView.range, telemetry.historyRange)) return;
    if (telemetry.historyStatus !== "ready") return;
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (cancelled) return;
      const hiddenIdentities = new Set(restoredView.hiddenItemIdentities);
      setHiddenSeriesKeys(
        new Set(
          telemetry.series
            .filter((entry) => hiddenIdentities.has(dashboardItemIdentity(entry.item)))
            .map((entry) => chartSeriesKey(savedDashboardChartIdentity(dashboard.id, entry))),
        ),
      );
      if (restoredView.viewport && viewportOverlapsWindow(restoredView.viewport, resetDomain)) {
        setViewportDomain(restoredView.viewport);
      }
      setPendingRestore(false);
    });
    return () => {
      cancelled = true;
    };
  }, [
    dashboard.id,
    pendingRestore,
    resetDomain,
    restoredView,
    telemetry.historyRange,
    telemetry.historyStatus,
    telemetry.series,
  ]);

  const saveView = async (clear: boolean) => {
    if (!onSaveView) return;
    setViewSaveState("saving");
    try {
      if (clear) {
        await onSaveView(null);
        setViewSaved(false);
        setViewSaveState("cleared");
        return;
      }
      const hiddenItemIdentities = telemetry.series
        .filter((entry) =>
          hiddenSeriesKeys.has(chartSeriesKey(savedDashboardChartIdentity(dashboard.id, entry))),
        )
        .map((entry) => dashboardItemIdentity(entry.item));
      await onSaveView(
        captureViewSettings({
          hiddenItemIdentities,
          historyRange: telemetry.historyRange,
          viewport: viewportDomain,
          density,
        }),
      );
      setViewSaved(true);
      setViewSaveState("saved");
    } catch {
      setViewSaveState("error");
    }
  };

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

  const localInputValue = (value: string): string => {
    return toZonedInputValue(Date.parse(value), displayTimeZone);
  };

  const openCustomRange = () => {
    setCustomFrom(localInputValue(telemetry.historyWindow.from));
    setCustomTo(localInputValue(telemetry.historyWindow.to));
    setCustomError(null);
    setCustomOpen(true);
  };

  const applyCustomRange = () => {
    try {
      const fromMs = fromZonedInputValue(customFrom, displayTimeZone);
      const toMs = fromZonedInputValue(customTo, displayTimeZone);
      telemetry.applyCustomHistoryRange(new Date(fromMs ?? Number.NaN), new Date(toMs ?? Number.NaN));
      setCustomError(null);
      setCustomOpen(false);
    } catch (error) {
      setCustomError(error instanceof Error ? error.message : "Некоректний Custom діапазон.");
    }
  };

  const downloadXlsx = async () => {
    try {
      // The workbook is built from the SAME authoritative server export as the CSV.
      const csv = await telemetry.exportCsv();
      const bytes = dashboardCsvToXlsx(await csv.blob.text(), {
        dashboardName: dashboard.name,
        fromIso: telemetry.historyWindow.from,
        toIso: telemetry.historyWindow.to,
        displayTimeZone,
        generatedAt: new Date(),
      });
      triggerBrowserBlobDownload({
        blob: new Blob([bytes as BlobPart], { type: XLSX_MEDIA_TYPE }),
        filename: xlsxFilenameFromCsv(csv.filename),
      });
    } catch {
      // The hook owns the truthful export error state rendered below the controls.
    }
  };

  const downloadCsv = async () => {
    try {
      const download = await telemetry.exportCsv();
      triggerBrowserBlobDownload(download);
    } catch {
      // The hook owns the truthful export error state rendered below the controls.
    }
  };

  return (
    <section className="min-w-0 space-y-5" aria-labelledby="live-dashboard-title">
      <div className="hidden print:block" data-testid="dashboard-print-header">
        <p className="text-lg font-semibold">{dashboard.name} — звіт про вимірювання</p>
        <p className="text-xs">
          Інтервал: {formatOperationalTimestamp(telemetry.historyWindow.from, displayTimeZone)} —{" "}
          {formatOperationalTimestamp(telemetry.historyWindow.to, displayTimeZone)}. Сформовано:{" "}
          {formatOperationalTimestamp(new Date(), displayTimeZone)}. Статистика і таблиці розраховані зі
          збережених вимірювань; графік показує стиснуті точки.
        </p>
      </div>
      <div className="rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <button
              type="button"
              onClick={onBack}
              className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-cyan-200"
            >
              <ArrowLeft className="h-4 w-4" aria-hidden="true" />
              До library
            </button>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <h1 id="live-dashboard-title" className="text-2xl font-semibold text-white sm:text-3xl">
                {dashboard.name}
              </h1>
              <span className="rounded-full border border-white/10 px-2.5 py-1 text-xs text-slate-400">
                v{dashboard.version}
              </span>
            </div>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
              {dashboard.description ?? "Збережений channel-scoped operator workspace."}
            </p>
            <p className="mt-2 text-xs text-slate-500">
              {dashboard.items.length} series · {dashboard.time_window} · display refresh{" "}
              {dashboard.refresh_seconds} с · latest{" "}
              {formatTimestamp(telemetry.lastCapturedAt, displayTimeZone)}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={telemetry.retry}
              className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-slate-300 hover:border-cyan-300/30 focus-visible:ring-2 focus-visible:ring-cyan-300"
            >
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              Перепідключити
            </button>
            {canManage ? (
              <button
                type="button"
                onClick={onEdit}
                className="inline-flex min-h-10 items-center gap-2 rounded-xl bg-blue-500 px-3 text-sm font-medium text-white hover:bg-blue-400 focus-visible:ring-2 focus-visible:ring-cyan-300"
              >
                <Edit3 className="h-4 w-4" aria-hidden="true" />
                Редагувати
              </button>
            ) : null}
          </div>
        </div>
      </div>

      <div className={`flex items-start gap-3 rounded-2xl border p-4 ${status.classes}`} role="status">
        <StatusIcon
          className={`mt-0.5 h-5 w-5 shrink-0 ${telemetry.status === "connecting" ? "animate-pulse" : ""}`}
          aria-hidden="true"
        />
        <div>
          <p className="font-semibold">{status.label}</p>
          <p className="mt-1 text-sm opacity-75">{status.detail}</p>
          {telemetry.error ? <p className="mt-1 text-xs opacity-65">{telemetry.error.message}</p> : null}
        </div>
      </div>

      {containsOperatorTemperatures ? (
        <div
          data-testid="saved-dashboard-operator-temperature-note"
          className="rounded-xl border border-amber-400/25 bg-amber-400/[0.06] px-4 py-3 text-sm text-amber-100"
        >
          Попередня оцінка температур Embraco: signed Modbus raw ×0,01 °C. Попередній коефіцієнт ×0,1
          суперечив показу контролера. Вибір датчика на дисплеї та калібрування ще не підтверджено; вихідні
          raw і якість телеметрії не змінюються.
        </div>
      ) : null}

      {dashboard.items.length === 0 ? (
        <div className="grid min-h-72 place-items-center rounded-3xl border border-dashed border-white/10 bg-[#081a32]/55 p-8 text-center">
          <div>
            <Gauge className="mx-auto h-8 w-8 text-slate-500" aria-hidden="true" />
            <h2 className="mt-3 text-lg font-semibold text-white">Dashboard не містить каналів</h2>
            <p className="mt-2 text-sm text-slate-500">Редагування потрібне до запуску live view.</p>
          </div>
        </div>
      ) : null}

      {valueSeries.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {valueSeries.map((item) => (
            <article
              key={item.item.id}
              className="rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-5"
              data-testid={`saved-dashboard-${item.item.visualization}-card`}
            >
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-semibold tracking-[0.12em] text-slate-500 uppercase">
                  Поточне значення
                </span>
                <span
                  className="h-3 w-3 rounded-full border border-white/20"
                  style={{ backgroundColor: item.item.color ?? "#00C6E0" }}
                  aria-hidden="true"
                />
              </div>
              <h2
                className="mt-3 truncate text-sm font-medium text-slate-300"
                title={`${item.item.channel_id} ${item.item.metric}`}
              >
                {savedDashboardSeriesLabel(item.item)}
              </h2>
              <p className="mt-3 text-3xl font-semibold tracking-tight text-white">{formatValue(item)}</p>
              <p className="mt-3 text-xs text-slate-500">
                {seriesState(item, telemetry.cadenceObservations)}
              </p>
              <p className="mt-1 text-xs text-slate-600">
                {formatTimestamp(item.latest?.captured_at ?? null, displayTimeZone)}
              </p>
              {item.item.visualization === "gauge" ? (
                <p className="mt-3 rounded-xl border border-white/[0.06] bg-[#06142a]/70 p-2 text-[11px] leading-4 text-slate-500">
                  Збережений індикатор показує поточне значення без шкали. У редакторі можна обрати інший тип
                  відображення.
                </p>
              ) : null}
            </article>
          ))}
        </div>
      ) : null}

      {dashboard.items.length > 0 ? (
        <section
          className="rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-4 sm:p-5 print:hidden"
          aria-label="Saved Dashboard history range and export"
        >
          <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <CalendarRange className="h-4 w-4 text-cyan-300" aria-hidden="true" />
                <h2 className="text-sm font-semibold text-white">Persisted history</h2>
              </div>
              <p className="mt-1 text-xs text-slate-500">
                Діапазон графіка та CSV не змінює фізичний polling або збережене визначення Dashboard.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {LIVE_DASHBOARD_HISTORY_PRESETS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => telemetry.selectHistoryPreset(preset)}
                  className={`min-h-9 rounded-xl border px-3 text-xs font-medium transition ${
                    telemetry.historyRange.kind === preset
                      ? "border-cyan-300/35 bg-cyan-400/10 text-cyan-100"
                      : "border-white/10 text-slate-400 hover:border-cyan-300/25 hover:text-slate-200"
                  }`}
                >
                  {LIVE_DASHBOARD_PRESET_LABELS[preset]}
                </button>
              ))}
              <button
                type="button"
                onClick={openCustomRange}
                className={`min-h-9 rounded-xl border px-3 text-xs font-medium transition ${
                  telemetry.historyRange.kind === "custom"
                    ? "border-cyan-300/35 bg-cyan-400/10 text-cyan-100"
                    : "border-white/10 text-slate-400 hover:border-cyan-300/25 hover:text-slate-200"
                }`}
              >
                Власний період
              </button>
              <button
                type="button"
                onClick={() => void downloadCsv()}
                disabled={
                  telemetry.historyStatus === "loading" ||
                  telemetry.exportStatus === "exporting" ||
                  dashboard.items.length === 0
                }
                className="inline-flex min-h-9 items-center gap-2 rounded-xl border border-emerald-300/20 bg-emerald-400/[0.06] px-3 text-xs font-medium text-emerald-100 hover:bg-emerald-400/10 disabled:cursor-not-allowed disabled:opacity-45"
              >
                <Download className="h-4 w-4" aria-hidden="true" />
                {telemetry.exportStatus === "exporting" ? "Експорт…" : "Export CSV"}
              </button>
              <button
                type="button"
                onClick={() => void downloadXlsx()}
                disabled={
                  telemetry.historyStatus === "loading" ||
                  telemetry.exportStatus === "exporting" ||
                  dashboard.items.length === 0
                }
                data-testid="dashboard-export-xlsx"
                className="inline-flex min-h-9 items-center gap-2 rounded-xl border border-emerald-300/20 bg-emerald-400/[0.06] px-3 text-xs font-medium text-emerald-100 hover:bg-emerald-400/10 disabled:cursor-not-allowed disabled:opacity-45"
              >
                <Download className="h-4 w-4" aria-hidden="true" />
                Export XLSX
              </button>
              <button
                type="button"
                onClick={() => globalThis.print()}
                data-testid="dashboard-print-report"
                className="inline-flex min-h-9 items-center gap-2 rounded-xl border border-white/10 px-3 text-xs font-medium text-slate-200 hover:border-cyan-300/25"
              >
                Друк / PDF
              </button>
            </div>
          </div>

          {canManage && onSaveView ? (
            <div
              className="mt-4 flex flex-wrap items-center gap-2"
              data-testid="saved-analysis-view-controls"
            >
              <button
                type="button"
                onClick={() => void saveView(false)}
                disabled={viewSaveState === "saving"}
                className="min-h-9 rounded-xl border border-cyan-300/25 bg-cyan-400/[0.06] px-3 text-xs font-medium text-cyan-100 hover:bg-cyan-400/10 disabled:opacity-50"
              >
                Зберегти вигляд аналізу
              </button>
              {viewSaved ? (
                <button
                  type="button"
                  onClick={() => void saveView(true)}
                  disabled={viewSaveState === "saving"}
                  className="min-h-9 rounded-xl border border-white/10 px-3 text-xs text-slate-300 hover:border-cyan-300/25 disabled:opacity-50"
                >
                  Скинути збережений вигляд
                </button>
              ) : null}
              <p className="text-xs text-slate-400" role="status" data-testid="saved-analysis-view-status">
                {viewSaveState === "saving"
                  ? "Збереження…"
                  : viewSaveState === "saved"
                    ? "Вигляд збережено: сховані серії, період, масштаб і деталізація відновляться при відкритті."
                    : viewSaveState === "cleared"
                      ? "Збережений вигляд скинуто."
                      : viewSaveState === "error"
                        ? "Не вдалося зберегти вигляд (можливий конфлікт версій або немає прав)."
                        : viewSaved
                          ? "Збережений вигляд застосовується при відкритті."
                          : "Вигляд ще не збережено."}
              </p>
            </div>
          ) : null}

          <div className="mt-4">
            <ChartDensityControl
              mode={density}
              resolution={densityResolution}
              onChange={onDensityChange}
              displayedPoints={densityCounts.displayed}
              availableMeasurements={densityCounts.available}
            />
          </div>

          {customOpen ? (
            <div className="mt-4 grid gap-3 rounded-2xl border border-white/[0.07] bg-[#06142a]/70 p-4 md:grid-cols-[1fr_1fr_auto] md:items-end">
              <label className="grid gap-1.5 text-xs text-slate-400">
                Від · локальний час
                <input
                  type="datetime-local"
                  value={customFrom}
                  onChange={(event) => setCustomFrom(event.target.value)}
                  className="min-h-10 rounded-xl border border-white/10 bg-[#081a32] px-3 text-sm text-slate-100 outline-none focus:border-cyan-300/35"
                />
              </label>
              <label className="grid gap-1.5 text-xs text-slate-400">
                До · локальний час
                <input
                  type="datetime-local"
                  value={customTo}
                  onChange={(event) => setCustomTo(event.target.value)}
                  className="min-h-10 rounded-xl border border-white/10 bg-[#081a32] px-3 text-sm text-slate-100 outline-none focus:border-cyan-300/35"
                />
              </label>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={applyCustomRange}
                  className="min-h-10 rounded-xl bg-blue-500 px-4 text-sm font-medium text-white hover:bg-blue-400"
                >
                  Apply
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setCustomOpen(false);
                    setCustomError(null);
                  }}
                  className="min-h-10 rounded-xl border border-white/10 px-4 text-sm text-slate-400 hover:text-slate-200"
                >
                  Cancel
                </button>
              </div>
              {customError ? <p className="text-xs text-red-200 md:col-span-3">{customError}</p> : null}
            </div>
          ) : null}

          {telemetry.historyStatus === "loading" ? (
            <p
              className="mt-3 text-xs text-cyan-200"
              role="status"
              aria-live="polite"
              data-testid="saved-dashboard-history-progress"
            >
              Завантаження повної persisted history…
              {telemetry.historyProgress
                ? ` Завантажено серій: ${telemetry.historyProgress.loaded} з ${telemetry.historyProgress.total}.`
                : null}
            </p>
          ) : telemetry.historyStatus === "error" ? (
            <p className="mt-3 text-xs text-red-200">{describeHistoryLoadError(telemetry.historyError)}</p>
          ) : null}
          {telemetry.exportError ? (
            <p className="mt-3 text-xs text-red-200">{telemetry.exportError.message}</p>
          ) : null}
        </section>
      ) : null}

      <div
        className="space-y-5"
        data-testid="saved-dashboard-chart-workspace"
        data-history-source={telemetry.historySource ?? "raw"}
        data-viewport-detail={telemetry.viewportDetailPoints ? `${telemetry.viewportDetailPoints}` : "none"}
      >
        {chartGroups.map((group) => (
          <DashboardChartPanel
            key={group.id}
            group={group}
            rangeLabel={telemetry.historyRange.label}
            sharedCursorMs={sharedCursorMs}
            resetDomain={resetDomain}
            onSharedCursorChange={setSharedCursorMs}
            onXDomainChange={(domain) => setViewportDomain(domain)}
            onResetView={() => setViewportDomain(null)}
            onToggleSeries={toggleSeries}
            onSoloSeries={soloSeries}
          />
        ))}
      </div>

      <DashboardIntervalStatistics
        rows={statisticsRows}
        fromMs={statisticsRange.fromMs}
        toMs={statisticsRange.toMs}
        isViewport={viewportDomain !== null}
        displayTimeZone={displayTimeZone}
      />

      <DashboardStateLanes
        lanes={stateLanes}
        fromMs={effectiveDomain.fromMs}
        toMs={effectiveDomain.toMs}
        cursorMs={sharedCursorMs}
      />

      <DashboardAlertEvents
        events={chartGroups.flatMap((group) => group.scene.events ?? [])}
        status={alertEvents.status}
        message={alertEvents.message}
        displayTimeZone={displayTimeZone}
      />

      <section className="overflow-hidden rounded-3xl border border-white/[0.08] bg-[#091a31]/90">
        <div className="border-b border-white/[0.07] px-5 py-4">
          <h2 className="text-lg font-semibold text-white">Latest selected channels</h2>
          <p className="mt-1 text-xs text-slate-500">
            Кожен рядок відповідає збереженому item; універсальний inventory не запитується.
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-[#06142a]/70 text-xs tracking-[0.08em] text-slate-500 uppercase">
              <tr>
                <th className="px-5 py-3 font-medium">Канал</th>
                <th className="px-5 py-3 font-medium">Показник</th>
                <th className="px-5 py-3 font-medium">Значення</th>
                <th className="px-5 py-3 font-medium">Стан</th>
                <th className="px-5 py-3 font-medium">Captured at</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.06]">
              {telemetry.series.map((item) => (
                <tr key={item.item.id} className="text-slate-300">
                  <td className="px-5 py-3 font-medium text-slate-100">
                    {savedDashboardChannelLabel(item.item)}
                  </td>
                  <td className="px-5 py-3">{item.item.metric}</td>
                  <td className="px-5 py-3 font-semibold text-white">{formatValue(item)}</td>
                  <td className="px-5 py-3">{seriesState(item, telemetry.cadenceObservations)}</td>
                  <td className="px-5 py-3 text-slate-500">
                    {formatTimestamp(item.latest?.captured_at ?? null, displayTimeZone)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}
