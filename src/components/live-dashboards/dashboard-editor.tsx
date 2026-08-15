"use client";

import type { Dispatch, SetStateAction } from "react";
import { useMemo, useState } from "react";
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
  dashboardItemIdentity,
  moveDashboardDraftItem,
  removeDashboardDraftItem,
} from "@/features/live-dashboards/model";
import {
  buildLiveDashboardTelemetrySelectionModel,
  reconcileLiveDashboardTelemetrySelection,
} from "@/features/live-dashboards/telemetry-selection-adapter";
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

import { TelemetryPointSelector } from "@/components/telemetry-selection/telemetry-point-selector";

const VISUALIZATION_LABELS = {
  line: "Лінія",
  area: "Область",
  gauge: "Індикатор",
  value: "Значення",
} as const;

export function DashboardEditor({
  organizationId,
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
  organizationId: string;
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
  const [selectionNotice, setSelectionNotice] = useState<string | null>(null);
  const selectionModel = useMemo(
    () => buildLiveDashboardTelemetrySelectionModel(organizationId, inventory.items, draft.items),
    [draft.items, inventory.items, organizationId],
  );
  const availableKeys = selectionModel.inventoryIdentities;
  const unavailableItems = selectionModel.unresolvedItems;
  const availableSelectionLimit = Math.max(0, LIVE_DASHBOARD_MAX_ITEMS - unavailableItems.length);

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
            До library
          </button>
          <h1 id="live-dashboard-editor-title" className="mt-3 text-2xl font-semibold text-white sm:text-3xl">
            {draft.id ? "Редагування Live Dashboard" : "Новий Live Dashboard"}
          </h1>
          <p className="mt-2 text-sm leading-6 text-slate-400">
            Вибір каналів формує лише read model. Refresh і time window не змінюють scheduler або Modbus
            cadence.
          </p>
        </div>
        <button
          type="button"
          onClick={onSave}
          disabled={saving || !validation.valid}
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-blue-500 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-400 disabled:cursor-not-allowed disabled:opacity-40"
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

      <div className="grid gap-5 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.35fr)]">
        <div className="space-y-5">
          <section className="rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-5">
            <h2 className="text-lg font-semibold text-white">Основні налаштування</h2>
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
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, description: event.target.value }))
                  }
                  className="rounded-xl border border-white/10 bg-[#06142a] px-3 py-2.5 text-sm text-slate-100 outline-none focus:border-cyan-300/50 focus:ring-2 focus:ring-cyan-400/10"
                />
              </label>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="grid gap-1.5 text-xs font-medium text-slate-400">
                  Display refresh
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
                  Time window
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

          <section className="rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-white">Канали</h2>
                <p className="mt-1 text-xs text-slate-500">{draft.items.length} / 64 вибрано</p>
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
                {unavailableItems.length} збережених каналів відсутні у поточному latest inventory. Вони не
                видаляються автоматично; сервер повторно перевірить їх під час save.
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
                        <p className="truncate text-sm font-medium text-slate-100">
                          {item.channel_id} · {item.metric}
                        </p>
                        <p className="mt-1 text-xs text-slate-500">
                          {item.node_id ?? "node невідомий"} · {item.equipment_id ?? "equipment невідоме"} ·{" "}
                          {item.native_unit}
                        </p>
                        <p
                          className={`mt-1 text-[11px] ${available ? "text-emerald-300" : "text-amber-300"}`}
                        >
                          {available ? "Доступний у latest inventory" : "Потребує серверної перевірки"}
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
                          {LIVE_DASHBOARD_VISUALIZATIONS.map((value) => (
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
                Виберіть точки телеметрії в ієрархії праворуч.
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

        <section className="min-w-0 space-y-4">
          <div className="flex flex-col gap-3 rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-5 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-white">Ієрархічний вибір телеметрії</h2>
              <p className="mt-1 max-w-2xl text-xs leading-5 text-slate-500">
                Один read-only inventory: лабораторія / зона → тип обладнання → обладнання → канал і метрика.
                Непідтверджені зміни не змінюють Dashboard.
              </p>
            </div>
            <button
              type="button"
              onClick={inventory.retry}
              className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-slate-300 hover:border-cyan-300/30"
            >
              <RefreshCw
                className={`h-4 w-4 ${inventory.status === "loading" ? "animate-spin" : ""}`}
                aria-hidden="true"
              />
              Оновити inventory
            </button>
          </div>

          {selectionNotice ? (
            <p
              className="rounded-xl border border-cyan-300/10 bg-cyan-400/[0.05] px-3 py-2 text-xs text-cyan-100"
              role="status"
            >
              {selectionNotice}
            </p>
          ) : null}

          {inventory.status === "loading" ? (
            <div className="grid min-h-64 place-items-center rounded-3xl border border-white/[0.08] bg-[#091a31]/90 text-sm text-cyan-100">
              <span className="inline-flex items-center gap-2">
                <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />
                Читання canonical inventory…
              </span>
            </div>
          ) : null}

          {inventory.status === "error" ? (
            <div
              className="rounded-2xl border border-red-300/15 bg-red-400/[0.06] p-4 text-sm text-red-100"
              role="alert"
            >
              {inventory.error?.message ?? "Inventory недоступний."}
            </div>
          ) : null}

          {inventory.status === "ready" && inventory.items.length === 0 ? (
            <div className="grid min-h-56 place-items-center rounded-3xl border border-dashed border-white/10 bg-[#091a31]/70 p-5 text-center text-sm text-slate-500">
              <p>У canonical inventory немає доступних точок телеметрії.</p>
            </div>
          ) : null}

          {inventory.status === "ready" && inventory.items.length > 0 ? (
            <TelemetryPointSelector
              hierarchy={selectionModel.hierarchy}
              value={selectionModel.selectedKeys}
              maxSelection={availableSelectionLimit}
              title="Канали Live Dashboard"
              onConfirm={(selected) => {
                setDraft((current) =>
                  reconcileLiveDashboardTelemetrySelection(
                    current,
                    selected,
                    organizationId,
                    inventory.items,
                  ),
                );
                setSelectionNotice("Підтверджений вибір застосовано до чернетки Dashboard.");
              }}
              onCancel={() => setSelectionNotice("Непідтверджені зміни селектора скасовано.")}
            />
          ) : null}
        </section>
      </div>
    </section>
  );
}
