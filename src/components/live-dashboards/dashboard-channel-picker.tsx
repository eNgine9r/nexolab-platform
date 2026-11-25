"use client";

import { Check, Plus, RefreshCw, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { dashboardItemIdentity } from "@/features/live-dashboards/model";
import { LIVE_DASHBOARD_MAX_ITEMS, type LiveDashboardInventoryItem } from "@/features/live-dashboards/types";
import type { LiveDashboardInventoryModel } from "@/hooks/use-live-dashboard-inventory";

const PAGE_SIZE = 60;
const DEVICE_NAMES: Readonly<Record<string, string>> = {
  "dixell-xjp60d-sections": "Dixell XJP60D",
  "eastron-sdm120m": "Eastron SDM120M",
  "waveshare-analog-input-8ch-b-v3": "Waveshare 8AI",
};

function deviceName(item: LiveDashboardInventoryItem): string {
  const model = DEVICE_NAMES[item.source];
  return item.channel_ref_id === null && model
    ? `${model} · ${item.equipment_id.split(":").at(-1)}`
    : item.equipment_name;
}

export function DashboardChannelPicker({
  inventory,
  selected,
  count,
  onToggle,
}: {
  inventory: LiveDashboardInventoryModel;
  selected: ReadonlySet<string>;
  count: number;
  onToggle: (item: LiveDashboardInventoryItem) => void;
}) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "observed" | "selected">("all");
  const [limit, setLimit] = useState(PAGE_SIZE);
  const matches = useMemo(() => {
    const terms = search.toLocaleLowerCase("uk-UA").trim().split(/\s+/).filter(Boolean);
    return inventory.items
      .filter((item) => {
        if (filter === "observed" && item.channel_ref_id !== null) return false;
        if (filter === "selected" && !selected.has(dashboardItemIdentity(item))) return false;
        const text = [
          deviceName(item),
          item.equipment_id,
          item.channel_id,
          item.channel_name,
          item.climate_chamber_code,
          item.climate_chamber_name,
          item.metric,
          item.native_unit,
        ]
          .join(" ")
          .toLocaleLowerCase("uk-UA");
        return terms.every((term) => text.includes(term));
      })
      .sort(
        (a, b) =>
          Number(b.channel_ref_id === null) - Number(a.channel_ref_id === null) ||
          deviceName(a).localeCompare(deviceName(b), "uk-UA", { numeric: true }),
      );
  }, [inventory.items, search, filter, selected]);
  const devices = new Map<string, LiveDashboardInventoryItem[]>();
  for (const item of matches.slice(0, limit)) {
    const key = JSON.stringify([item.node_id, item.equipment_id]);
    const group = devices.get(key);
    if (group) group.push(item);
    else devices.set(key, [item]);
  }

  return (
    <section
      aria-labelledby="dashboard-channels-title"
      className="min-w-0 rounded-3xl border border-white/10 bg-[#0a192b] p-4 sm:p-6 xl:col-start-2 xl:row-span-2 xl:row-start-1"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="dashboard-channels-title" className="text-xl font-semibold tracking-tight text-white">
          Додати канали
        </h2>
        <button
          type="button"
          onClick={inventory.retry}
          disabled={inventory.status === "loading"}
          className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-slate-300 hover:bg-white/5 focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:opacity-50"
        >
          <RefreshCw className="size-4" aria-hidden="true" />
          Оновити
        </button>
      </div>
      <div className="relative mt-4">
        <Search
          className="pointer-events-none absolute top-3.5 left-3.5 size-4 text-slate-400"
          aria-hidden="true"
        />
        <input
          type="search"
          aria-label="Пошук"
          placeholder="Прилад, датчик, показник або одиниця"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setLimit(PAGE_SIZE);
          }}
          className="h-11 w-full min-w-0 rounded-xl border border-white/10 bg-[#061321] pr-3 pl-10 text-sm text-white placeholder:text-slate-400 focus-visible:outline-2 focus-visible:outline-cyan-300"
        />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {(
          [
            ["all", "Усі канали"],
            ["observed", "Поза камерами"],
            ["selected", "Обрані"],
          ] as const
        ).map(([value, title]) => (
          <button
            key={value}
            type="button"
            aria-pressed={filter === value}
            onClick={() => {
              setFilter(value);
              setLimit(PAGE_SIZE);
            }}
            className="min-h-10 rounded-full border border-white/10 px-3 text-sm text-slate-300 hover:bg-white/5 focus-visible:outline-2 focus-visible:outline-cyan-300 aria-pressed:border-cyan-300/30 aria-pressed:bg-cyan-300/10 aria-pressed:text-cyan-100"
          >
            {title}
          </button>
        ))}
        <span
          data-testid="telemetry-selection-count"
          aria-live="polite"
          className="ml-auto text-sm text-cyan-200 tabular-nums"
        >
          {count} / {LIVE_DASHBOARD_MAX_ITEMS}
        </span>
      </div>

      <div
        aria-label="Список каналів"
        className="mt-5 max-h-[min(55dvh,32rem)] space-y-3 overflow-y-auto pr-1"
      >
        {inventory.status === "loading" ? (
          <p role="status" className="text-sm text-slate-300">
            Завантажую канали…
          </p>
        ) : null}
        {inventory.status === "error" ? (
          <p role="alert" className="text-sm text-rose-200">
            Не вдалося завантажити канали. Спробуйте оновити список.
          </p>
        ) : null}
        {inventory.status === "ready" && matches.length === 0 ? (
          <p className="rounded-xl border border-dashed border-white/15 p-4 text-sm text-slate-300">
            {inventory.items.length === 0 ? "Немає доступних каналів." : "За цими умовами каналів немає."}
          </p>
        ) : null}
        {[...devices].map(([key, items]) => (
          <div key={key} className="overflow-hidden rounded-2xl border border-white/10 bg-[#081524]">
            <header className="border-b border-white/10 bg-white/[0.035] px-3.5 py-2.5">
              <h3 className="text-sm font-semibold break-words text-slate-100">{deviceName(items[0])}</h3>
              <p className="text-xs break-all text-slate-400">
                {items[0].climate_chamber_code ?? items[0].equipment_id} · {items[0].node_id}
              </p>
            </header>
            <ul className="divide-y divide-white/[0.07]">
              {items.map((item) => {
                const checked = selected.has(dashboardItemIdentity(item));
                return (
                  <li key={dashboardItemIdentity(item)}>
                    <button
                      type="button"
                      aria-pressed={checked}
                      onClick={() => onToggle(item)}
                      disabled={!checked && count >= LIVE_DASHBOARD_MAX_ITEMS}
                      className="flex min-h-12 w-full min-w-0 items-center gap-3 px-3.5 py-2 text-left hover:bg-white/5 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-cyan-300 disabled:opacity-40 aria-pressed:bg-cyan-300/10"
                    >
                      <span
                        className={`grid size-7 shrink-0 place-items-center rounded-lg border ${checked ? "border-cyan-300/30 text-cyan-200" : "border-white/15 text-slate-400"}`}
                      >
                        {checked ? (
                          <Check className="size-4" aria-hidden="true" />
                        ) : (
                          <Plus className="size-4" aria-hidden="true" />
                        )}
                      </span>
                      <span className="min-w-0 flex-1 text-sm font-medium break-all text-slate-100">
                        {item.channel_name}
                      </span>
                      <span className="max-w-[40%] shrink-0 text-right text-xs break-words text-slate-400">
                        {item.metric} {item.native_unit && `· ${item.native_unit}`}
                        {item.latest === null ? <span className="block">Без вимірювань</span> : null}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
        {matches.length > limit ? (
          <button
            type="button"
            onClick={() => setLimit((current) => current + PAGE_SIZE)}
            className="min-h-10 w-full rounded-xl border border-white/10 text-sm text-cyan-200 hover:bg-cyan-400/10 focus-visible:outline-2 focus-visible:outline-cyan-300"
          >
            Показати ще · {matches.length - limit}
          </button>
        ) : null}
      </div>
    </section>
  );
}
