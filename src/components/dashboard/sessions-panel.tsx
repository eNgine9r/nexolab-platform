"use client";

import { formatOperationalTimestamp } from "@/features/display-time/format";
import { useDisplayTimeZone } from "@/hooks/use-display-time-zone";

import Link from "next/link";
import { useEffect, useMemo } from "react";
import { AlertTriangle, Clock3, LoaderCircle } from "lucide-react";

import { useSessionListReadModel } from "@/features/test-sessions/use-session-list-read-model";
import type { DashboardKpiValue } from "@/lib/telemetry/dashboard-state";
import { SESSION_STATE_LABELS } from "@/lib/sessions/view-model";

/** One query for the Overview list and its KPI: the read-model cache serves both from one request. */
export const OVERVIEW_SESSION_QUERY = { nodeId: "edge-01", limit: 50 } as const;

export interface ActiveSessionCounts {
  running: number;
  paused: number;
  ready: number;
}

const COUNT_QUERY_LIMIT = 1;

/**
 * #1845 review: exact totals per state from the server (`count` of a state-filtered page is the
 * total match count), not a count of the newest 50 sessions. Three cached one-row queries.
 */
export function useActiveSessionCounts({
  enabled,
  organizationId,
}: {
  enabled: boolean;
  organizationId: string | null;
}): { counts: ActiveSessionCounts | null; failed: boolean } {
  const nodeId = OVERVIEW_SESSION_QUERY.nodeId;
  const running = useSessionListReadModel({
    enabled,
    organizationId,
    query: { nodeId, state: "running", limit: COUNT_QUERY_LIMIT },
  });
  const paused = useSessionListReadModel({
    enabled,
    organizationId,
    query: { nodeId, state: "paused", limit: COUNT_QUERY_LIMIT },
  });
  const ready = useSessionListReadModel({
    enabled,
    organizationId,
    query: { nodeId, state: "ready", limit: COUNT_QUERY_LIMIT },
  });
  const failed = running.error !== null || paused.error !== null || ready.error !== null;
  if (!running.value || !paused.value || !ready.value) return { counts: null, failed };
  return {
    counts: { running: running.value.count, paused: paused.value.count, ready: ready.value.count },
    failed,
  };
}

/**
 * #1845: the "Active sessions" KPI from the session API (it used to say "Session API not
 * connected" next to a running session). Active = running or paused; ready sessions are named
 * separately. Its status badge follows the session API, not telemetry, and a failed refresh is
 * always stated. Unknown stays "—" with the reason, never a guess.
 */
export function activeSessionsKpi<T extends Pick<DashboardKpiValue, "value" | "detail" | "trend">>(
  base: T,
  counts: ActiveSessionCounts | null,
  failed: boolean,
): Omit<T, "value" | "detail" | "trend" | "badge" | "badgeTone"> &
  Pick<DashboardKpiValue, "value" | "detail" | "trend" | "badge" | "badgeTone"> {
  if (counts === null) {
    return {
      ...base,
      value: "—",
      detail: failed ? "Список сесій недоступний" : "Завантаження сесій…",
      trend: "дані не симулюються",
      badge: failed ? "error" : "offline",
      badgeTone: failed ? "error" : "offline",
    };
  }
  return {
    ...base,
    value: String(counts.running + counts.paused),
    detail: `Виконується: ${counts.running} · призупинено: ${counts.paused}`,
    trend: failed
      ? "оновлення не вдалося; останній відомий стан"
      : counts.ready > 0
        ? `готові до запуску: ${counts.ready}`
        : "вузол edge-01",
    badge: failed ? "stale" : "live",
    badgeTone: failed ? "stale" : "live",
  };
}

export function SessionsPanel({ organizationId }: { organizationId: string | null }) {
  const displayTimeZone = useDisplayTimeZone();
  const sessionsModel = useSessionListReadModel({
    organizationId,
    query: OVERVIEW_SESSION_QUERY,
  });
  const sessions = useMemo(
    () =>
      (sessionsModel.value?.items ?? [])
        .filter((item) => item.state === "running" || item.state === "paused" || item.state === "ready")
        .slice(0, 5),
    [sessionsModel.value],
  );

  useEffect(() => {
    const timer = window.setInterval(sessionsModel.retry, 10_000);
    return () => window.clearInterval(timer);
  }, [sessionsModel.retry]);

  if (sessionsModel.status === "loading" && sessionsModel.value === null) {
    return (
      <div className="grid min-h-48 place-items-center">
        <LoaderCircle className="h-5 w-5 animate-spin text-cyan-300" />
      </div>
    );
  }
  if (sessionsModel.error && sessionsModel.value === null) {
    return (
      <div className="m-4 rounded-xl border border-amber-300/15 bg-amber-400/[0.04] p-4 text-[10px] leading-5 text-slate-400">
        <AlertTriangle className="mr-2 inline h-4 w-4 text-amber-300" />
        {sessionsModel.error.message}
        <p className="mt-2 text-[9px] text-slate-600">Демонстраційні сесії не підставляються.</p>
      </div>
    );
  }
  if (sessions.length === 0) {
    return (
      <div className="grid min-h-28 place-items-center px-5 py-4 text-center">
        <div>
          {sessionsModel.error ? (
            <p className="mb-2 text-[9px] text-amber-300">
              Оновлення не вдалося; показано останній відомий стан.
            </p>
          ) : null}
          <p className="text-[11px] font-semibold text-white">Активних сесій немає</p>
          <Link
            href="/sessions/new"
            className="mt-3 inline-flex text-[10px] text-cyan-300 hover:text-cyan-200"
          >
            Створити реальний draft →
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="divide-y divide-white/[0.045] px-4 py-1 sm:px-5">
      {sessionsModel.error ? (
        <div className="py-2 text-[9px] text-amber-300">
          Оновлення не вдалося; показано останній валідний список.
        </div>
      ) : null}
      {sessions.map((session) => (
        <Link key={session.id} href={`/sessions/${session.id}`} className="group block w-full py-3 text-left">
          <div className="flex items-center justify-between gap-3">
            <h3 className="truncate text-[10px] font-medium text-slate-100 transition group-hover:text-cyan-200">
              {session.title}
            </h3>
            <span className="rounded-full border border-cyan-300/10 bg-cyan-400/[0.04] px-2 py-1 text-[8px] text-cyan-300">
              {SESSION_STATE_LABELS[session.state]}
            </span>
          </div>
          <div className="mt-2 flex items-center justify-between text-[8px] text-slate-600">
            <span>
              {session.session_number} · {session.test_object}
            </span>
            <span className="flex items-center gap-1">
              <Clock3 className="h-2.5 w-2.5" />
              {formatOperationalTimestamp(new Date(session.updated_at), displayTimeZone, {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
          </div>
        </Link>
      ))}
    </div>
  );
}
