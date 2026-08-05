"use client";

import {
  Archive,
  Copy,
  Edit3,
  FolderOpen,
  LayoutDashboard,
  Plus,
  RefreshCw,
  Search,
} from "lucide-react";

import type { LiveDashboard, LiveDashboardStatus } from "@/features/live-dashboards/types";
import type { LiveDashboardLibraryStatus } from "@/hooks/use-live-dashboard-library";

function formatTimestamp(value: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "Невідомий час";
  return new Intl.DateTimeFormat("uk-UA", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(timestamp);
}

function statusLabel(status: LiveDashboardStatus): string {
  return status === "active" ? "Активний" : "Архівний";
}

export function DashboardLibrary({
  dashboards,
  status,
  error,
  search,
  onSearchChange,
  includeArchived,
  onIncludeArchivedChange,
  canManage,
  onCreate,
  onOpen,
  onEdit,
  onDuplicate,
  onArchive,
  onRetry,
}: {
  dashboards: LiveDashboard[];
  status: LiveDashboardLibraryStatus;
  error: Error | null;
  search: string;
  onSearchChange: (value: string) => void;
  includeArchived: boolean;
  onIncludeArchivedChange: (value: boolean) => void;
  canManage: boolean;
  onCreate: () => void;
  onOpen: (dashboard: LiveDashboard) => void;
  onEdit: (dashboard: LiveDashboard) => void;
  onDuplicate: (dashboard: LiveDashboard) => void;
  onArchive: (dashboard: LiveDashboard) => void;
  onRetry: () => void;
}) {
  return (
    <section className="space-y-5" aria-labelledby="live-dashboard-library-title">
      <div className="flex flex-col gap-4 rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-5 shadow-2xl shadow-black/20 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="text-xs font-semibold tracking-[0.18em] text-cyan-300 uppercase">Operator workspace</p>
          <h1 id="live-dashboard-library-title" className="mt-1 text-2xl font-semibold text-white sm:text-3xl">
            Live Dashboards
          </h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
            Збережені робочі екрани відкривають тільки вибрані канали. Налаштування відображення не
            змінюють фізичне опитування обладнання.
          </p>
        </div>
        {canManage ? (
          <button
            type="button"
            onClick={onCreate}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-blue-500 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-400 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300"
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            Створити Dashboard
          </button>
        ) : null}
      </div>

      <div className="grid gap-3 rounded-2xl border border-white/[0.08] bg-[#081a32]/85 p-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
        <label className="grid gap-1.5 text-xs font-medium text-slate-400">
          Пошук Dashboard
          <span className="relative block">
            <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <input
              type="search"
              value={search}
              onChange={(event) => onSearchChange(event.target.value)}
              placeholder="Назва, опис, власник або канал"
              className="h-11 w-full rounded-xl border border-white/10 bg-[#06142a] pr-3 pl-10 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-cyan-300/50 focus:ring-2 focus:ring-cyan-400/10"
            />
          </span>
        </label>
        <label className="inline-flex min-h-11 items-center gap-3 rounded-xl border border-white/10 bg-[#06142a] px-3 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={(event) => onIncludeArchivedChange(event.target.checked)}
            className="h-4 w-4 rounded border-white/20 bg-transparent accent-blue-500"
          />
          Показувати архівні
        </label>
      </div>

      {status === "loading" ? (
        <div className="grid min-h-64 place-items-center rounded-3xl border border-cyan-300/10 bg-[#081a32]/70 text-sm text-cyan-100">
          <span className="inline-flex items-center gap-2">
            <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />
            Завантаження з локальної бази…
          </span>
        </div>
      ) : null}

      {status === "forbidden" ? (
        <div className="rounded-3xl border border-red-300/15 bg-red-400/[0.05] p-6">
          <h2 className="text-lg font-semibold text-red-100">Доступ до Live Dashboards заборонено</h2>
          <p className="mt-2 text-sm leading-6 text-red-100/70">
            Поточна роль не має `dashboard.read` для цієї організації. Дані іншої організації не
            завантажувалися.
          </p>
        </div>
      ) : null}

      {status === "error" ? (
        <div className="rounded-3xl border border-red-300/15 bg-red-400/[0.05] p-6">
          <h2 className="text-lg font-semibold text-red-100">Library недоступна</h2>
          <p className="mt-2 text-sm leading-6 text-red-100/70">
            {error?.message ?? "Не вдалося прочитати Live Dashboards з локального API."}
          </p>
          <button
            type="button"
            onClick={onRetry}
            className="mt-4 inline-flex items-center gap-2 rounded-xl border border-red-200/20 px-4 py-2.5 text-sm text-red-100 hover:bg-red-300/10"
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            Повторити
          </button>
        </div>
      ) : null}

      {status === "ready" && dashboards.length === 0 ? (
        <div className="grid min-h-72 place-items-center rounded-3xl border border-dashed border-white/10 bg-[#081a32]/55 p-8 text-center">
          <div className="max-w-md">
            <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl border border-cyan-300/15 bg-cyan-400/[0.06]">
              <LayoutDashboard className="h-6 w-6 text-cyan-300" aria-hidden="true" />
            </div>
            <h2 className="mt-4 text-lg font-semibold text-white">Збережених Dashboard ще немає</h2>
            <p className="mt-2 text-sm leading-6 text-slate-400">
              Створіть перший екран, виберіть канали та відкривайте його без повторного universal scan.
            </p>
            {canManage ? (
              <button
                type="button"
                onClick={onCreate}
                className="mt-5 inline-flex items-center gap-2 rounded-xl bg-blue-500 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-400"
              >
                <Plus className="h-4 w-4" aria-hidden="true" />
                Створити перший Dashboard
              </button>
            ) : null}
          </div>
        </div>
      ) : null}

      {status === "ready" && dashboards.length > 0 ? (
        <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
          {dashboards.map((dashboard) => (
            <article
              key={dashboard.id}
              className="flex min-h-64 flex-col rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-5 shadow-xl shadow-black/15 transition hover:border-cyan-300/20"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${
                        dashboard.status === "active"
                          ? "border-emerald-300/20 bg-emerald-400/10 text-emerald-200"
                          : "border-slate-300/15 bg-slate-400/10 text-slate-300"
                      }`}
                    >
                      {statusLabel(dashboard.status)}
                    </span>
                    <span className="text-xs text-slate-500">v{dashboard.version}</span>
                  </div>
                  <h2 className="mt-3 truncate text-lg font-semibold text-white" title={dashboard.name}>
                    {dashboard.name}
                  </h2>
                </div>
                <div className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl border border-cyan-300/15 bg-cyan-400/[0.06]">
                  <LayoutDashboard className="h-5 w-5 text-cyan-300" aria-hidden="true" />
                </div>
              </div>

              <p className="mt-3 line-clamp-2 min-h-10 text-sm leading-5 text-slate-400">
                {dashboard.description ?? "Без опису"}
              </p>

              <dl className="mt-4 grid grid-cols-2 gap-3 text-xs">
                <div className="rounded-xl border border-white/[0.06] bg-[#06142a]/70 p-3">
                  <dt className="text-slate-500">Серії</dt>
                  <dd className="mt-1 text-base font-semibold text-slate-100">{dashboard.items.length}</dd>
                </div>
                <div className="rounded-xl border border-white/[0.06] bg-[#06142a]/70 p-3">
                  <dt className="text-slate-500">Вікно / refresh</dt>
                  <dd className="mt-1 font-medium text-slate-200">
                    {dashboard.time_window} · {dashboard.refresh_seconds} с
                  </dd>
                </div>
              </dl>

              <div className="mt-4 text-xs leading-5 text-slate-500">
                <p>Власник: {dashboard.owner_subject}</p>
                <p>Оновлено: {formatTimestamp(dashboard.updated_at)}</p>
              </div>

              <div className="mt-auto flex flex-wrap gap-2 pt-5">
                <button
                  type="button"
                  onClick={() => onOpen(dashboard)}
                  disabled={dashboard.status !== "active" || dashboard.items.length === 0}
                  className="inline-flex min-h-10 flex-1 items-center justify-center gap-2 rounded-xl bg-blue-500 px-3 text-sm font-medium text-white hover:bg-blue-400 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <FolderOpen className="h-4 w-4" aria-hidden="true" />
                  Відкрити
                </button>
                {canManage && dashboard.status === "active" ? (
                  <>
                    <button
                      type="button"
                      onClick={() => onEdit(dashboard)}
                      aria-label={`Редагувати ${dashboard.name}`}
                      title="Редагувати"
                      className="grid h-10 w-10 place-items-center rounded-xl border border-white/10 text-slate-300 hover:border-cyan-300/30 hover:text-cyan-200"
                    >
                      <Edit3 className="h-4 w-4" aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      onClick={() => onDuplicate(dashboard)}
                      aria-label={`Дублювати ${dashboard.name}`}
                      title="Дублювати"
                      className="grid h-10 w-10 place-items-center rounded-xl border border-white/10 text-slate-300 hover:border-cyan-300/30 hover:text-cyan-200"
                    >
                      <Copy className="h-4 w-4" aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      onClick={() => onArchive(dashboard)}
                      aria-label={`Архівувати ${dashboard.name}`}
                      title="Архівувати"
                      className="grid h-10 w-10 place-items-center rounded-xl border border-red-300/10 text-red-200/80 hover:border-red-300/30 hover:bg-red-400/10"
                    >
                      <Archive className="h-4 w-4" aria-hidden="true" />
                    </button>
                  </>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}
