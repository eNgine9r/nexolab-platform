"use client";

import type { ReactNode } from "react";

import { chartSeriesKey, type ChartCursorInspection, type ChartSeries } from "@/features/charts/domain";
import { formatChartExactTimestamp, formatChartValue } from "@/features/charts/format";
import { buildChartYAxisModel } from "@/features/charts/units";

function freshnessLabel(state: ChartSeries["freshness"], locale: "en" | "uk" = "en"): string {
  const labels =
    locale === "uk"
      ? {
          live: "Актуально",
          stale: "Застаріло",
          connecting: "Підключення",
          reconnecting: "Перепідключення",
          offline: "Офлайн",
        }
      : {
          live: "Live",
          stale: "Stale",
          connecting: "Connecting",
          reconnecting: "Reconnecting",
          offline: "Offline",
        };
  return labels[state];
}

export function ChartShell({
  title,
  context,
  selectedRange,
  series,
  inspection,
  children,
  onToggleSeries,
  onSoloSeries,
  onResetZoom,
  formatTimestamp = formatChartExactTimestamp,
  locale = "en",
}: {
  title: string;
  context: string;
  selectedRange: string;
  series: readonly ChartSeries[];
  inspection: ChartCursorInspection | null;
  children: ReactNode;
  onToggleSeries: (seriesKey: string) => void;
  onSoloSeries: (seriesKey: string) => void;
  onResetZoom: () => void;
  formatTimestamp?: (timestampMs: number) => string;
  locale?: "en" | "uk";
}) {
  const visibleSeries = series.filter((item) => item.visible);
  const freshnessSeries = visibleSeries.length > 0 ? visibleSeries : series;
  const freshness = freshnessSeries.some((item) => item.freshness === "offline")
    ? "offline"
    : freshnessSeries.some((item) => item.freshness === "stale")
      ? "stale"
      : freshnessSeries.some((item) => item.freshness === "reconnecting")
        ? "reconnecting"
        : freshnessSeries.some((item) => item.freshness === "connecting")
          ? "connecting"
          : "live";
  const inspectionBySeries = new Map(
    (inspection?.series ?? []).map((entry) => [entry.seriesKey, entry] as const),
  );
  const visibleAxes = buildChartYAxisModel(series).visibleAxes;
  const units = [...new Set(visibleAxes.map((axis) => axis.nativeUnit))].join(", ");
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
        }
      : {
          resetZoom: "Reset zoom",
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
        };

  return (
    <section className="min-w-0 overflow-hidden rounded-2xl border border-white/[0.08] bg-[#081a32] text-slate-100">
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-white/[0.07] p-4 sm:p-5">
        <div className="min-w-0">
          <p className="text-[10px] tracking-[0.16em] text-cyan-300 uppercase">{context}</p>
          <h2 className="mt-1 truncate text-lg font-semibold text-white">{title}</h2>
          <p className="mt-1 text-xs text-slate-400">
            {selectedRange} · <span className="font-medium">{freshnessLabel(freshness, locale)}</span>
          </p>
        </div>
        <button
          type="button"
          onClick={onResetZoom}
          className="min-h-10 rounded-xl border border-white/10 px-3 text-xs text-slate-200 outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
        >
          {copy.resetZoom}
        </button>
      </header>

      <p className="sr-only" data-testid="chart-accessible-summary">
        {summary}
      </p>
      <div className="min-w-0 p-3 sm:p-4">{children}</div>

      <div className="grid items-start gap-3 border-t border-white/[0.07] p-4 [overflow-anchor:none] 2xl:grid-cols-[minmax(0,1fr)_minmax(360px,520px)]">
        <div className="grid min-w-0 gap-2 sm:grid-cols-2" aria-label={copy.legend}>
          {series.map((item) => {
            const key = chartSeriesKey(item.identity);
            const latest = item.segments.at(-1)?.points.at(-1);
            const latestValue = `${latest ? formatChartValue(latest.value, item.displayPrecision) : "—"} ${item.identity.nativeUnit}`;
            const quality = latest?.quality ?? "unknown";
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
              {inspection ? formatTimestamp(inspection.timestampMs) : "—"}
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
                  const sampleTimestamp = point ? formatTimestamp(point.timestampMs) : "—";
                  const value = point
                    ? `${formatChartValue(point.value, item.displayPrecision)} ${item.identity.nativeUnit}`
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
                      <td className="min-w-0 truncate py-1.5 pr-2">{point?.quality ?? "—"}</td>
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
  );
}
