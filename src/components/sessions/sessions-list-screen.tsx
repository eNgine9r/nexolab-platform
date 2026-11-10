"use client";

import { formatOperationalTimestamp } from "@/features/display-time/format";
import { useDisplayTimeZone } from "@/hooks/use-display-time-zone";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Archive,
  ArrowUpRight,
  CheckCircle2,
  CircleDashed,
  Clock3,
  LoaderCircle,
  PauseCircle,
  PlayCircle,
  RefreshCw,
  Search,
  XCircle,
} from "lucide-react";

import { usePlatformAccount } from "@/components/dashboard/platform-account-boundary";
import { createSessionApiClient } from "@/lib/sessions/api-client";
import type { LaboratorySession, SessionState } from "@/lib/sessions/types";
import { SESSION_STATE_LABELS } from "@/lib/sessions/view-model";

const FILTERS: Array<{ value: "all" | SessionState; label: string }> = [
  { value: "all", label: "Усі" },
  { value: "running", label: "Виконуються" },
  { value: "ready", label: "Готові" },
  { value: "paused", label: "Призупинені" },
  { value: "draft", label: "Чернетки" },
  { value: "completed", label: "Завершені" },
  { value: "cancelled", label: "Скасовані" },
  { value: "archived", label: "Архів" },
];

function StateIcon({ state }: { state: SessionState }) {
  if (state === "running") return <PlayCircle className="h-3 w-3" />;
  if (state === "paused") return <PauseCircle className="h-3 w-3" />;
  if (state === "completed") return <CheckCircle2 className="h-3 w-3" />;
  if (state === "archived") return <Archive className="h-3 w-3" />;
  if (state === "cancelled") return <XCircle className="h-3 w-3" />;
  return <CircleDashed className="h-3 w-3" />;
}

function stateClass(state: SessionState): string {
  if (state === "running") return "border-emerald-300/20 bg-emerald-400/[0.06] text-emerald-300";
  if (state === "paused") return "border-amber-300/20 bg-amber-400/[0.06] text-amber-300";
  if (state === "completed") return "border-cyan-300/20 bg-cyan-400/[0.06] text-cyan-300";
  if (state === "cancelled") return "border-red-300/20 bg-red-400/[0.06] text-red-300";
  return "border-slate-400/15 bg-slate-400/[0.05] text-slate-300";
}

function formatDate(value: string, displayTimeZone: string): string {
  return formatOperationalTimestamp(new Date(value), displayTimeZone, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function SessionsListScreen() {
  const displayTimeZone = useDisplayTimeZone();
  const account = usePlatformAccount();
  const organizationId = account?.security.membership?.organizationId;
  const [filter, setFilter] = useState<"all" | SessionState>("all");
  const [query, setQuery] = useState("");
  const [generation, setGeneration] = useState(0);
  const [response, setResponse] = useState<{
    key: string;
    items: LaboratorySession[];
    error: Error | null;
    hasMore: boolean;
  } | null>(null);

  // Only a matching organization/filter/request generation can show results.
  const requestKey = JSON.stringify([organizationId ?? null, filter, generation]);
  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void createSessionApiClient({ organizationId })
        .listSessions(
          { state: filter === "all" ? undefined : filter, nodeId: "edge-01", limit: 200 },
          controller.signal,
        )
        .then((page) => {
          if (!controller.signal.aborted) {
            setResponse({
              key: requestKey,
              items: page.items,
              error: null,
              hasMore: page.next_offset !== null,
            });
          }
        })
        .catch((cause: unknown) => {
          if (!controller.signal.aborted) {
            setResponse({
              key: requestKey,
              items: [],
              error: cause instanceof Error ? cause : new Error("Не вдалося завантажити сесії."),
              hasMore: false,
            });
          }
        });
    }, 0);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [filter, organizationId, requestKey]);

  const loading = response?.key !== requestKey;
  const error = loading ? null : (response?.error ?? null);
  const sessions = loading || error ? [] : (response?.items ?? []);
  const hasMore = !loading && !error && response?.hasMore === true;
  const normalized = query.trim().toLocaleLowerCase("uk-UA");
  const visible = normalized
    ? sessions.filter((session) =>
        [session.session_number, session.title, session.test_object, session.customer, session.serial_number]
          .filter(Boolean)
          .some((value) => value?.toLocaleLowerCase("uk-UA").includes(normalized)),
      )
    : sessions;

  const refresh = () => setGeneration((value) => value + 1);
  const resetFilters = () => {
    setQuery("");
    setFilter("all");
  };

  return (
    <div className="space-y-4">
      <section className="panel p-5 sm:p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="text-xs font-semibold tracking-[0.12em] text-cyan-300 uppercase">
              Випробування · Моніторинг
            </p>
            <h1 className="mt-2 text-2xl font-semibold text-white sm:text-3xl">Лабораторні випробування</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
              Контролюйте статуси та відкривайте історію кожного лабораторного випробування.
            </p>
          </div>
          <div className="w-full min-w-0 xl:max-w-[440px]">
            <p className="mb-2 text-xs text-slate-400">
              Поточна вибірка · до 200 записів, не загальна статистика
            </p>
            <div className="grid grid-cols-3 gap-2">
              <Summary label="У вибірці" value={loading || error ? "—" : sessions.length} />
              <Summary
                label="Активні"
                value={
                  loading || error
                    ? "—"
                    : sessions.filter((item) => item.state === "running" || item.state === "paused").length
                }
              />
              <Summary
                label="Завершені"
                value={
                  loading || error
                    ? "—"
                    : sessions.filter((item) => item.state === "completed" || item.state === "archived")
                        .length
                }
              />
            </div>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="flex flex-col gap-3 border-b border-white/[0.055] p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
          <div className="flex flex-wrap gap-2" aria-label="Фільтр стану сесій">
            {FILTERS.map((item) => (
              <button
                key={item.value}
                onClick={() => setFilter(item.value)}
                aria-pressed={filter === item.value}
                className={`rounded-xl border px-3 py-2 text-xs font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 ${
                  filter === item.value
                    ? "border-blue-400/40 bg-blue-500/10 text-cyan-200"
                    : "border-white/[0.065] bg-white/[0.02] text-slate-500 hover:text-slate-200"
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <label className="relative min-w-0 flex-1 sm:w-72">
              <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-slate-600" />
              <input
                type="search"
                aria-label="Пошук сесій"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Номер, об’єкт, замовник…"
                className="form-input pl-10"
              />
            </label>
            <button className="icon-button inline-grid" onClick={refresh} aria-label="Оновити список">
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>

        {(query || filter !== "all" || hasMore) && (
          <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-3 text-xs text-slate-400 sm:px-5">
            <span>
              {loading || error
                ? "Вибірка недоступна"
                : "Показано " + visible.length + " з " + sessions.length + " завантажених"}
              {hasMore ? " · є наступні записи" : ""}
            </span>
            {(query || filter !== "all") && (
              <button
                type="button"
                onClick={resetFilters}
                className="font-medium text-cyan-300 hover:text-white focus-visible:outline-2 focus-visible:outline-cyan-300"
              >
                Скинути фільтри
              </button>
            )}
          </div>
        )}

        {error ? (
          <div className="m-4 rounded-2xl border border-amber-300/15 bg-amber-400/[0.045] p-5 sm:m-5">
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 text-amber-300" />
              <div>
                <h2 className="text-sm font-semibold text-white">API випробувань недоступний</h2>
                <p className="mt-1 text-[11px] leading-5 text-slate-400">{error.message}</p>
                <button className="secondary-button mt-3" onClick={refresh}>
                  Повторити
                </button>
              </div>
            </div>
          </div>
        ) : loading ? (
          <div className="grid min-h-72 place-items-center text-slate-500" role="status">
            <div className="text-center">
              <LoaderCircle className="mx-auto h-6 w-6 animate-spin text-cyan-300" />
              <p className="mt-3 text-sm">Завантаження реальних сесій…</p>
            </div>
          </div>
        ) : visible.length === 0 ? (
          <div className="grid min-h-72 place-items-center px-6 text-center">
            <div>
              <CircleDashed className="mx-auto h-8 w-8 text-slate-600" />
              <h2 className="mt-3 text-sm font-semibold text-white">Сесій не знайдено</h2>
              <p className="mt-1 text-[11px] text-slate-500">
                Змініть фільтр або створіть нову лабораторну сесію.
              </p>
              <Link href="/sessions/new" className="primary-button mt-4">
                Створити сесію
              </Link>
            </div>
          </div>
        ) : (
          <div className="divide-y divide-white/[0.045]">
            {visible.map((session) => (
              <Link
                key={session.id}
                href={`/sessions/${session.id}`}
                className="group grid min-w-0 gap-4 p-4 transition hover:bg-blue-500/[0.055] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-cyan-400 sm:grid-cols-2 sm:p-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,.8fr)_minmax(0,.8fr)] xl:items-center"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs [overflow-wrap:anywhere] text-cyan-300">
                      {session.session_number}
                    </span>
                    <span
                      className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-semibold ${stateClass(
                        session.state,
                      )}`}
                    >
                      <StateIcon state={session.state} />
                      {SESSION_STATE_LABELS[session.state]}
                    </span>
                  </div>
                  <h2 className="mt-2 text-base leading-snug font-semibold [overflow-wrap:anywhere] text-white">
                    {session.title}
                  </h2>
                  <p className="mt-1 text-xs leading-5 [overflow-wrap:anywhere] text-slate-400">
                    {session.test_object} · {session.model ?? "модель не вказана"}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-medium text-slate-400">Замовник / стандарт</p>
                  <p className="mt-1 text-sm [overflow-wrap:anywhere] text-slate-200">
                    {session.customer ?? "Внутрішнє випробування"}
                  </p>
                  <p className="mt-1 text-xs [overflow-wrap:anywhere] text-slate-400">
                    {session.standard ?? "Без стандарту"}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-medium text-slate-400">Конфігурація</p>
                  <p className="mt-1 text-xs leading-5 text-slate-200">
                    Знімок конфігурації {session.active_config_snapshot_id ? "зафіксовано" : "не зафіксовано"}
                  </p>
                  <p className="mt-1 text-xs text-slate-400">
                    Обмеження v{session.active_limit_version ?? "—"}
                  </p>
                </div>
                <div className="flex min-w-0 items-center gap-2 text-xs text-slate-400 xl:justify-end">
                  <Clock3 className="h-4 w-4 shrink-0" />
                  <span className="min-w-0">{formatDate(session.updated_at, displayTimeZone)}</span>
                  <ArrowUpRight
                    className="h-4 w-4 shrink-0 text-cyan-400 opacity-60 transition group-hover:opacity-100"
                    aria-hidden="true"
                  />
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function Summary({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-2xl border border-white/[0.06] bg-white/[0.025] p-3 text-center">
      <p className="text-xl font-semibold text-white">{value}</p>
      <p className="mt-1 text-xs text-slate-400">{label}</p>
    </div>
  );
}
