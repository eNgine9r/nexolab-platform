"use client";

import type { Dispatch, SetStateAction } from "react";
import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  CheckCircle2,
  Plus,
  RefreshCw,
  Save,
  Search,
  Trash2,
} from "lucide-react";

import {
  addDashboardDraftItem,
  dashboardItemIdentity,
  defaultLiveDashboardInventoryFilters,
  filterLiveDashboardInventory,
  moveDashboardDraftItem,
  removeDashboardDraftItem,
} from "@/features/live-dashboards/model";
import {
  LIVE_DASHBOARD_REFRESH_SECONDS,
  LIVE_DASHBOARD_TIME_WINDOWS,
  LIVE_DASHBOARD_VISUALIZATIONS,
  type LiveDashboardDraft,
  type LiveDashboardInventoryFilters,
  type LiveDashboardValidation,
} from "@/features/live-dashboards/types";
import type { LiveDashboardConflict } from "@/hooks/use-live-dashboard-library";
import type { LiveDashboardInventoryModel } from "@/hooks/use-live-dashboard-inventory";

const VISUALIZATION_LABELS = {
  line: "Лінія",
  area: "Область",
  gauge: "Індикатор",
  value: "Значення",
} as const;

function sortedUnique(values: Iterable<string>): string[] {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right, "uk-UA"));
}

function qualityLabel(value: string): string {
  if (value === "valid") return "Валідні";
  if (value === "sensor_error") return "Помилка датчика";
  if (value === "communication_error") return "Помилка зв’язку";
  if (value === "unknown") return "Невідомі";
  return "Усі";
}

function SelectFilter({
  label,
  value,
  values,
  onChange,
}: {
  label: string;
  value: string;
  values: string[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid gap-1.5 text-xs font-medium text-slate-400">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 min-w-0 rounded-xl border border-white/10 bg-[#06142a] px-3 text-sm text-slate-100 outline-none focus:border-cyan-300/50 focus:ring-2 focus:ring-cyan-400/10"
      >
        <option value="all">Усі</option>
        {values.map((item) => (
          <option key={item} value={item}>
            {item}
          </option>
        ))}
      </select>
    </label>
  );
}

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
  const [filters, setFilters] = useState<LiveDashboardInventoryFilters>(defaultLiveDashboardInventoryFilters);
  const [selectionNotice, setSelectionNotice] = useState<string | null>(null);
  const filteredInventory = useMemo(
    () => filterLiveDashboardInventory(inventory.items, filters),
    [filters, inventory.items],
  );
  const selectedKeys = useMemo(() => new Set(draft.items.map(dashboardItemIdentity)), [draft.items]);
  const availableKeys = useMemo(
    () => new Set(inventory.items.map((item) => dashboardItemIdentity(item))),
    [inventory.items],
  );
  const unavailableItems = draft.items.filter((item) => !availableKeys.has(dashboardItemIdentity(item)));
  const nodeOptions = sortedUnique(inventory.items.map((item) => item.node_id));
  const equipmentOptions = sortedUnique(inventory.items.map((item) => item.equipment_id));
  const metricOptions = sortedUnique(inventory.items.map((item) => item.metric));

  const updateFilter = (field: keyof LiveDashboardInventoryFilters, value: string) => {
    setFilters((current) => ({ ...current, [field]: value }));
  };

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
                Виберіть канали з inventory праворуч.
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

        <section className="rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-white">Canonical channel inventory</h2>
              <p className="mt-1 text-xs leading-5 text-slate-500">
                Inventory завантажується лише для редактора. Live view використовує тільки збережені канали.
              </p>
            </div>
            <button
              type="button"
              onClick={inventory.retry}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-slate-300 hover:border-cyan-300/30"
            >
              <RefreshCw
                className={`h-4 w-4 ${inventory.status === "loading" ? "animate-spin" : ""}`}
                aria-hidden="true"
              />
              Оновити inventory
            </button>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            <label className="grid gap-1.5 text-xs font-medium text-slate-400 md:col-span-2 xl:col-span-3">
              Пошук
              <span className="relative block">
                <Search
                  className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-slate-500"
                  aria-hidden="true"
                />
                <input
                  type="search"
                  value={filters.search}
                  onChange={(event) => updateFilter("search", event.target.value)}
                  placeholder="Node, equipment, channel, metric, source"
                  className="h-10 w-full rounded-xl border border-white/10 bg-[#06142a] pr-3 pl-10 text-sm text-slate-100 outline-none"
                />
              </span>
            </label>
            <SelectFilter
              label="Node"
              value={filters.node_id}
              values={nodeOptions}
              onChange={(value) => updateFilter("node_id", value)}
            />
            <SelectFilter
              label="Equipment"
              value={filters.equipment_id}
              values={equipmentOptions}
              onChange={(value) => updateFilter("equipment_id", value)}
            />
            <SelectFilter
              label="Metric"
              value={filters.metric}
              values={metricOptions}
              onChange={(value) => updateFilter("metric", value)}
            />
            <label className="grid gap-1.5 text-xs font-medium text-slate-400">
              Якість latest
              <select
                value={filters.quality}
                onChange={(event) => updateFilter("quality", event.target.value)}
                className="h-10 rounded-xl border border-white/10 bg-[#06142a] px-3 text-sm text-slate-100"
              >
                {["all", "valid", "sensor_error", "communication_error", "unknown"].map((value) => (
                  <option key={value} value={value}>
                    {qualityLabel(value)}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1.5 text-xs font-medium text-slate-400">
              Тривога latest
              <select
                value={filters.alarm}
                onChange={(event) => updateFilter("alarm", event.target.value)}
                className="h-10 rounded-xl border border-white/10 bg-[#06142a] px-3 text-sm text-slate-100"
              >
                <option value="all">Усі</option>
                <option value="active">Активна</option>
                <option value="none">Без тривоги</option>
              </select>
            </label>
          </div>

          {selectionNotice ? (
            <p className="mt-3 rounded-xl border border-cyan-300/10 bg-cyan-400/[0.05] px-3 py-2 text-xs text-cyan-100">
              {selectionNotice}
            </p>
          ) : null}

          {inventory.status === "loading" ? (
            <div className="grid min-h-64 place-items-center text-sm text-cyan-100">
              <span className="inline-flex items-center gap-2">
                <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />
                Читання latest inventory…
              </span>
            </div>
          ) : null}

          {inventory.status === "error" ? (
            <div className="mt-4 rounded-2xl border border-red-300/15 bg-red-400/[0.06] p-4 text-sm text-red-100">
              {inventory.error?.message ?? "Inventory недоступний."}
            </div>
          ) : null}

          {inventory.status === "ready" && filteredInventory.length === 0 ? (
            <div className="grid min-h-56 place-items-center text-center text-sm text-slate-500">
              <p>Каналів за цими фільтрами немає.</p>
            </div>
          ) : null}

          {inventory.status === "ready" && filteredInventory.length > 0 ? (
            <div className="mt-5 max-h-[720px] space-y-2 overflow-y-auto pr-1">
              {filteredInventory.map((item) => {
                const selected = selectedKeys.has(item.key);
                return (
                  <article
                    key={item.key}
                    className="flex flex-col gap-3 rounded-2xl border border-white/[0.07] bg-[#06142a]/75 p-3 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-slate-100">
                        {item.channel_id} · {item.metric}
                      </p>
                      <p className="mt-1 truncate text-xs text-slate-500">
                        {item.node_id} · {item.equipment_id} · {item.source} · {item.native_unit}
                      </p>
                      <p className="mt-1 text-[11px] text-slate-500">
                        Якість: {qualityLabel(item.quality)} · Тривога: {item.alarm ?? "немає"}
                      </p>
                    </div>
                    <button
                      type="button"
                      disabled={selected}
                      onClick={() => {
                        setDraft((current) => {
                          const result = addDashboardDraftItem(current, item);
                          setSelectionNotice(
                            result.reason === "added"
                              ? `${item.channel_id} додано.`
                              : result.reason === "duplicate"
                                ? "Цей канал уже вибрано."
                                : "Досягнуто межу 64 канали.",
                          );
                          return result.draft;
                        });
                      }}
                      className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-xl border border-cyan-300/15 px-3 text-sm text-cyan-100 hover:bg-cyan-400/[0.06] disabled:cursor-not-allowed disabled:border-emerald-300/10 disabled:text-emerald-300"
                    >
                      {selected ? (
                        <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                      ) : (
                        <Plus className="h-4 w-4" aria-hidden="true" />
                      )}
                      {selected ? "Додано" : "Додати"}
                    </button>
                  </article>
                );
              })}
            </div>
          ) : null}
        </section>
      </div>
    </section>
  );
}
