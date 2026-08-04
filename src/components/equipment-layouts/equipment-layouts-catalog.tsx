"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Boxes,
  CircleDashed,
  ExternalLink,
  Eye,
  FilterX,
  ImageOff,
  Layers3,
  LoaderCircle,
  RefreshCcw,
  Search,
} from "lucide-react";
import { clsx } from "clsx";

import { EquipmentLayoutPreview } from "@/components/equipment-layouts/equipment-layout-preview";
import {
  collectLayoutCatalogOptions,
  defaultLayoutCatalogFilters,
  filterLayoutCatalog,
  type LayoutCatalogFilters,
  type LayoutCatalogItem,
  type LayoutCatalogReadyItem,
  type LayoutCatalogState,
} from "@/features/equipment-layouts/layout-catalog";
import type { EquipmentLayoutsCatalogState } from "@/hooks/use-equipment-layouts-catalog";

const lifecycleValues = new Set(["all", "active", "maintenance", "retired"]);
const layoutValues = new Set([
  "all",
  "published-current",
  "published-with-draft",
  "draft-only",
  "no-image",
  "empty",
  "failed",
]);

export function EquipmentLayoutsCatalog({
  state,
  items,
  error,
  onRetry,
}: {
  state: EquipmentLayoutsCatalogState;
  items: LayoutCatalogItem[];
  error: string | null;
  onRetry: () => void;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [previewEquipmentId, setPreviewEquipmentId] = useState<string | null>(null);
  const filters = readFilters(searchParams);
  const options = useMemo(() => collectLayoutCatalogOptions(items), [items]);
  const filteredItems = useMemo(() => filterLayoutCatalog(items, filters), [filters, items]);
  const previewItem = items.find(
    (item): item is LayoutCatalogReadyItem =>
      item.kind === "ready" && item.equipment.id === previewEquipmentId && item.published !== null,
  );
  const activeFilterCount = countActiveFilters(filters);

  const updateFilter = (key: keyof LayoutCatalogFilters, value: string) => {
    const next = new URLSearchParams(searchParams.toString());
    const parameter = filterParameter(key);
    if (!value || value === "all") next.delete(parameter);
    else next.set(parameter, value);
    router.replace(next.size > 0 ? `${pathname}?${next.toString()}` : pathname, { scroll: false });
  };

  const clearFilters = () => {
  const next = new URLSearchParams(searchParams.toString());
  for (const parameter of ["q", "lab", "zone", "chamber", "lifecycle", "layout"]) {
    next.delete(parameter);
  }
  const href = next.size > 0 ? `${pathname}?${next.toString()}` : pathname;
  window.history.replaceState(window.history.state, "", href);
};

  return (
    <div className="space-y-4">
      <section className="rounded-3xl border border-cyan-300/10 bg-[#08182e]/90 p-4 shadow-xl shadow-black/10 sm:p-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <div className="flex items-center gap-2 text-[10px] font-semibold tracking-[0.2em] text-cyan-300 uppercase">
              <Layers3 className="h-4 w-4" />
              Digital layouts catalog
            </div>
            <h1 className="mt-2 text-2xl font-semibold text-white">Схеми обладнання</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
              Організаційний каталог опублікованих схем і чернеток. Редагування залишається в канонічній
              картці холодильного обладнання.
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-400">
            {state === "refreshing" ? <LoaderCircle className="h-4 w-4 animate-spin text-cyan-300" /> : null}
            <span>
              Показано <strong className="text-white">{filteredItems.length}</strong> із {items.length}
            </span>
            <button
              type="button"
              aria-label="Оновити каталог схем"
              title="Оновити"
              onClick={onRetry}
              className="grid h-9 w-9 place-items-center rounded-xl border border-white/10 text-slate-300 hover:bg-white/[0.06] hover:text-white focus:ring-2 focus:ring-cyan-300 focus:outline-none"
            >
              <RefreshCcw className={clsx("h-4 w-4", state === "refreshing" && "animate-spin")} />
            </button>
          </div>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-7">
          <label className="relative md:col-span-2 xl:col-span-2">
            <span className="sr-only">Пошук схем обладнання</span>
            <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <input
              value={filters.search}
              onChange={(event) => updateFilter("search", event.target.value)}
              placeholder="Код, назва, модель або розташування"
              className={inputClass}
            />
          </label>
          <FilterSelect
            label="Лабораторія"
            value={filters.laboratory}
            values={options.laboratories}
            onChange={(value) => updateFilter("laboratory", value)}
          />
          <FilterSelect
            label="Зона"
            value={filters.zone}
            values={options.zones}
            onChange={(value) => updateFilter("zone", value)}
          />
          <FilterSelect
            label="Кліматична камера"
            value={filters.chamber}
            values={options.chambers}
            onChange={(value) => updateFilter("chamber", value)}
          />
          <label>
            <span className="sr-only">Життєвий цикл обладнання</span>
            <select
              value={filters.lifecycle}
              onChange={(event) => updateFilter("lifecycle", event.target.value)}
              className={selectClass}
            >
              <option value="all">Усі lifecycle</option>
              <option value="active">Активні</option>
              <option value="maintenance">Обслуговування</option>
              <option value="retired">Виведені</option>
            </select>
          </label>
          <label>
            <span className="sr-only">Стан схеми</span>
            <select
              value={filters.layout}
              onChange={(event) => updateFilter("layout", event.target.value)}
              className={selectClass}
            >
              <option value="all">Усі стани схем</option>
              {Object.entries(layoutStateLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>

        {activeFilterCount > 0 ? (
          <div className="mt-3 flex items-center justify-between gap-3 rounded-xl border border-blue-300/10 bg-blue-400/[0.05] px-3 py-2 text-xs text-blue-100">
            <span>Активних фільтрів: {activeFilterCount}</span>
            <button
              type="button"
              onClick={clearFilters}
              className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 font-medium hover:bg-white/[0.06] focus:ring-2 focus:ring-blue-300 focus:outline-none"
            >
              <FilterX className="h-3.5 w-3.5" />
              Очистити
            </button>
          </div>
        ) : null}
      </section>

      {state === "loading" || state === "idle" ? <CatalogLoading /> : null}
      {state === "error" && items.length === 0 ? (
        <CatalogError message={error ?? "Каталог схем недоступний."} onRetry={onRetry} />
      ) : null}
      {state !== "loading" && items.length === 0 && state !== "error" ? <CatalogEmpty /> : null}
      {items.length > 0 && filteredItems.length === 0 ? (
        <section className="rounded-3xl border border-white/[0.07] bg-[#08182e]/80 p-8 text-center">
          <CircleDashed className="mx-auto h-8 w-8 text-slate-500" />
          <h2 className="mt-3 font-semibold text-white">За фільтрами нічого не знайдено</h2>
          <button
            type="button"
            onClick={clearFilters}
            className="mt-3 text-sm text-cyan-300 hover:text-cyan-200"
          >
            Очистити фільтри
          </button>
        </section>
      ) : null}

      {filteredItems.length > 0 ? (
        <section className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3" aria-label="Каталог схем обладнання">
          {filteredItems.map((item) => (
            <LayoutCatalogCard
              key={item.equipment.id}
              item={item}
              onPreview={() => setPreviewEquipmentId(item.equipment.id)}
              onRetry={onRetry}
            />
          ))}
        </section>
      ) : null}

      {previewItem ? (
        <EquipmentLayoutPreview item={previewItem} onClose={() => setPreviewEquipmentId(null)} />
      ) : null}
    </div>
  );
}

function LayoutCatalogCard({
  item,
  onPreview,
  onRetry,
}: {
  item: LayoutCatalogItem;
  onPreview: () => void;
  onRetry: () => void;
}) {
  const equipment = item.equipment;
  const stateMeta = layoutStateMeta[item.layoutState];

  return (
    <article className="rounded-2xl border border-white/[0.07] bg-[#091a31]/90 p-4 shadow-lg shadow-black/10">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-[10px] font-semibold tracking-[0.16em] text-cyan-300 uppercase">
            {equipment.code}
          </p>
          <h2 className="mt-1 truncate text-base font-semibold text-white">{equipment.name}</h2>
          <p className="mt-1 truncate text-xs text-slate-500">{equipment.location}</p>
        </div>
        <span
          className={clsx(
            "shrink-0 rounded-full border px-2 py-1 text-[9px] font-semibold",
            stateMeta.className,
          )}
        >
          {stateMeta.label}
        </span>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-2 text-xs">
        <Metadata label="Лабораторія" value={equipment.laboratory ?? "Не задано"} />
        <Metadata label="Зона" value={equipment.zone ?? "Не задано"} />
        <Metadata label="Камера" value={equipment.climateChamberId ?? "Не задано"} />
        <Metadata label="Lifecycle" value={lifecycleLabel(equipment.lifecycleStatus)} />
      </dl>

      {item.kind === "failed" ? (
        <div
          className="mt-4 flex items-start gap-2 rounded-xl border border-rose-300/15 bg-rose-400/10 p-3 text-xs text-rose-100"
          role="alert"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p>{item.error}</p>
            <button
              type="button"
              onClick={onRetry}
              className="mt-2 font-semibold text-rose-200 underline underline-offset-4"
            >
              Повторити завантаження
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-4 grid grid-cols-3 gap-2 rounded-xl border border-white/[0.06] bg-white/[0.025] p-3 text-center">
          <Metric label="Draft" value={`v${item.draft.version}`} />
          <Metric label="Published" value={item.published ? `r${item.published.revision}` : "—"} />
          <Metric
            label="Позиції"
            value={String(item.published?.placements.length ?? item.draft.placements.length)}
          />
        </div>
      )}

      {item.kind === "ready" && item.published ? (
        <p className="mt-3 text-[10px] text-slate-500">
          {formatDateTime(item.published.publishedAt)} · {item.published.publishedBy}
        </p>
      ) : null}

      <div className="mt-4 flex items-center justify-end gap-2 border-t border-white/[0.06] pt-3">
        <button
          type="button"
          aria-label={`Переглянути опубліковану схему ${equipment.code}`}
          title="Read-only preview"
          disabled={item.kind !== "ready" || !item.published}
          onClick={onPreview}
          className="grid h-9 w-9 place-items-center rounded-xl border border-white/10 text-slate-300 focus:ring-2 focus:ring-cyan-300 focus:outline-none enabled:hover:bg-cyan-400/10 enabled:hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-35"
        >
          {item.kind === "ready" && item.published ? (
            <Eye className="h-4 w-4" />
          ) : (
            <ImageOff className="h-4 w-4" />
          )}
        </button>
        <Link
          href={`/refrigeration/${encodeURIComponent(equipment.id)}`}
          aria-label={`Відкрити картку обладнання ${equipment.code}`}
          title="Відкрити канонічну картку"
          className="inline-flex h-9 items-center gap-2 rounded-xl border border-blue-300/15 bg-blue-400/10 px-3 text-xs font-semibold text-blue-100 hover:bg-blue-400/15 focus:ring-2 focus:ring-blue-300 focus:outline-none"
        >
          Картка
          <ExternalLink className="h-3.5 w-3.5" />
        </Link>
      </div>
    </article>
  );
}

function FilterSelect({
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
    <label>
      <span className="sr-only">{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} className={selectClass}>
        <option value="all">{label}: усі</option>
        {values.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function Metadata({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-white/[0.05] bg-white/[0.02] px-2.5 py-2">
      <dt className="text-[9px] tracking-wide text-slate-500 uppercase">{label}</dt>
      <dd className="mt-1 truncate font-medium text-slate-200">{value}</dd>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[9px] text-slate-500 uppercase">{label}</dt>
      <dd className="mt-1 font-semibold text-slate-100">{value}</dd>
    </div>
  );
}

function CatalogLoading() {
  return (
    <section className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3" aria-label="Завантаження каталогу">
      {Array.from({ length: 6 }, (_, index) => (
        <div
          key={index}
          className="h-64 animate-pulse rounded-2xl border border-white/[0.06] bg-white/[0.03]"
        />
      ))}
    </section>
  );
}

function CatalogError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <section className="rounded-3xl border border-rose-300/15 bg-rose-400/10 p-6 text-rose-100" role="alert">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
        <div>
          <h2 className="font-semibold">Каталог схем недоступний</h2>
          <p className="mt-1 text-sm text-rose-100/80">{message}</p>
          <button
            type="button"
            onClick={onRetry}
            className="mt-4 inline-flex items-center gap-2 rounded-xl bg-rose-200 px-3 py-2 text-xs font-semibold text-rose-950"
          >
            <RefreshCcw className="h-4 w-4" />
            Повторити
          </button>
        </div>
      </div>
    </section>
  );
}

function CatalogEmpty() {
  return (
    <section className="rounded-3xl border border-white/[0.07] bg-[#08182e]/80 p-8 text-center">
      <Boxes className="mx-auto h-9 w-9 text-slate-500" />
      <h2 className="mt-3 font-semibold text-white">Каталог обладнання порожній</h2>
      <p className="mt-1 text-sm text-slate-500">Активне обладнання з authenticated API не повернуто.</p>
    </section>
  );
}

function readFilters(searchParams: URLSearchParams | ReadonlyURLSearchParamsLike): LayoutCatalogFilters {
  const defaults = defaultLayoutCatalogFilters();
  const lifecycle = searchParams.get("lifecycle") ?? defaults.lifecycle;
  const layout = searchParams.get("layout") ?? defaults.layout;
  return {
    search: searchParams.get("q") ?? "",
    laboratory: searchParams.get("lab") ?? "all",
    zone: searchParams.get("zone") ?? "all",
    chamber: searchParams.get("chamber") ?? "all",
    lifecycle: lifecycleValues.has(lifecycle) ? (lifecycle as LayoutCatalogFilters["lifecycle"]) : "all",
    layout: layoutValues.has(layout) ? (layout as LayoutCatalogFilters["layout"]) : "all",
  };
}

type ReadonlyURLSearchParamsLike = Pick<URLSearchParams, "get">;

function filterParameter(key: keyof LayoutCatalogFilters): string {
  return {
    search: "q",
    laboratory: "lab",
    zone: "zone",
    chamber: "chamber",
    lifecycle: "lifecycle",
    layout: "layout",
  }[key];
}

function countActiveFilters(filters: LayoutCatalogFilters): number {
  return Object.entries(filters).filter(([, value]) => Boolean(value) && value !== "all").length;
}

function lifecycleLabel(value: string): string {
  return (
    {
      active: "Активне",
      maintenance: "Обслуговування",
      retired: "Виведене",
    }[value] ?? value
  );
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("uk-UA", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

const layoutStateLabels: Record<Exclude<LayoutCatalogState, "failed"> | "failed", string> = {
  "published-current": "Опублікована · актуальна",
  "published-with-draft": "Є нові зміни",
  "draft-only": "Лише чернетка",
  "no-image": "Немає фото",
  empty: "Порожня схема",
  failed: "Помилка summary",
};

const layoutStateMeta: Record<LayoutCatalogState, { label: string; className: string }> = {
  "published-current": {
    label: layoutStateLabels["published-current"],
    className: "border-emerald-300/20 bg-emerald-400/10 text-emerald-200",
  },
  "published-with-draft": {
    label: layoutStateLabels["published-with-draft"],
    className: "border-amber-300/20 bg-amber-400/10 text-amber-100",
  },
  "draft-only": {
    label: layoutStateLabels["draft-only"],
    className: "border-blue-300/20 bg-blue-400/10 text-blue-100",
  },
  "no-image": {
    label: layoutStateLabels["no-image"],
    className: "border-violet-300/20 bg-violet-400/10 text-violet-100",
  },
  empty: {
    label: layoutStateLabels.empty,
    className: "border-slate-300/15 bg-slate-400/10 text-slate-300",
  },
  failed: {
    label: layoutStateLabels.failed,
    className: "border-rose-300/20 bg-rose-400/10 text-rose-100",
  },
};

const inputClass =
  "h-11 w-full rounded-xl border border-white/[0.08] bg-[#06142a] pr-3 pl-10 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-cyan-300/35 focus:ring-2 focus:ring-cyan-300/10";
const selectClass =
  "h-11 w-full rounded-xl border border-white/[0.08] bg-[#06142a] px-3 text-xs text-slate-200 outline-none focus:border-cyan-300/35 focus:ring-2 focus:ring-cyan-300/10";
