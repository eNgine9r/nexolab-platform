"use client";

import type { ReactNode } from "react";

import { chartSeriesKey, type ChartCursorInspection, type ChartSeries } from "@/features/charts/domain";
import { formatChartValue } from "@/features/charts/format";

function freshnessLabel(state: ChartSeries["freshness"]): string {
  return {
    live: "Live",
    stale: "Stale",
    connecting: "Connecting",
    reconnecting: "Reconnecting",
    offline: "Offline",
  }[state];
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
}) {
  const freshness = series.some((item) => item.freshness === "offline")
    ? "offline"
    : series.some((item) => item.freshness === "stale")
      ? "stale"
      : series.some((item) => item.freshness === "reconnecting")
        ? "reconnecting"
        : series.some((item) => item.freshness === "connecting")
          ? "connecting"
          : "live";
  const inspectionBySeries = new Map(
    (inspection?.series ?? []).map((entry) => [entry.seriesKey, entry] as const),
  );
  const units = [...new Set(series.map((item) => item.identity.nativeUnit))].join(", ");
  const summary = `${title}. Range ${selectedRange}. ${series.length} series. Units ${units || "none"}. State ${freshnessLabel(freshness)}.`;

  return (
    <section className="min-w-0 overflow-hidden rounded-2xl border border-white/[0.08] bg-[#081a32] text-slate-100">
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-white/[0.07] p-4 sm:p-5">
        <div className="min-w-0">
          <p className="text-[10px] tracking-[0.16em] text-cyan-300 uppercase">{context}</p>
          <h2 className="mt-1 truncate text-lg font-semibold text-white">{title}</h2>
          <p className="mt-1 text-xs text-slate-400">
            {selectedRange} · <span className="font-medium">{freshnessLabel(freshness)}</span>
          </p>
        </div>
        <button
          type="button"
          onClick={onResetZoom}
          className="min-h-10 rounded-xl border border-white/10 px-3 text-xs text-slate-200 outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
        >
          Reset zoom
        </button>
      </header>

      <p className="sr-only" data-testid="chart-accessible-summary">
        {summary}
      </p>
      <div className="min-w-0 p-3 sm:p-4">{children}</div>

      <div className="grid items-start gap-3 border-t border-white/[0.07] p-4 [overflow-anchor:none] 2xl:grid-cols-[minmax(0,1fr)_minmax(360px,520px)]">
        <div className="grid min-w-0 gap-2 sm:grid-cols-2" aria-label="Chart legend">
          {series.map((item) => {
            const key = chartSeriesKey(item.identity);
            const inspected = inspectionBySeries.get(key)?.point ?? item.segments.at(-1)?.points.at(-1);
            const legendLabel = [
              item.name,
              `${inspected ? formatChartValue(inspected.value, item.displayPrecision) : "—"} ${item.identity.nativeUnit}`,
              inspected?.quality ?? "unknown",
              freshnessLabel(item.freshness),
            ].join(" · ");
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
                  {legendLabel}
                </span>
                <button
                  type="button"
                  aria-pressed={item.visible}
                  onClick={() => onToggleSeries(key)}
                  className="shrink-0 rounded px-2 py-1 text-[10px] outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                >
                  {item.visible ? "Hide" : "Show"}
                </button>
                <button
                  type="button"
                  onClick={() => onSoloSeries(key)}
                  className="shrink-0 rounded px-2 py-1 text-[10px] outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                >
                  Solo
                </button>
              </div>
            );
          })}
        </div>
        <aside
          className="min-h-44 min-w-0 rounded-xl border border-white/[0.07] bg-[#06142A] p-3 text-xs [overflow-anchor:none]"
          aria-label="Chart inspector"
          data-testid="chart-inspector"
        >
          <div className="flex min-w-0 items-baseline justify-between gap-3">
            <p className="font-medium text-white">Exact inspector</p>
            <p className="min-w-0 truncate text-right text-[10px] tabular-nums text-slate-500">
              {inspection ? new Date(inspection.timestampMs).toISOString() : "—"}
            </p>
          </div>
          <p className="mt-2 min-h-4 text-slate-500">
            {inspection
              ? "Nearest measured sample per visible series. Distant samples remain unavailable."
              : "Move the shared cursor or use keyboard inspection."}
          </p>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[420px] table-fixed border-collapse text-left">
              <thead className="text-[10px] text-slate-500">
                <tr>
                  <th className="w-[30%] pb-1 pr-2 font-medium">Series</th>
                  <th className="w-[24%] pb-1 pr-2 font-medium">Sample time</th>
                  <th className="w-[18%] pb-1 pr-2 font-medium">Value</th>
                  <th className="w-[14%] pb-1 pr-2 font-medium">Quality</th>
                  <th className="w-[14%] pb-1 font-medium">Freshness</th>
                </tr>
              </thead>
              <tbody className="align-top text-slate-300">
                {series
                  .filter((item) => item.visible)
                  .map((item) => {
                    const key = chartSeriesKey(item.identity);
                    const inspected = inspectionBySeries.get(key);
                    const point = inspected?.point ?? null;
                    const sampleTimestamp = point ? new Date(point.timestampMs).toISOString() : "—";
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
                          {freshnessLabel(inspected?.freshness ?? item.freshness)}
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
