"use client";

import { BarChart3 } from "lucide-react";

import { formatChartValue } from "@/features/charts/format";
import type { IntervalStatistics } from "@/features/charts/interval-statistics";
import { formatOperationalTimestamp } from "@/features/display-time/format";
import type { DashboardStatisticsRow } from "@/features/live-dashboards/statistics-rows";

function value(number: number | null, unit: string): string {
  return number === null ? "—" : `${formatChartValue(number)} ${unit}`.trim();
}

function coverageText(statistics: IntervalStatistics): string {
  if (statistics.coverageStatus === "no_data") return "Немає даних";
  if (statistics.coverageRatio === null) return "Недостатньо точок для оцінки покриття";
  const percent = `${Math.round(statistics.coverageRatio * 100)}%`;
  return statistics.coverageStatus === "sufficient" ? `Достатнє · ${percent}` : `Недостатнє · ${percent}`;
}

function gapText(statistics: IntervalStatistics): string {
  if (statistics.gaps.count === 0) return "Без прогалин";
  const minutes = Math.max(1, Math.round(statistics.gaps.longestMs / 60_000));
  return `${statistics.gaps.count} прогал. · найдовша ≈${minutes} хв`;
}

function averageCell(statistics: IntervalStatistics | null, unit: string) {
  if (!statistics || statistics.averageStatus === "no_data") return "—";
  if (statistics.averageStatus === "available") return value(statistics.average, unit);
  return (
    <span title="Покриття інтервалу недостатнє для достовірного середнього">— (недостатнє покриття)</span>
  );
}

export function DashboardIntervalStatistics({
  rows,
  fromMs,
  toMs,
  isViewport,
  displayTimeZone,
}: {
  rows: readonly DashboardStatisticsRow[];
  fromMs: number;
  toMs: number;
  isViewport: boolean;
  displayTimeZone: string;
}) {
  if (rows.length === 0) return null;
  const options: Intl.DateTimeFormatOptions = { dateStyle: "short", timeStyle: "medium" };
  const headings = ["Серія", "Мін", "Макс", "Середнє", "Вимірювань", "Покриття", "Прогалини"];
  return (
    <section
      className="overflow-hidden rounded-3xl border border-white/[0.08] bg-[#091a31]/90"
      aria-labelledby="dashboard-interval-statistics-title"
      data-testid="dashboard-interval-statistics"
    >
      <div className="border-b border-white/[0.07] px-5 py-4">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-cyan-300" aria-hidden="true" />
          <h2 id="dashboard-interval-statistics-title" className="text-lg font-semibold text-white">
            Статистика інтервалу
          </h2>
        </div>
        <p className="mt-1 text-xs text-slate-400" data-testid="dashboard-interval-statistics-scope">
          {isViewport ? "Видимий (збільшений) інтервал" : "Весь запитаний інтервал"}:{" "}
          {formatOperationalTimestamp(fromMs, displayTimeZone, options)} —{" "}
          {formatOperationalTimestamp(toMs, displayTimeZone, options)}. Розраховано з усіх збережених
          вимірювань, а не зі стиснутих точок графіка. Лише валідні вимірювання; прогалини та помилки зв’язку
          не вважаються нулем. Середнє не показується за недостатнього покриття.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <caption className="sr-only">Мінімум, максимум, середнє, кількість вимірювань та покриття</caption>
          <thead className="bg-[#06142a]/70 text-xs tracking-[0.08em] text-slate-500 uppercase">
            <tr>
              {headings.map((heading) => (
                <th key={heading} scope="col" className="px-5 py-3 font-medium">
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.06]">
            {rows.map((row) => {
              const stats = row.statistics;
              return (
                <tr key={row.seriesKey} className="text-slate-300" data-testid="dashboard-statistics-row">
                  <th scope="row" className="px-5 py-3 font-medium text-slate-100">
                    <span
                      className="mr-2 inline-block h-2.5 w-2.5 rounded-full align-middle"
                      style={{ backgroundColor: row.color }}
                      aria-hidden="true"
                    />
                    {row.name}
                  </th>
                  <td className="px-5 py-3">{stats ? value(stats.min, row.unit) : "—"}</td>
                  <td className="px-5 py-3">{stats ? value(stats.max, row.unit) : "—"}</td>
                  <td className="px-5 py-3">{averageCell(stats, row.unit)}</td>
                  <td className="px-5 py-3">
                    {stats ? stats.validCount : "—"}
                    {stats && stats.invalidCount > 0 ? (
                      <span className="ml-1 text-xs text-amber-200">(+{stats.invalidCount} з помилкою)</span>
                    ) : null}
                  </td>
                  <td className="px-5 py-3">{stats ? coverageText(stats) : "Немає даних"}</td>
                  <td className="px-5 py-3 text-slate-400">{stats ? gapText(stats) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
