"use client";

import { Eye, EyeOff, Focus } from "lucide-react";
import { memo, useMemo, useState } from "react";

import {
  chartSeriesKey,
  type ChartCursorInspection,
  type ChartPoint,
  type ChartSeries,
} from "@/features/charts/domain";
import { formatChartValue } from "@/features/charts/format";
import { displayUnit } from "@/features/charts/units";

/** Optional grouping of legend rows, e.g. by instrument; `secondary` is shown dimmed (node). */
export interface ChartLegendGroup {
  key: string;
  label: string;
  secondary?: string | null;
}

/** More series than this shows the legend search (#1845/#1878 behavior kept). */
export const CHART_LEGEND_SEARCH_THRESHOLD = 4;

const COPY = {
  uk: {
    legend: "Легенда графіка",
    heading: "Серії",
    cursor: "На курсорі",
    latest: "Останні вимірювання",
    search: "Знайти серію",
    searchPlaceholder: "Прилад або канал",
    noMatches: "Серій за пошуком немає",
    noData: "Немає даних",
    hide: "Приховати",
    show: "Показати",
    solo: "Лише",
    freshness: {
      live: "Актуально",
      stale: "Застаріло",
      invalid: "Немає валідних даних",
      connecting: "Підключення",
      reconnecting: "Перепідключення",
      offline: "Офлайн",
      historical: "Фіксований період",
    },
    quality: {
      valid: "валідне",
      unknown: "невідома якість",
      sensor_error: "помилка датчика",
      communication_error: "немає зв'язку",
    } as Record<string, string>,
  },
  en: {
    legend: "Chart legend",
    heading: "Series",
    cursor: "At cursor",
    latest: "Latest measurements",
    search: "Find series",
    searchPlaceholder: "Instrument or channel",
    noMatches: "No series match",
    noData: "No data",
    hide: "Hide",
    show: "Show",
    solo: "Solo",
    freshness: {
      live: "Live",
      stale: "Stale",
      invalid: "No valid data",
      connecting: "Connecting",
      reconnecting: "Reconnecting",
      offline: "Offline",
      historical: "Fixed period",
    },
    quality: {} as Record<string, string>,
  },
} as const;

/** Freshness states that are shown as visible text next to the value (not only by color). */
const WARNING_FRESHNESS = new Set<ChartSeries["freshness"]>(["stale", "invalid", "offline", "reconnecting"]);

function latestOf(item: ChartSeries): { value: number | null; quality: string } | null {
  if (item.latest)
    return {
      value: item.latest.quality === "valid" ? item.latest.value : null,
      quality: item.latest.quality,
    };
  const plotted = item.segments.at(-1)?.points.at(-1);
  return plotted ? { value: plotted.value, quality: plotted.quality } : null;
}

interface LegendRowModel {
  key: string;
  item: ChartSeries;
  group: ChartLegendGroup | null;
}

/**
 * #1878: the one compact series legend for every NEXOLAB chart (approved Saved Dashboard design).
 * One row per series: color, name, value + unit, Eye/EyeOff and Focus icon controls. Values are the
 * latest measurements, or the nearest measured values at the cursor while inspecting.
 */
export const ChartSeriesLegend = memo(function ChartSeriesLegend({
  series,
  inspection,
  onToggleSeries,
  onSoloSeries,
  groups,
  locale = "uk",
}: {
  series: readonly ChartSeries[];
  inspection: ChartCursorInspection | null;
  onToggleSeries: (seriesKey: string) => void;
  onSoloSeries: (seriesKey: string) => void;
  /** Series key → group. Series without a group are listed without a heading. */
  groups?: ReadonlyMap<string, ChartLegendGroup>;
  locale?: "en" | "uk";
}) {
  const copy = COPY[locale];
  const [search, setSearch] = useState("");
  const query = search.trim().toLowerCase();
  const searchable = series.length > CHART_LEGEND_SEARCH_THRESHOLD;

  const sections = useMemo(() => {
    const ordered = new Map<string, { group: ChartLegendGroup | null; rows: LegendRowModel[] }>();
    for (const item of series) {
      const key = chartSeriesKey(item.identity);
      const group = groups?.get(key) ?? null;
      if (searchable && query) {
        const description =
          `${group?.label ?? ""} ${group?.secondary ?? ""} ${item.name} ${item.identity.nativeUnit}`.toLowerCase();
        if (!description.includes(query)) continue;
      }
      const sectionKey = group ? `g:${group.key}` : "";
      const section = ordered.get(sectionKey);
      if (section) section.rows.push({ key, item, group });
      else ordered.set(sectionKey, { group, rows: [{ key, item, group }] });
    }
    return [...ordered.entries()];
  }, [groups, query, searchable, series]);

  const cursorPoints = useMemo(
    () =>
      inspection
        ? new Map<string, ChartPoint | null>(inspection.series.map((entry) => [entry.seriesKey, entry.point]))
        : null,
    [inspection],
  );

  return (
    <section aria-label={copy.legend} className="min-w-0" data-testid="chart-series-legend">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-medium text-slate-100">{copy.heading}</h3>
        <span className="text-[11px] text-slate-400" data-testid="chart-series-legend-mode">
          {inspection ? copy.cursor : copy.latest}
        </span>
      </div>
      {searchable ? (
        <input
          aria-label={copy.search}
          placeholder={copy.searchPlaceholder}
          type="search"
          value={search}
          onChange={(event) => setSearch(event.currentTarget.value)}
          className="mt-2 min-h-9 w-full rounded-lg border border-white/10 bg-[#06142a] px-2.5 text-xs text-white outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
        />
      ) : null}
      <div className="mt-2 grid max-h-64 gap-3 overflow-y-auto pr-1 [overflow-anchor:none]">
        {sections.map(([sectionKey, section]) => (
          <section key={sectionKey || "ungrouped"} aria-label={section.group?.label} className="min-w-0">
            {section.group ? (
              <p
                className="truncate py-1 text-[11px] font-medium text-slate-300"
                title={section.group.secondary ?? undefined}
              >
                {section.group.label}
                {section.group.secondary ? (
                  <span className="ml-2 text-slate-500">{section.group.secondary}</span>
                ) : null}
              </p>
            ) : null}
            {section.rows.map(({ key, item }) => (
              <LegendRow
                key={key}
                seriesKey={key}
                item={item}
                cursorPoint={cursorPoints ? (cursorPoints.get(key) ?? null) : undefined}
                copy={copy}
                onToggleSeries={onToggleSeries}
                onSoloSeries={onSoloSeries}
              />
            ))}
          </section>
        ))}
        {sections.length === 0 ? <p className="p-2 text-xs text-slate-400">{copy.noMatches}</p> : null}
      </div>
    </section>
  );
});

function LegendRow({
  seriesKey,
  item,
  cursorPoint,
  copy,
  onToggleSeries,
  onSoloSeries,
}: {
  seriesKey: string;
  item: ChartSeries;
  /** `undefined` = no cursor (show latest); `null` = cursor without a measurement for this series. */
  cursorPoint: ChartPoint | null | undefined;
  copy: (typeof COPY)[keyof typeof COPY];
  onToggleSeries: (seriesKey: string) => void;
  onSoloSeries: (seriesKey: string) => void;
}) {
  const unit = displayUnit(item.identity.nativeUnit);
  const latest = cursorPoint === undefined ? latestOf(item) : null;
  const point = cursorPoint === undefined ? latest : cursorPoint;
  const quality = point ? (copy.quality[point.quality] ?? point.quality) : null;
  let value: string;
  if (point && point.value !== null)
    value = `${formatChartValue(point.value, item.displayPrecision)} ${unit}`;
  else if (point) value = quality ?? copy.noData;
  else value = item.visible ? copy.noData : "—";
  const freshness = copy.freshness[item.freshness];
  const warning = WARNING_FRESHNESS.has(item.freshness);
  const details = [item.name, value, quality, freshness].filter(Boolean).join(" · ");
  const Icon = item.visible ? EyeOff : Eye;
  const toggleLabel = `${item.visible ? copy.hide : copy.show} ${item.name}`;
  const soloLabel = `${copy.solo} ${item.name}`;

  return (
    <div
      className="flex min-w-0 items-center gap-1.5 border-t border-white/[0.06] text-xs"
      data-testid="chart-series-legend-row"
      data-series-key={seriesKey}
      title={details}
    >
      <span
        className="h-2 w-2 shrink-0 rounded-full"
        style={{ backgroundColor: item.colorToken }}
        aria-hidden="true"
      />
      <span className={`min-w-0 flex-1 truncate ${item.visible ? "text-slate-200" : "text-slate-500"}`}>
        {item.name}
      </span>
      {warning ? (
        <span className="shrink-0 text-[10px] text-amber-200" data-testid="chart-series-legend-freshness">
          {freshness}
        </span>
      ) : null}
      <span
        className="min-w-[4.5rem] shrink-0 text-right text-[11px] text-slate-300 tabular-nums"
        data-testid="chart-series-legend-value"
      >
        {value}
      </span>
      <span className="sr-only">
        {quality ? ` · ${quality}` : ""} · {freshness}
      </span>
      <button
        type="button"
        aria-label={toggleLabel}
        title={toggleLabel}
        aria-pressed={item.visible}
        onClick={() => onToggleSeries(seriesKey)}
        className="grid size-9 shrink-0 place-items-center rounded text-slate-300 outline-none hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-cyan-300"
      >
        <Icon size={15} aria-hidden="true" />
      </button>
      <button
        type="button"
        aria-label={soloLabel}
        title={soloLabel}
        onClick={() => onSoloSeries(seriesKey)}
        className="grid size-9 shrink-0 place-items-center rounded text-slate-300 outline-none hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-cyan-300"
      >
        <Focus size={15} aria-hidden="true" />
      </button>
    </div>
  );
}
