"use client";

import { clsx } from "clsx";

import { CHART_GRID_INSETS } from "@/features/charts/echarts-adapter";
import {
  laneStateAt,
  type LaneInterval,
  type LaneState,
  type LaneSummary,
} from "@/features/charts/state-lanes";

const STATE_TEXT: Record<LaneState, string> = { on: "ON", off: "OFF", unknown: "Невідомо" };

export function laneStateLabel(state: LaneState | null): string {
  return state === null ? "Немає даних" : STATE_TEXT[state];
}

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

/**
 * One synchronized digital state lane (#1679): ON / OFF / UNKNOWN (hatched + text) / NO DATA (empty,
 * labelled). It uses the chart's left inset so the lane time axis lines up with the plot above it,
 * follows the shared cursor and the visible viewport, and states every state in text — never colour
 * alone.
 */
export function StateLaneRow({
  label,
  onMeaning,
  intervals,
  fromMs,
  toMs,
  cursorMs,
  summary,
}: {
  label: string;
  onMeaning: string;
  intervals: readonly LaneInterval[];
  fromMs: number;
  toMs: number;
  cursorMs: number | null;
  summary?: LaneSummary;
}) {
  const span = Math.max(1, toMs - fromMs);
  const left = (timestampMs: number) =>
    `${((Math.min(Math.max(timestampMs, fromMs), toMs) - fromMs) / span) * 100}%`;
  const observed = cursorMs === null ? undefined : laneStateAt(intervals, cursorMs);
  const total = toMs - fromMs;
  return (
    <div
      className="grid items-center"
      style={{ gridTemplateColumns: `${CHART_GRID_INSETS.left}px minmax(0,1fr)` }}
      data-state-lane={label}
    >
      <div className="min-w-0 pr-1 text-[10px] text-slate-400">
        <span className="block truncate text-slate-200" title={`${label}: ON — ${onMeaning}`}>
          {label}
        </span>
        {cursorMs !== null ? (
          <span className="block truncate text-slate-200" data-testid="state-lane-cursor-state">
            {laneStateLabel(observed ?? null)}
          </span>
        ) : summary && total > 0 ? (
          <span className="block truncate text-slate-500">ON {percent(summary.onMs / total)}</span>
        ) : null}
      </div>
      <div className="relative h-7 overflow-hidden rounded-md bg-[#06142a] ring-1 ring-white/[0.07] ring-inset">
        {intervals.map((interval) => (
          <span
            key={`${interval.fromMs}-${interval.state}`}
            title={`${STATE_TEXT[interval.state]} · ${new Date(interval.fromMs).toISOString()} → ${new Date(interval.toMs).toISOString()}`}
            aria-label={`${label} ${STATE_TEXT[interval.state]}`}
            tabIndex={0}
            className={clsx(
              "absolute inset-y-1 flex min-w-px items-center justify-center overflow-hidden rounded text-[9px] font-semibold text-slate-100 outline-none focus-visible:ring-2 focus-visible:ring-cyan-200",
              interval.state === "unknown"
                ? "border border-dashed border-amber-300/60 bg-[repeating-linear-gradient(135deg,rgba(245,179,1,.22)_0_4px,transparent_4px_8px)]"
                : interval.state === "on"
                  ? "bg-cyan-400/55"
                  : "bg-slate-500/25",
            )}
            style={{ left: left(interval.fromMs), right: `${100 - parseFloat(left(interval.toMs))}%` }}
          >
            <span className="truncate px-1">{STATE_TEXT[interval.state]}</span>
          </span>
        ))}
        {intervals.length === 0 ? (
          <span className="absolute inset-0 grid place-items-center text-[9px] text-slate-400">
            Немає даних
          </span>
        ) : null}
        {cursorMs !== null && cursorMs >= fromMs && cursorMs <= toMs ? (
          <div
            className="pointer-events-none absolute inset-y-0 z-10 border-l border-dashed border-slate-100/75"
            style={{ left: left(cursorMs) }}
            aria-hidden="true"
          />
        ) : null}
      </div>
    </div>
  );
}
