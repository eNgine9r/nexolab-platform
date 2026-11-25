"use client";

import { useId } from "react";

import {
  CHART_DENSITY_MODES,
  chartDensityLabel,
  isChartDensityMode,
  type ChartDensityMode,
  type ChartPointBudgetResolution,
} from "@/features/charts/density";

function count(value: number): string {
  return value.toLocaleString("uk-UA");
}

/**
 * «Деталізація / точок на лінію» (#1620). A maximum rendered-points budget per series — not the
 * number of stored measurements and never a change of acquisition. The truth-in-presentation
 * line states how many points are drawn against how many measurements are available, and when
 * the aggregate cap lowered the request.
 */
export function ChartDensityControl({
  mode,
  resolution,
  onChange,
  displayedPoints,
  availableMeasurements,
}: {
  mode: ChartDensityMode;
  resolution: ChartPointBudgetResolution;
  onChange: (mode: ChartDensityMode) => void;
  /** Points currently drawn across the visible series; null when unknown. */
  displayedPoints: number | null;
  /** Authoritative valid measurements in the requested interval; null when unknown. */
  availableMeasurements: number | null;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5" data-testid="chart-density-control">
      <label htmlFor={id} className="text-xs font-medium text-slate-300">
        Деталізація / точок на лінію
      </label>
      <select
        id={id}
        value={String(mode)}
        onChange={(event) => {
          const raw = event.target.value;
          const next: unknown = raw === "auto" ? "auto" : Number(raw);
          if (isChartDensityMode(next)) onChange(next);
        }}
        className="min-h-9 rounded-xl border border-white/10 bg-[#081a32] px-3 text-xs text-slate-100 outline-none focus:border-cyan-300/35"
      >
        {CHART_DENSITY_MODES.map((option) => (
          <option key={String(option)} value={String(option)}>
            {chartDensityLabel(option)}
          </option>
        ))}
      </select>
      <p
        className="text-[11px] leading-4 text-slate-400"
        aria-live="polite"
        data-testid="chart-density-status"
      >
        Максимум {count(resolution.perSeries)} точок на серію
        {displayedPoints !== null && availableMeasurements !== null
          ? ` · показано ${count(displayedPoints)} із ${count(availableMeasurements)} вимірювань`
          : ""}
        .
        {resolution.capped
          ? ` Режим ${count(resolution.requested)} обмежено сумарним лімітом точок для кількох серій.`
          : ""}
      </p>
    </div>
  );
}
