"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  CircleDashed,
  Clock3,
  LoaderCircle,
  PauseCircle,
  PlayCircle,
  RefreshCw,
  Search,
} from "lucide-react";

import { createSessionApiClient } from "@/lib/sessions/api-client";
import type { LaboratorySession, SessionState } from "@/lib/sessions/types";
import { SESSION_STATE_LABELS } from "@/lib/sessions/view-model";

const FILTERS: Array<{ value: "all" | SessionState; label: string }> = [
  { value: "all", label: "Усі" },
  { value: "running", label: "Виконуються" },
  { value: "paused", label: "Призупинені" },
  { value: "draft", label: "Чернетки" },
  { value: "completed", label: "Завершені" },
  { value: "archived", label: "Архів" },
];

function StateIcon({ state }: { state: SessionState }) {
  if (state === "running") return <PlayCircle className="h-3 w-3" />;
  if (state === "paused") return <PauseCircle className="h-3 w-3" />;
  if (state === "completed") return <CheckCircle2 className="h-3 w-3" />;
  if (state === "archived") return <Archive className="h-3 w-3" />;
  return <CircleDashed className="h-3 w-3" />;
}

function stateClass(state: SessionState): string {
  if (state === "running") return "border-emerald-300/20 bg-emerald-400/[0.06] text-emerald-300";
  if (state === "paused") return "border-amber-300/20 bg-amber-400/[0.06] text-amber-300";
  if (state === "completed") return "border-cyan-300/20 bg-cyan-400/[0.06] text-cyan-300";
  if (state === "cancelled") return "border-red-300/20 bg-red-400/[0.06] text-red-300";
  return "border-slate-400/15 bg-slate-400/[0.05] text-slate-300";
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("uk-UA", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function SessionsListScreen() {
  const [sessions, setSessions] = useState<LaboratorySession[]>([]);
  const [filter, setFilter] = useState<"all" | SessionState>("all");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [generation, setGeneration] = useState(0);

  const load = useCallback(
    async (signal: AbortSignal) => {
      setLoading(true);
      try {
        const client = createSessionApiClient();
        const page = await client.listSessions(
          {
            state: filter === "all" ? undefined : filter,
            nodeId: "edge-01",
            limit: 200,
          },
          signal,
        );
        setSessions(page.items);
        setError(null);
      } catch (nextError) {
        if (!signal.aborted) {
          setError(nextError instanceof Error ? nextError : new Error("Не вдалося завантажити сесії."));
        }
      } finally {
        if (!signal.aborted) setLoading(false);
      }
    },
    [filter],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [generation, load]);

  const visible = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("uk-UA");
    if (!normalized) return sessions;
    return sessions.filter((session) =>
      [session.session_number, session.title, session.test_object, session.customer, session.serial_number]
        .filter(Boolean)
        .some((value) => value?.toLocaleLowerCase("uk-UA").includes(normalized)),
    );
  }, [query, sessions]);

  return (
    <div className="space-y-4">
      <section className="panel p-5 sm:p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="text-[9px] font-semibold tracking-[0.18em] text-cyan-300 uppercase">
              M4 · Sessions
            </p>
            <h1 className="mt-2 text-2xl font-semibold text-white sm:text-3xl">Лабораторні випробування</h1>
            <p className="mt-2 max-w-3xl text-[12px] leading-6 text-slate-400">
              Реальні сесії з central backend: конфігурація, 34 production series, етапи, телеметрія та
              immutable audit.
            </p>
          </div>
          <div className="grid grid-cols-3 gap-2 sm:min-w-[420px]">
            <Summary label="Усього" value={sessions.length} />
            <Summary
              label="Активні"
              value={sessions.filter((item) => item.state === "running" || item.state === "paused").length}
            />
            <Summary
              label="Завершені"
              value={
                sessions.filter((item) => item.state === "completed" || item.state === "archived").length
              }
            />
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
                className={`rounded-xl border px-3 py-2 text-[10px] font-semibold transition ${
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
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Номер, об’єкт, замовник…"
                className="form-input pl-10"
              />
            </label>
            <button
              className="icon-button inline-grid"
              onClick={() => setGeneration((value) => value + 1)}
              aria-label="Оновити список"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>

        {error ? (
          <div className="m-4 rounded-2xl border border-amber-300/15 bg-amber-400/[0.045] p-5 sm:m-5">
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 text-amber-300" />
              <div>
                <h2 className="text-sm font-semibold text-white">Sessions API недоступний</h2>
                <p className="mt-1 text-[11px] leading-5 text-slate-400">{error.message}</p>
                <button className="secondary-button mt-3" onClick={() => setGeneration((value) => value + 1)}>
                  Повторити
                </button>
              </div>
            </div>
          </div>
        ) : loading ? (
          <div className="grid min-h-72 place-items-center text-slate-500">
            <div className="text-center">
              <LoaderCircle className="mx-auto h-6 w-6 animate-spin text-cyan-300" />
              <p className="mt-3 text-[11px]">Завантаження реальних сесій…</p>
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
                className="grid gap-3 p-4 transition hover:bg-blue-500/[0.035] sm:grid-cols-[minmax(0,1.4fr)_minmax(180px,.8fr)_160px_170px] sm:items-center sm:p-5"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[9px] text-cyan-300">{session.session_number}</span>
                    <span
                      className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[8px] font-semibold ${stateClass(
                        session.state,
                      )}`}
                    >
                      <StateIcon state={session.state} />
                      {SESSION_STATE_LABELS[session.state]}
                    </span>
                  </div>
                  <h2 className="mt-2 truncate text-sm font-semibold text-white">{session.title}</h2>
                  <p className="mt-1 truncate text-[10px] text-slate-500">
                    {session.test_object} · {session.model ?? "модель не вказана"}
                  </p>
                </div>
                <div>
                  <p className="text-[8px] tracking-[0.12em] text-slate-600 uppercase">
                    Замовник / стандарт
                  </p>
                  <p className="mt-1 truncate text-[10px] text-slate-300">
                    {session.customer ?? "Внутрішнє випробування"}
                  </p>
                  <p className="mt-1 truncate text-[9px] text-slate-600">
                    {session.standard ?? "Без стандарту"}
                  </p>
                </div>
                <div>
                  <p className="text-[8px] tracking-[0.12em] text-slate-600 uppercase">Конфігурація</p>
                  <p className="mt-1 text-[10px] text-slate-300">
                    Snapshot {session.active_config_snapshot_id ? "зафіксовано" : "не зафіксовано"}
                  </p>
                  <p className="mt-1 text-[9px] text-slate-600">
                    Limits v{session.active_limit_version ?? "—"}
                  </p>
                </div>
                <div className="flex items-center gap-2 text-[9px] text-slate-500 sm:justify-end">
                  <Clock3 className="h-3.5 w-3.5" />
                  <span>{formatDate(session.updated_at)}</span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function Summary({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl border border-white/[0.06] bg-white/[0.025] p-3 text-center">
      <p className="text-xl font-semibold text-white">{value}</p>
      <p className="mt-1 text-[8px] tracking-[0.12em] text-slate-600 uppercase">{label}</p>
    </div>
  );
}
