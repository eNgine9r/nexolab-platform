"use client";

import type { Dispatch, SetStateAction } from "react";
import { useMemo } from "react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  CheckCircle2,
  RefreshCw,
  Save,
  Trash2,
} from "lucide-react";

import {
  addDashboardDraftItem,
  dashboardItemIdentity,
  moveDashboardDraftItem,
  removeDashboardDraftItem,
} from "@/features/live-dashboards/model";
import {
  LIVE_DASHBOARD_MAX_ITEMS,
  LIVE_DASHBOARD_REFRESH_SECONDS,
  LIVE_DASHBOARD_TIME_WINDOWS,
  LIVE_DASHBOARD_VISUALIZATIONS,
  type LiveDashboardDraft,
  type LiveDashboardValidation,
} from "@/features/live-dashboards/types";
import type { LiveDashboardConflict } from "@/hooks/use-live-dashboard-library";
import type { LiveDashboardInventoryModel } from "@/hooks/use-live-dashboard-inventory";

import { DashboardChannelPicker } from "./dashboard-channel-picker";

const SUPPORTED_VISUALIZATIONS = LIVE_DASHBOARD_VISUALIZATIONS.filter((value) => value !== "gauge");

const VISUALIZATION_LABELS = {
  line: "Лінія",
  area: "Область",
  value: "Значення",
} as const;

export function DashboardEditor({
  draft,
  setDraft,
  inventory,
  validation,
  conflict,
  saving,
  saveError,
  onSave,
  onCancel,
  onUseServerVersion,
  onSaveAsCopy,
}: {
  draft: LiveDashboardDraft;
  setDraft: Dispatch<SetStateAction<LiveDashboardDraft>>;
  inventory: LiveDashboardInventoryModel;
  validation: LiveDashboardValidation;
  conflict: LiveDashboardConflict | null;
  saving: boolean;
  saveError: Error | null;
  onSave: () => void;
  onCancel: () => void;
  onUseServerVersion: () => void;
  onSaveAsCopy: () => void;
}) {
  const availableKeys = useMemo(() => new Set(inventory.items.map(dashboardItemIdentity)), [inventory.items]);
  const selected = useMemo(() => new Set(draft.items.map(dashboardItemIdentity)), [draft.items]);
  const unavailableItems = draft.items.filter((item) => !availableKeys.has(dashboardItemIdentity(item)));

  return (
    <section className="space-y-5" aria-labelledby="live-dashboard-editor-title">
      <div className="flex flex-col gap-4 rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-5 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <button
            type="button"
            onClick={onCancel}
            className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-cyan-200"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            До збережених панелей
          </button>
          <h1 id="live-dashboard-editor-title" className="mt-3 text-2xl font-semibold text-white sm:text-3xl">
            {draft.id ? "Редагування панелі" : "Нова панель"}
          </h1>
        </div>
        <button
          type="button"
          onClick={onSave}
          disabled={saving || !validation.valid}
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-cyan-300 px-5 py-2.5 text-sm font-semibold text-[#05202a] hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {saving ? (
            <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <Save className="h-4 w-4" aria-hidden="true" />
          )}
          {saving ? "Збереження…" : "Зберегти"}
        </button>
      </div>

      {conflict ? (
        <div className="rounded-3xl border border-amber-300/20 bg-amber-400/[0.07] p-5" role="alert">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-200" aria-hidden="true" />
            <div>
              <h2 className="font-semibold text-amber-100">Dashboard змінено іншим оператором</h2>
              <p className="mt-1 text-sm leading-6 text-amber-100/70">
                Ваші незбережені зміни залишилися в редакторі. Очікувана версія:{" "}
                {conflict.expectedVersion ?? "—"}, серверна:{" "}
                {conflict.actualVersion ?? conflict.server?.value.version ?? "—"}.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={onUseServerVersion}
                  disabled={!conflict.server}
                  className="rounded-xl border border-amber-200/20 px-4 py-2 text-sm text-amber-100 hover:bg-amber-300/10 disabled:opacity-40"
                >
                  Відкрити серверну версію
                </button>
                <button
                  type="button"
                  onClick={onSaveAsCopy}
                  className="rounded-xl bg-amber-300 px-4 py-2 text-sm font-semibold text-amber-950 hover:bg-amber-200"
                >
                  Зберегти мої зміни як копію
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {saveError ? (
        <div
          className="rounded-2xl border border-red-300/15 bg-red-400/[0.06] p-4 text-sm text-red-100"
          role="alert"
        >
          {saveError.message}
        </div>
      ) : null}

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
        <section className="rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-5">
          <h2 className="text-lg font-semibold text-white">Налаштування панелі</h2>
          <div className="mt-4 grid gap-4">
            <label className="grid gap-1.5 text-xs font-medium text-slate-400">
              Назва
              <input
                value={draft.name}
                maxLength={128}
                onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
                className="h-11 rounded-xl border border-white/10 bg-[#06142a] px-3 text-sm text-slate-100 outline-none focus:border-cyan-300/50 focus:ring-2 focus:ring-cyan-400/10"
              />
            </label>
            <label className="grid gap-1.5 text-xs font-medium text-slate-400">
              Опис
              <textarea
                value={draft.description}
                maxLength={1024}
                rows={3}
                onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))}
                className="rounded-xl border border-white/10 bg-[#06142a] px-3 py-2.5 text-sm text-slate-100 outline-none focus:border-cyan-300/50 focus:ring-2 focus:ring-cyan-400/10"
              />
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="grid gap-1.5 text-xs font-medium text-slate-400">
                Оновлення екрана
                <select
                  value={draft.refresh_seconds}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      refresh_seconds: Number(event.target.value) as LiveDashboardDraft["refresh_seconds"],
                    }))
                  }
                  className="h-10 rounded-xl border border-white/10 bg-[#06142a] px-3 text-sm text-slate-100"
                >
                  {LIVE_DASHBOARD_REFRESH_SECONDS.map((value) => (
                    <option key={value} value={value}>
                      {value} с
                    </option>
                  ))}
                </select>
              </label>
              <label className="grid gap-1.5 text-xs font-medium text-slate-400">
                Часове вікно
                <select
                  value={draft.time_window}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      time_window: event.target.value as LiveDashboardDraft["time_window"],
                    }))
                  }
                  className="h-10 rounded-xl border border-white/10 bg-[#06142a] px-3 text-sm text-slate-100"
                >
                  {LIVE_DASHBOARD_TIME_WINDOWS.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>
        </section>

        <DashboardChannelPicker
          inventory={inventory}
          selected={selected}
          count={draft.items.length}
          onToggle={(item) =>
            setDraft((current) => {
              const index = current.items.findIndex(
                (saved) => dashboardItemIdentity(saved) === dashboardItemIdentity(item),
              );
              return index < 0
                ? addDashboardDraftItem(current, item).draft
                : removeDashboardDraftItem(current, index);
            })
          }
        />

        <section className="min-w-0 rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-5 xl:col-start-1">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-white">Обрані канали</h2>
              <p className="mt-1 text-xs text-slate-500">
                {draft.items.length} / {LIVE_DASHBOARD_MAX_ITEMS} вибрано
              </p>
            </div>
            {validation.valid ? (
              <CheckCircle2 className="h-5 w-5 text-emerald-300" aria-label="Конфігурація валідна" />
            ) : (
              <AlertTriangle
                className="h-5 w-5 text-amber-300"
                aria-label="Конфігурація потребує виправлення"
              />
            )}
          </div>

          {unavailableItems.length > 0 && inventory.status === "ready" ? (
            <div className="mt-4 rounded-2xl border border-amber-300/15 bg-amber-400/[0.06] p-3 text-xs leading-5 text-amber-100">
              {unavailableItems.length} збережених каналів зараз недоступні. Перевірте їх перед збереженням.
            </div>
          ) : null}

          <ol className="mt-4 space-y-3">
            {draft.items.map((item, index) => {
              const available = availableKeys.has(dashboardItemIdentity(item));
              return (
                <li
                  key={`${dashboardItemIdentity(item)}-${index}`}
                  className="rounded-2xl border border-white/[0.07] bg-[#06142a]/75 p-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-medium break-all text-slate-100">
                        {item.channel_id} · {item.metric}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        {[item.equipment_id, item.native_unit].filter(Boolean).join(" · ")}
                      </p>
                      <p className={`mt-1 text-[11px] ${available ? "text-emerald-300" : "text-amber-300"}`}>
                        {available ? "Доступний" : "Потребує серверної перевірки"}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setDraft((current) => removeDashboardDraftItem(current, index))}
                      aria-label={`Видалити ${item.channel_id} ${item.metric}`}
                      className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-red-300/10 text-red-200 hover:bg-red-400/10"
                    >
                      <Trash2 className="h-4 w-4" aria-hidden="true" />
                    </button>
                  </div>
                  <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_86px_auto] sm:items-end">
                    <label className="grid gap-1 text-[11px] text-slate-500">
                      Візуалізація
                      <select
                        value={item.visualization}
                        onChange={(event) =>
                          setDraft((current) => ({
                            ...current,
                            items: current.items.map((currentItem, itemIndex) =>
                              itemIndex === index
                                ? {
                                    ...currentItem,
                                    visualization: event.target
                                      .value as LiveDashboardDraft["items"][number]["visualization"],
                                  }
                                : currentItem,
                            ),
                          }))
                        }
                        className="h-9 rounded-xl border border-white/10 bg-[#081a32] px-2 text-xs text-slate-200"
                      >
                        {item.visualization === "gauge" ? (
                          <option value="gauge" disabled>
                            Значення (старий індикатор)
                          </option>
                        ) : null}
                        {SUPPORTED_VISUALIZATIONS.map((value) => (
                          <option key={value} value={value}>
                            {VISUALIZATION_LABELS[value]}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="grid gap-1 text-[11px] text-slate-500">
                      Колір
                      <input
                        type="color"
                        value={item.color ?? "#00C6E0"}
                        onChange={(event) =>
                          setDraft((current) => ({
                            ...current,
                            items: current.items.map((currentItem, itemIndex) =>
                              itemIndex === index
                                ? { ...currentItem, color: event.target.value.toUpperCase() }
                                : currentItem,
                            ),
                          }))
                        }
                        className="h-9 w-full cursor-pointer rounded-xl border border-white/10 bg-[#081a32] p-1"
                      />
                    </label>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => setDraft((current) => moveDashboardDraftItem(current, index, -1))}
                        disabled={index === 0}
                        aria-label={`Перемістити ${item.channel_id} вище`}
                        className="grid h-9 w-9 place-items-center rounded-xl border border-white/10 text-slate-300 disabled:opacity-30"
                      >
                        <ArrowUp className="h-4 w-4" aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        onClick={() => setDraft((current) => moveDashboardDraftItem(current, index, 1))}
                        disabled={index === draft.items.length - 1}
                        aria-label={`Перемістити ${item.channel_id} нижче`}
                        className="grid h-9 w-9 place-items-center rounded-xl border border-white/10 text-slate-300 disabled:opacity-30"
                      >
                        <ArrowDown className="h-4 w-4" aria-hidden="true" />
                      </button>
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>

          {draft.items.length === 0 ? (
            <p className="mt-4 rounded-2xl border border-dashed border-white/10 p-4 text-center text-sm text-slate-500">
              Додайте потрібні канали зі списку.
            </p>
          ) : null}

          {!validation.valid ? (
            <ul className="mt-4 space-y-1 text-xs leading-5 text-amber-100" aria-label="Помилки валідації">
              {validation.issues.map((issue) => (
                <li key={issue}>• {issue}</li>
              ))}
            </ul>
          ) : null}
        </section>
      </div>
    </section>
  );
}
