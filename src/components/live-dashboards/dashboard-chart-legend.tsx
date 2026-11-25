"use client";

import { Eye, EyeOff, Focus } from "lucide-react";
import { useMemo, useState } from "react";

import { chartSeriesKey, type ChartCursorInspection } from "@/features/charts/domain";
import { formatChartValue } from "@/features/charts/format";
import type { SavedDashboardChartGroup } from "@/features/live-dashboards/chart";

export function DashboardChartLegend({
  group,
  inspection,
  onToggleSeries,
  onSoloSeries,
}: {
  group: SavedDashboardChartGroup;
  inspection: ChartCursorInspection | null;
  onToggleSeries: (key: string) => void;
  onSoloSeries: (key: string) => void;
}) {
  const [search, setSearch] = useState("");
  const query = search.trim().toLowerCase();
  const instruments = useMemo(() => {
    const byInstrument = new Map<
      string,
      { label: string; node: string | null; series: SavedDashboardChartGroup["scene"]["series"][number][] }
    >();
    for (const item of group.scene.series) {
      const instrument = group.instruments.get(chartSeriesKey(item.identity));
      if (!instrument) continue;
      const description = `${instrument.label} ${instrument.node ?? ""} ${item.name} ${item.identity.nativeUnit}`;
      if (!description.toLowerCase().includes(query)) continue;
      const previous = byInstrument.get(instrument.key);
      if (previous) previous.series.push(item);
      else
        byInstrument.set(instrument.key, { label: instrument.label, node: instrument.node, series: [item] });
    }
    return byInstrument;
  }, [group.instruments, group.scene.series, query]);
  const points = new Map(inspection?.series.map((entry) => [entry.seriesKey, entry.point]));

  return (
    <section aria-label="Легенда графіка" className="min-w-0" data-testid="saved-dashboard-legend">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-medium text-slate-100">Серії</h3>
        <span className="text-[11px] text-slate-400">
          {inspection ? "На курсорі" : "Останні вимірювання"}
        </span>
      </div>
      {group.scene.series.length > 4 ? (
        <input
          aria-label="Знайти серію"
          placeholder="Прилад або канал"
          type="search"
          value={search}
          onChange={(event) => setSearch(event.currentTarget.value)}
          className="mt-2 min-h-9 w-full rounded-lg border border-white/10 bg-[#06142a] px-2.5 text-xs text-white outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
        />
      ) : null}
      <div className="mt-2 grid max-h-64 gap-3 overflow-y-auto pr-1">
        {[...instruments.entries()].map(([id, instrument]) => (
          <section key={id} aria-label={instrument.label} className="min-w-0">
            <p
              className="truncate py-1 text-[11px] font-medium text-slate-300"
              title={instrument.node ?? undefined}
            >
              {instrument.label}
              {instrument.node ? <span className="ml-2 text-slate-500">{instrument.node}</span> : null}
            </p>
            {instrument.series.map((item) => {
              const key = chartSeriesKey(item.identity);
              const point = inspection ? points.get(key) : item.segments.at(-1)?.points.at(-1);
              const value = point
                ? `${formatChartValue(point.value, item.displayPrecision)} ${item.identity.nativeUnit}`
                : item.visible
                  ? "Немає даних"
                  : "—";
              const Icon = item.visible ? EyeOff : Eye;
              return (
                <div
                  key={key}
                  className="flex min-w-0 items-center gap-1.5 border-t border-white/[0.06] text-xs"
                >
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: item.colorToken }}
                    aria-hidden="true"
                  />
                  <span className="min-w-0 flex-1 truncate text-slate-200" title={item.name}>
                    {item.name}
                  </span>
                  <span className="shrink-0 text-[11px] text-slate-300 tabular-nums">{value}</span>
                  <button
                    type="button"
                    aria-label={item.visible ? `Приховати ${item.name}` : `Показати ${item.name}`}
                    title={item.visible ? `Приховати ${item.name}` : `Показати ${item.name}`}
                    aria-pressed={item.visible}
                    onClick={() => onToggleSeries(key)}
                    className="grid size-9 shrink-0 place-items-center rounded text-slate-300 outline-none hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-cyan-300"
                  >
                    <Icon size={15} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    aria-label={`Лише ${item.name}`}
                    title={`Лише ${item.name}`}
                    onClick={() => onSoloSeries(key)}
                    className="grid size-9 shrink-0 place-items-center rounded text-slate-300 outline-none hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-cyan-300"
                  >
                    <Focus size={15} aria-hidden="true" />
                  </button>
                </div>
              );
            })}
          </section>
        ))}
        {instruments.size === 0 ? <p className="p-2 text-xs text-slate-400">Серій за пошуком немає</p> : null}
      </div>
    </section>
  );
}
