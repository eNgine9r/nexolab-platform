"use client";

import { StateLaneRow } from "@/components/charts/state-lane-row";
import type { DashboardStateLane } from "@/features/live-dashboards/state-lanes";

export function DashboardStateLanes({
  lanes,
  fromMs,
  toMs,
  cursorMs,
}: {
  lanes: readonly DashboardStateLane[];
  fromMs: number;
  toMs: number;
  cursorMs: number | null;
}) {
  if (lanes.length === 0) return null;
  return (
    <section
      className="rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-4 sm:p-5"
      aria-labelledby="dashboard-state-lanes-title"
      data-testid="dashboard-state-lanes"
    >
      <h2 id="dashboard-state-lanes-title" className="text-lg font-semibold text-white">
        Стани каналів
      </h2>
      <p className="mt-1 text-xs text-slate-400">
        Доріжки синхронізовано з графіком і курсором. Стани беруться зі збережених вимірювань; нічого не
        домислюється.
      </p>
      <ul
        className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-slate-400"
        aria-label="Позначення станів доріжок"
      >
        <li>OFF — вимкнено</li>
        <li>ON — увімкнено</li>
        <li>Невідомо (штрихування) — опитування було, але валідного стану немає</li>
        <li>Немає даних (порожньо) — опитування відсутнє</li>
      </ul>
      <div className="mt-4 grid gap-2" style={{ paddingRight: 0 }}>
        {lanes.map((lane) => (
          <StateLaneRow
            key={lane.key}
            label={lane.label}
            onMeaning={lane.onMeaning}
            intervals={lane.intervals}
            fromMs={fromMs}
            toMs={toMs}
            cursorMs={cursorMs}
            summary={lane.summary}
          />
        ))}
      </div>
    </section>
  );
}
