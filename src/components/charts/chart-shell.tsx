"use client";

import { useCallback, useMemo, useState, type ReactNode } from "react";
import { useDisplayTimeZone } from "@/hooks/use-display-time-zone";

import { chartSeriesKey, type ChartCursorInspection, type ChartSeries } from "@/features/charts/domain";
import { formatChartExactTimestamp, formatChartValue } from "@/features/charts/format";
import { assessHistoryCoverage } from "@/features/charts/history-coverage";
import { buildChartYAxisModel, displayUnit } from "@/features/charts/units";
import {
  DEFAULT_CHART_Y_SCALE,
  type ChartManualYBounds,
  type ChartYScale,
  type ChartYScaleMode,
} from "@/features/charts/y-axis-bounds";

import { ChartViewContext, type ChartViewContextValue } from "./chart-view-context";

/** Compact duration of a visible window, e.g. "1 год 10 хв", "3 дн 4 год". */
export function formatChartWindowDuration(durationMs: number, locale: "en" | "uk" = "uk"): string {
  const units =
    locale === "uk"
      ? ([
          ["дн", 86_400_000],
          ["год", 3_600_000],
          ["хв", 60_000],
          ["с", 1_000],
        ] as const)
      : ([
          ["d", 86_400_000],
          ["h", 3_600_000],
          ["min", 60_000],
          ["s", 1_000],
        ] as const);
  let remaining = Math.max(0, Math.round(durationMs / 1_000) * 1_000);
  const parts: string[] = [];
  for (const [label, size] of units) {
    const count = Math.floor(remaining / size);
    if (count > 0 && parts.length < 2) parts.push(`${count} ${label}`);
    remaining -= count * size;
    if (parts.length > 0 && count === 0) break;
  }
  return parts.join(" ") || `0 ${units[3][0]}`;
}

interface ReportedWindow {
  visible: { fromMs: number; toMs: number };
  full: { fromMs: number; toMs: number };
}

function freshnessLabel(state: ChartSeries["freshness"], locale: "en" | "uk" = "en"): string {
  const labels =
    locale === "uk"
      ? {
          live: "Актуально",
          stale: "Застаріло",
          invalid: "Немає валідних даних",
          connecting: "Підключення",
          reconnecting: "Перепідключення",
          offline: "Офлайн",
          historical: "Фіксований період",
        }
      : {
          live: "Live",
          stale: "Stale",
          invalid: "No valid data",
          connecting: "Connecting",
          reconnecting: "Reconnecting",
          offline: "Offline",
          historical: "Fixed period",
        };
  return labels[state];
}

function qualityLabel(quality: string, locale: "en" | "uk"): string {
  if (locale !== "uk") return quality;
  const labels: Record<string, string> = {
    valid: "валідне",
    unknown: "невідома якість",
    sensor_error: "помилка датчика",
    communication_error: "немає зв'язку",
  };
  return labels[quality] ?? quality;
}

function latestOf(item: ChartSeries): { value: number | null; quality: string } | null {
  if (item.latest)
    return {
      value: item.latest.quality === "valid" ? item.latest.value : null,
      quality: item.latest.quality,
    };
  const plotted = item.segments.at(-1)?.points.at(-1);
  return plotted ? { value: plotted.value, quality: plotted.quality } : null;
}

export function ChartShell({
  title,
  context,
  selectedRange,
  series,
  inspection,
  children,
  legend,
  onToggleSeries,
  onSoloSeries,
  onResetZoom,
  onExportImage,
  formatTimestamp,
  locale = "en",
  requestedWindow,
}: {
  title: string;
  context: string;
  selectedRange: string;
  series: readonly ChartSeries[];
  inspection: ChartCursorInspection | null;
  children: ReactNode;
  legend?: ReactNode;
  onToggleSeries: (seriesKey: string) => void;
  onSoloSeries: (seriesKey: string) => void;
  onResetZoom: () => void;
  /** When provided, shows a button that saves the visible plot as PNG (local renderer only). */
  onExportImage?: () => void;
  formatTimestamp?: (timestampMs: number) => string;
  locale?: "en" | "uk";
  /** The requested time window; enables the "history starts later than requested" notice. */
  requestedWindow?: { fromMs: number; toMs: number };
}) {
  const displayTimeZone = useDisplayTimeZone();
  const [yScale, setYScale] = useState<ChartYScale>(DEFAULT_CHART_Y_SCALE);
  const [reportedWindow, setReportedWindow] = useState<ReportedWindow | null>(null);
  const reportVisibleDomain = useCallback<ChartViewContextValue["reportVisibleDomain"]>((visible, full) => {
    setReportedWindow((previous) =>
      previous &&
      previous.visible.fromMs === visible.fromMs &&
      previous.visible.toMs === visible.toMs &&
      previous.full.fromMs === full.fromMs &&
      previous.full.toMs === full.toMs
        ? previous
        : { visible, full },
    );
  }, []);
  const viewContext = useMemo(() => ({ yScale, reportVisibleDomain }), [reportVisibleDomain, yScale]);
  const timestampFormatter =
    formatTimestamp ??
    ((timestampMs: number) => formatChartExactTimestamp(timestampMs, { timeZone: displayTimeZone }));
  const visibleSeries = series.filter((item) => item.visible);
  const freshnessSeries = visibleSeries.length > 0 ? visibleSeries : series;
  const freshness = freshnessSeries.some((item) => item.freshness === "offline")
    ? "offline"
    : freshnessSeries.some((item) => item.freshness === "stale")
      ? "stale"
      : freshnessSeries.some((item) => item.freshness === "invalid")
        ? "invalid"
        : freshnessSeries.some((item) => item.freshness === "reconnecting")
          ? "reconnecting"
          : freshnessSeries.some((item) => item.freshness === "connecting")
            ? "connecting"
            : freshnessSeries.some((item) => item.freshness === "historical")
              ? "historical"
              : "live";
  const inspectionBySeries = new Map(
    (inspection?.series ?? []).map((entry) => [entry.seriesKey, entry] as const),
  );
  const visibleAxes = buildChartYAxisModel(series).visibleAxes;
  // #1843: name the interval actually shown once the operator zoomed or panned.
  const zoomedWindow =
    reportedWindow &&
    (Math.abs(reportedWindow.visible.fromMs - reportedWindow.full.fromMs) > 1_000 ||
      Math.abs(reportedWindow.visible.toMs - reportedWindow.full.toMs) > 1_000)
      ? reportedWindow.visible
      : null;
  const setYMode = (mode: ChartYScaleMode) => setYScale((current) => ({ ...current, mode }));
  const setManualBound = (axisId: string, side: keyof ChartManualYBounds, text: string) => {
    const parsed = text.trim() === "" ? undefined : Number(text.replace(",", "."));
    setYScale((current) => ({
      mode: "manual",
      manual: {
        ...current.manual,
        [axisId]: { ...current.manual?.[axisId], [side]: Number.isFinite(parsed) ? parsed : undefined },
      },
    }));
  };
  const units = [...new Set(visibleAxes.map((axis) => displayUnit(axis.nativeUnit)))].join(", ");
  const continuityBreaks = visibleSeries.reduce(
    (total, item) => total + item.segments.filter((segment) => segment.precedingBreak).length,
    0,
  );
  const summary =
    locale === "uk"
      ? `${title}. Період ${selectedRange}. Видимих серій ${visibleSeries.length}. Осей ${visibleAxes.length}. Одиниці ${units || "немає"}. Стан ${freshnessLabel(freshness, locale)}. Розривів безперервності ${continuityBreaks}.`
      : `${title}. Range ${selectedRange}. ${visibleSeries.length} series visible. Axes ${visibleAxes.length}. Units ${units || "none"}. State ${freshnessLabel(freshness, locale)}. Continuity breaks ${continuityBreaks}.`;
  const copy =
    locale === "uk"
      ? {
          resetZoom: "Скинути масштаб",
          exportImage: "Зберегти PNG",
          legend: "Легенда графіка",
          hide: "Приховати",
          show: "Показати",
          solo: "Лише цей",
          inspector: "Інспектор графіка",
          inspectorTitle: "Точні значення",
          inspectorNearest:
            "Найближче виміряне значення для кожної видимої серії. Віддалені точки не підставляються.",
          inspectorEmpty: "Наведіть курсор на графік або використайте клавіатурну навігацію.",
          series: "Серія",
          sampleTime: "Час вимірювання",
          value: "Значення",
          quality: "Якість",
          freshness: "Актуальність",
          noValidPoints: "Немає валідних точок для відображення у вибраному періоді",
          noSamples: "немає збережених вимірювань",
          partialHistory: "Історія доступна не за весь період",
          visibleWindow: "Видимий інтервал",
          yScale: "Шкала Y",
          yAuto: "Авто",
          yAutoHint: "За видимим періодом",
          yFull: "Весь період",
          yFullHint: "За всім вибраним періодом; не змінюється під час масштабування",
          yManual: "Вручну",
          yManualHint: "Задати мінімум і максимум",
          min: "мін",
          max: "макс",
        }
      : {
          resetZoom: "Reset zoom",
          exportImage: "Save PNG",
          legend: "Chart legend",
          hide: "Hide",
          show: "Show",
          solo: "Solo",
          inspector: "Chart inspector",
          inspectorTitle: "Exact inspector",
          inspectorNearest: "Nearest measured sample per visible series. Distant samples remain unavailable.",
          inspectorEmpty: "Move the shared cursor or use keyboard inspection.",
          series: "Series",
          sampleTime: "Sample time",
          value: "Value",
          quality: "Quality",
          freshness: "Freshness",
          noValidPoints: "No valid points to plot in the selected range",
          noSamples: "no persisted samples",
          partialHistory: "History does not cover the whole range",
          visibleWindow: "Visible interval",
          yScale: "Y scale",
          yAuto: "Auto",
          yAutoHint: "Fit the visible period",
          yFull: "Full period",
          yFullHint: "Fit the whole selected period; stays while zooming",
          yManual: "Manual",
          yManualHint: "Set minimum and maximum",
          min: "min",
          max: "max",
        };
  // Series that are visible but have nothing plottable: say why instead of drawing empty axes.
  const emptySeries = visibleSeries.filter((item) =>
    item.segments.every((segment) => segment.points.length === 0),
  );

  const coverage = requestedWindow ? assessHistoryCoverage(series, requestedWindow) : null;
  const coverageDetail =
    coverage?.kind === "partial" && coverage.availableFromMs !== null
      ? locale === "uk"
        ? `Перше збережене вимірювання: ${timestampFormatter(coverage.availableFromMs)}. Покрито ${Math.round(coverage.coverageRatio * 100)}% вибраного періоду; решта — немає даних, а не нулі.`
        : `First stored measurement: ${timestampFormatter(coverage.availableFromMs)}. ${Math.round(coverage.coverageRatio * 100)}% of the range is covered; the rest is no data, not zero.`
      : null;

  return (
    <ChartViewContext.Provider value={viewContext}>
      <section className="min-w-0 overflow-hidden rounded-2xl border border-white/[0.08] bg-[#081a32] text-slate-100">
        <header className="flex flex-wrap items-start justify-between gap-4 border-b border-white/[0.07] p-4 sm:p-5">
          <div className="min-w-0">
            <p className="text-[10px] tracking-[0.16em] text-cyan-300 uppercase">{context}</p>
            <h2 className="mt-1 truncate text-lg font-semibold text-white">{title}</h2>
            <p className="mt-1 text-xs text-slate-400" data-testid="chart-display-timezone">
              Часова зона: {displayTimeZone}
            </p>
            <p className="mt-1 text-xs text-slate-400">
              {selectedRange} · <span className="font-medium">{freshnessLabel(freshness, locale)}</span>
            </p>
            {zoomedWindow ? (
              <p className="mt-1 text-xs text-cyan-100 tabular-nums" data-testid="chart-visible-window">
                {copy.visibleWindow}: {timestampFormatter(zoomedWindow.fromMs)} –{" "}
                {timestampFormatter(zoomedWindow.toMs)} (
                {formatChartWindowDuration(zoomedWindow.toMs - zoomedWindow.fromMs, locale)})
              </p>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div
              role="group"
              aria-label={copy.yScale}
              data-testid="chart-y-scale"
              data-y-scale-mode={yScale.mode}
              className="flex min-h-10 items-center gap-1 rounded-xl border border-white/10 px-1 text-xs"
            >
              <span className="px-1 text-slate-400" aria-hidden="true">
                {copy.yScale}
              </span>
              {(
                [
                  ["auto", copy.yAuto, copy.yAutoHint],
                  ["full", copy.yFull, copy.yFullHint],
                  ["manual", copy.yManual, copy.yManualHint],
                ] as const
              ).map(([mode, label, hint]) => (
                <button
                  key={mode}
                  type="button"
                  aria-pressed={yScale.mode === mode}
                  title={hint}
                  onClick={() => setYMode(mode)}
                  className={`min-h-8 rounded-lg px-2 outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 ${
                    yScale.mode === mode ? "bg-cyan-300/15 text-cyan-100" : "text-slate-300"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            {yScale.mode === "manual"
              ? visibleAxes.map((axis) => {
                  const unit = displayUnit(axis.nativeUnit);
                  const manual = yScale.manual?.[axis.id];
                  return (
                    <div
                      key={axis.id}
                      className="flex min-h-10 items-center gap-1 rounded-xl border border-white/10 px-2 text-xs"
                      data-testid="chart-y-manual"
                    >
                      <span className="text-slate-400">{unit}</span>
                      {(["min", "max"] as const).map((side) => (
                        <label key={side} className="flex items-center gap-1">
                          <span className="text-slate-500">{copy[side]}</span>
                          <input
                            // Text, not number: a Ukrainian decimal comma ("30,5") must be accepted.
                            type="text"
                            inputMode="decimal"
                            pattern="-?[0-9]*([.,][0-9]+)?"
                            aria-label={`${copy[side]} ${unit}`}
                            defaultValue={manual?.[side] ?? ""}
                            onChange={(event) => setManualBound(axis.id, side, event.currentTarget.value)}
                            className="w-16 rounded-md border border-white/10 bg-transparent px-1 py-1 text-slate-100 tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                          />
                        </label>
                      ))}
                    </div>
                  );
                })
              : null}
            {onExportImage ? (
              <button
                type="button"
                onClick={onExportImage}
                data-testid="chart-export-png"
                className="min-h-10 rounded-xl border border-white/10 px-3 text-xs text-slate-200 outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
              >
                {copy.exportImage}
              </button>
            ) : null}
            <button
              type="button"
              onClick={onResetZoom}
              className="min-h-10 rounded-xl border border-white/10 px-3 text-xs text-slate-200 outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
            >
              {copy.resetZoom}
            </button>
          </div>
        </header>

        <p className="sr-only" data-testid="chart-accessible-summary">
          {summary}
        </p>
        <div className="min-w-0 p-3 sm:p-4">
          {emptySeries.length > 0 ? (
            <div
              role="status"
              data-testid="chart-no-valid-points"
              className="mb-3 rounded-xl border border-amber-300/30 bg-amber-300/[0.06] px-3 py-2 text-xs text-amber-100"
            >
              <p className="font-medium">{copy.noValidPoints}</p>
              <ul className="mt-1 space-y-0.5 text-amber-100/80">
                {emptySeries.map((item) => (
                  <li key={chartSeriesKey(item.identity)}>
                    {item.name}: {item.latest ? qualityLabel(item.latest.quality, locale) : copy.noSamples}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {children}
          {coverageDetail ? (
            <div
              role="status"
              data-testid="chart-partial-history"
              className="mt-3 rounded-xl border border-sky-300/30 bg-sky-300/[0.06] px-3 py-2 text-xs text-sky-100"
            >
              <p className="font-medium">{copy.partialHistory}</p>
              <p className="mt-1 text-sky-100/80">{coverageDetail}</p>
            </div>
          ) : null}
        </div>

        <div className="grid items-start gap-3 border-t border-white/[0.07] p-4 [overflow-anchor:none] 2xl:grid-cols-[minmax(0,1fr)_minmax(360px,520px)]">
          <div
            className={legend ? "min-w-0" : "grid min-w-0 gap-2 sm:grid-cols-2"}
            aria-label={legend ? undefined : copy.legend}
          >
            {legend ??
              series.map((item) => {
                const key = chartSeriesKey(item.identity);
                const latest = latestOf(item);
                const latestValue = `${latest && latest.value !== null ? formatChartValue(latest.value, item.displayPrecision) : "—"} ${displayUnit(item.identity.nativeUnit)}`;
                const quality = qualityLabel(latest?.quality ?? "unknown", locale);
                const itemFreshness = freshnessLabel(item.freshness, locale);
                const legendLabel = [item.name, latestValue, quality, itemFreshness].join(" · ");
                return (
                  <div
                    key={key}
                    className="flex min-h-10 min-w-0 items-center gap-2 rounded-xl border border-white/[0.08] px-3 py-2"
                  >
                    <span
                      className="h-3 w-3 shrink-0 rounded-full border border-white/40"
                      style={{ backgroundColor: item.colorToken }}
                      aria-hidden="true"
                    />
                    <span className="min-w-0 flex-1 truncate text-xs tabular-nums" title={legendLabel}>
                      <span>{item.name}</span>
                      <span aria-hidden="true"> · </span>
                      <span>{latestValue}</span>
                      <span aria-hidden="true"> · </span>
                      <span>{quality}</span>
                      <span aria-hidden="true"> · </span>
                      <span>{itemFreshness}</span>
                    </span>
                    <button
                      type="button"
                      aria-pressed={item.visible}
                      onClick={() => onToggleSeries(key)}
                      className="shrink-0 rounded px-2 py-1 text-[10px] outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                    >
                      {item.visible ? copy.hide : copy.show}
                    </button>
                    <button
                      type="button"
                      onClick={() => onSoloSeries(key)}
                      className="shrink-0 rounded px-2 py-1 text-[10px] outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                    >
                      {copy.solo}
                    </button>
                  </div>
                );
              })}
          </div>
          <aside
            className="min-h-44 min-w-0 rounded-xl border border-white/[0.07] bg-[#06142A] p-3 text-xs [overflow-anchor:none]"
            aria-label={copy.inspector}
            data-testid="chart-inspector"
          >
            <div className="flex min-w-0 items-baseline justify-between gap-3">
              <p className="font-medium text-white">{copy.inspectorTitle}</p>
              <p className="min-w-0 truncate text-right text-[10px] text-slate-500 tabular-nums">
                {inspection ? (
                  <time
                    dateTime={new Date(inspection.timestampMs).toISOString()}
                    data-testid="chart-inspector-timestamp"
                  >
                    {timestampFormatter(inspection.timestampMs)}
                  </time>
                ) : (
                  "—"
                )}
              </p>
            </div>
            <p className="mt-2 min-h-4 text-slate-500">
              {inspection ? copy.inspectorNearest : copy.inspectorEmpty}
            </p>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[420px] table-fixed border-collapse text-left">
                <thead className="text-[10px] text-slate-500">
                  <tr>
                    <th className="w-[30%] pr-2 pb-1 font-medium">{copy.series}</th>
                    <th className="w-[24%] pr-2 pb-1 font-medium">{copy.sampleTime}</th>
                    <th className="w-[18%] pr-2 pb-1 font-medium">{copy.value}</th>
                    <th className="w-[14%] pr-2 pb-1 font-medium">{copy.quality}</th>
                    <th className="w-[14%] pb-1 font-medium">{copy.freshness}</th>
                  </tr>
                </thead>
                <tbody className="align-top text-slate-300">
                  {visibleSeries.map((item) => {
                    const key = chartSeriesKey(item.identity);
                    const inspected = inspectionBySeries.get(key);
                    const point = inspected?.point ?? null;
                    const sampleTimestamp = point ? timestampFormatter(point.timestampMs) : "—";
                    const value = point
                      ? `${formatChartValue(point.value, item.displayPrecision)} ${displayUnit(item.identity.nativeUnit)}`
                      : "—";
                    return (
                      <tr key={key} className="border-t border-white/[0.05]">
                        <td className="min-w-0 truncate py-1.5 pr-2" title={item.name}>
                          {item.name}
                        </td>
                        <td className="min-w-0 truncate py-1.5 pr-2 tabular-nums" title={sampleTimestamp}>
                          {sampleTimestamp}
                        </td>
                        <td className="min-w-0 truncate py-1.5 pr-2 tabular-nums">{value}</td>
                        <td className="min-w-0 truncate py-1.5 pr-2">
                          {point ? qualityLabel(point.quality, locale) : "—"}
                        </td>
                        <td className="min-w-0 truncate py-1.5">
                          {freshnessLabel(inspected?.freshness ?? item.freshness, locale)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </aside>
        </div>
      </section>
    </ChartViewContext.Provider>
  );
}
