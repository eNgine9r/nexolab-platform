"use client";

import { Siren } from "lucide-react";

import { alertEventTypeLabel } from "@/features/charts/alert-events";
import type { ChartEventMarker } from "@/features/charts/domain";
import { formatOperationalTimestamp } from "@/features/display-time/format";
import type { DashboardAlertEventsStatus } from "@/features/live-dashboards/use-dashboard-alert-events";

const MAX_ROWS = 50;

const SEVERITY_TEXT: Record<NonNullable<ChartEventMarker["severity"]>, string> = {
  alarm: "Аварія",
  warning: "Попередження",
  info: "Інформація",
};

const STATE_TEXT: Record<string, string> = {
  active: "Активна",
  acknowledged: "Підтверджена",
  resolved: "Відновлена",
  closed: "Закрита",
};

export function DashboardAlertEvents({
  events,
  status,
  message,
  displayTimeZone,
}: {
  events: readonly ChartEventMarker[];
  status: DashboardAlertEventsStatus;
  message: string | null;
  displayTimeZone: string;
}) {
  if (status === "idle") return null;
  const ordered = [...new Map(events.map((event) => [event.id, event])).values()].sort(
    (left, right) => right.timestampMs - left.timestampMs || left.id.localeCompare(right.id),
  );
  const shown = ordered.slice(0, MAX_ROWS);
  return (
    <section
      className="overflow-hidden rounded-3xl border border-white/[0.08] bg-[#091a31]/90"
      aria-labelledby="dashboard-alert-events-title"
      data-testid="dashboard-alert-events"
    >
      <div className="border-b border-white/[0.07] px-5 py-4">
        <div className="flex items-center gap-2">
          <Siren className="h-4 w-4 text-amber-300" aria-hidden="true" />
          <h2 id="dashboard-alert-events-title" className="text-lg font-semibold text-white">
            Події та тривоги на інтервалі
          </h2>
        </div>
        <p className="mt-1 text-xs text-slate-400">
          Лише підтверджені записи журналу тривог для каналів цього графіка (час, джерело, стан). Сам лише
          прапорець alarm у вимірюванні не створює подію.
        </p>
      </div>
      {status === "loading" ? (
        <p className="px-5 py-4 text-sm text-cyan-200" role="status">
          Завантаження журналу тривог…
        </p>
      ) : status === "unavailable" || status === "error" ? (
        <p
          className="px-5 py-4 text-sm text-amber-100"
          role="status"
          data-testid="dashboard-alert-events-note"
        >
          {message}
        </p>
      ) : shown.length === 0 ? (
        <p className="px-5 py-4 text-sm text-slate-400" data-testid="dashboard-alert-events-empty">
          Тривог для цих каналів на вибраному інтервалі немає.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <caption className="sr-only">Журнал тривог для каналів графіка</caption>
            <thead className="bg-[#06142a]/70 text-xs tracking-[0.08em] text-slate-500 uppercase">
              <tr>
                {["Час", "Подія", "Канал", "Серйозність", "Поточний стан", "Джерело"].map((heading) => (
                  <th key={heading} scope="col" className="px-5 py-3 font-medium">
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.06]">
              {shown.map((event) => (
                <tr key={event.id} className="text-slate-300" data-testid="dashboard-alert-event-row">
                  <td className="px-5 py-3 whitespace-nowrap">
                    {formatOperationalTimestamp(event.timestampMs, displayTimeZone)}
                  </td>
                  <td className="px-5 py-3">{alertEventTypeLabel(event.type)}</td>
                  <td className="px-5 py-3">
                    {[event.source.equipmentId, event.source.channelId].filter(Boolean).join(" · ") || "—"}
                  </td>
                  <td className="px-5 py-3">{event.severity ? SEVERITY_TEXT[event.severity] : "—"}</td>
                  <td className="px-5 py-3">
                    {event.status ? (STATE_TEXT[event.status] ?? event.status) : "—"}
                  </td>
                  <td className="px-5 py-3 text-xs text-slate-500">
                    {event.source.entityType} · {event.source.entityId}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {ordered.length > shown.length ? (
            <p className="px-5 py-3 text-xs text-slate-500">
              Показано {shown.length} із {ordered.length} подій.
            </p>
          ) : null}
        </div>
      )}
    </section>
  );
}
