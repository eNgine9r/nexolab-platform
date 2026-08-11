"use client";

import type { ReactNode } from "react";

import { chartSeriesKey, type ChartCursorInspection, type ChartSeries } from "@/features/charts/domain";

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
  const inspectedSeries = inspection
    ? series.find((item) => chartSeriesKey(item.identity) === inspection.seriesKey)
    : undefined;
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

      <div className="grid gap-3 border-t border-white/[0.07] p-4 lg:grid-cols-[minmax(0,1fr)_minmax(220px,320px)]">
        <div className="flex min-w-0 flex-wrap gap-2" aria-label="Chart legend">
          {series.map((item) => {
            const key = chartSeriesKey(item.identity);
            const inspected =
              inspection?.seriesKey === key ? inspection.point : item.segments.at(-1)?.points.at(-1);
            return (
              <div
                key={key}
                className="flex min-h-10 items-center gap-2 rounded-xl border border-white/[0.08] px-3 py-2"
              >
                <span
                  className="h-3 w-3 shrink-0 rounded-full border border-white/40"
                  style={{ backgroundColor: item.colorToken }}
                  aria-hidden="true"
                />
                <span className="text-xs">
                  {item.name} · {inspected ? inspected.value.toFixed(2) : "—"} {item.identity.nativeUnit} ·{" "}
                  {inspected?.quality ?? "unknown"} · {freshnessLabel(item.freshness)}
                </span>
                <button
                  type="button"
                  aria-pressed={item.visible}
                  onClick={() => onToggleSeries(key)}
                  className="rounded px-2 py-1 text-[10px] outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                >
                  {item.visible ? "Hide" : "Show"}
                </button>
                <button
                  type="button"
                  onClick={() => onSoloSeries(key)}
                  className="rounded px-2 py-1 text-[10px] outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                >
                  Solo
                </button>
              </div>
            );
          })}
        </div>
        <aside
          className="rounded-xl border border-white/[0.07] bg-[#06142A] p-3 text-xs"
          aria-label="Chart inspector"
        >
          <p className="font-medium text-white">Exact inspector</p>
          {inspection?.point ? (
            <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-slate-300">
              <dt>Timestamp</dt>
              <dd>{new Date(inspection.point.timestampMs).toISOString()}</dd>
              <dt>Series</dt>
              <dd>{inspectedSeries?.name ?? inspection.seriesKey}</dd>
              <dt>Value</dt>
              <dd>
                {inspection.point.value} {inspectedSeries?.identity.nativeUnit ?? ""}
              </dd>
              <dt>Quality</dt>
              <dd>{inspection.point.quality}</dd>
              <dt>Freshness</dt>
              <dd>{freshnessLabel(inspection.freshness)}</dd>
            </dl>
          ) : (
            <p className="mt-2 text-slate-500">Move the shared cursor or use keyboard inspection.</p>
          )}
        </aside>
      </div>
    </section>
  );
}
