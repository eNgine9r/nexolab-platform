"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Boxes,
  CircleDashed,
  Cpu,
  ExternalLink,
  Eye,
  FilterX,
  Gauge,
  LoaderCircle,
  RefreshCcw,
  Refrigerator,
  Search,
  Thermometer,
} from "lucide-react";
import { clsx } from "clsx";

import {
  calibrationLabel,
  categoryLabel,
  EquipmentAssetDetails,
  statusLabel,
} from "@/components/equipment/equipment-asset-details";
import {
  collectEquipmentRegistryOptions,
  defaultEquipmentRegistryFilters,
  filterEquipmentRegistry,
  summarizeEquipmentRegistry,
  type EquipmentAssetCategory,
  type EquipmentCalibrationStatus,
  type EquipmentRegistryAsset,
  type EquipmentRegistryFailure,
  type EquipmentRegistryFilters,
} from "@/features/equipment/asset-registry";
import type { EquipmentRegistryState } from "@/hooks/use-equipment-registry";

const categories = new Set([
  "all",
  "refrigeration-equipment",
  "temperature-controller",
  "energy-meter",
  "physical-sensor",
]);
const calibrations = new Set(["all", "not-applicable", "untracked", "current", "due", "expired"]);
const filterParameters = new Set(["q", "category", "chamber", "manufacturer", "status", "calibration"]);

export function EquipmentRegistryCatalog({
  state,
  assets,
  failures,
  error,
  onRetry,
}: {
  state: EquipmentRegistryState;
  assets: EquipmentRegistryAsset[];
  failures: EquipmentRegistryFailure[];
  error: string | null;
  onRetry: () => void;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const filters = readFilters(searchParams);
  const options = useMemo(() => collectEquipmentRegistryOptions(assets), [assets]);
  const summary = useMemo(() => summarizeEquipmentRegistry(assets), [assets]);
  const filteredAssets = useMemo(() => filterEquipmentRegistry(assets, filters), [assets, filters]);
  const selectedAsset = assets.find((asset) => asset.key === selectedKey) ?? null;
  const activeFilterCount = countActiveFilters(filters);

  const updateFilter = (key: keyof EquipmentRegistryFilters, value: string) => {
    const next = new URLSearchParams(searchParams.toString());
    const parameter = filterParameter(key);
    if (!value || value === "all") next.delete(parameter);
    else next.set(parameter, value);
    router.replace(next.size > 0 ? `${pathname}?${next.toString()}` : pathname, { scroll: false });
  };

  const clearFilters = () => {
    const next = new URLSearchParams(searchParams.toString());
    for (const key of filterParameters) next.delete(key);
    const href = next.size > 0 ? `${pathname}?${next.toString()}` : pathname;
    window.location.replace(href);
  };

  return (
    <div className="space-y-4">
      <section className="rounded-3xl border border-cyan-300/10 bg-[#08182e]/90 p-4 shadow-xl shadow-black/10 sm:p-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <div className="flex items-center gap-2 text-[10px] font-semibold tracking-[0.2em] text-cyan-300 uppercase">
              <Boxes className="h-4 w-4" />
              Asset and metrology registry
            </div>
            <h1 className="mt-2 text-2xl font-semibold text-white">Обладнання та метрологія</h1>
            <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-400">
              Єдиний read-only реєстр холодильного обладнання, вимірювальних пристроїв і фізичних датчиків.
              Відображаються лише дані, які фактично зберігає локальна NEXOLAB система.
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-400">
            {state === "refreshing" ? <LoaderCircle className="h-4 w-4 animate-spin text-cyan-300" /> : null}
            <span>
              Показано <strong className="text-white">{filteredAssets.length}</strong> із {assets.length}
            </span>
            <button
              type="button"
              aria-label="Оновити реєстр обладнання"
              title="Оновити"
              onClick={onRetry}
              className="grid h-9 w-9 place-items-center rounded-xl border border-white/10 text-slate-300 hover:bg-white/[0.06] hover:text-white focus:ring-2 focus:ring-cyan-300 focus:outline-none"
            >
              <RefreshCcw className={clsx("h-4 w-4", state === "refreshing" && "animate-spin")} />
            </button>
          </div>
        </div>

        <div className="mt-5 grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
          <SummaryMetric label="Усього активів" value={summary.total} icon={Boxes} />
          <SummaryMetric label="Холодильне" value={summary.refrigerationEquipment} icon={Refrigerator} />
          <SummaryMetric label="Пристрої" value={summary.measurementDevices} icon={Cpu} />
          <SummaryMetric label="Фізичні датчики" value={summary.physicalSensors} icon={Thermometer} />
          <SummaryMetric
            label="Due / expired"
            value={summary.calibrationRisk}
            secondary={`${summary.calibrationUntracked} не відстежуються`}
            icon={AlertTriangle}
            emphasis={summary.calibrationRisk > 0}
          />
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-6">
          <label className="relative md:col-span-2 xl:col-span-2">
            <span className="sr-only">Пошук обладнання</span>
            <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <input
              value={filters.search}
              onChange={(event) => updateFilter("search", event.target.value)}
              placeholder="Код, inventory, business key, модель або серійний номер"
              className={inputClass}
            />
          </label>
          <label>
            <span className="sr-only">Категорія активу</span>
            <select
              value={filters.category}
              onChange={(event) => updateFilter("category", event.target.value)}
              className={selectClass}
            >
              <option value="all">Усі категорії</option>
              <option value="refrigeration-equipment">Холодильне обладнання</option>
              <option value="temperature-controller">Температурні контролери</option>
              <option value="energy-meter">Лічильники електроенергії</option>
              <option value="physical-sensor">Фізичні датчики</option>
            </select>
          </label>
          <FilterSelect
            label="Кліматична камера"
            value={filters.chamber}
            values={options.chambers}
            onChange={(value) => updateFilter("chamber", value)}
          />
          <FilterSelect
            label="Виробник"
            value={filters.manufacturer}
            values={options.manufacturers.map((value) => ({ value, label: value }))}
            onChange={(value) => updateFilter("manufacturer", value)}
          />
          <FilterSelect
            label="Статус"
            value={filters.status}
            values={options.statuses.map((value) => ({ value, label: statusLabel(value) }))}
            onChange={(value) => updateFilter("status", value)}
          />
          <label>
            <span className="sr-only">Статус калібрування</span>
            <select
              value={filters.calibration}
              onChange={(event) => updateFilter("calibration", event.target.value)}
              className={selectClass}
            >
              <option value="all">Усі calibration states</option>
              <option value="current">Актуальне</option>
              <option value="due">Наближається термін</option>
              <option value="expired">Прострочене</option>
              <option value="untracked">Не відстежується</option>
              <option value="not-applicable">Не застосовується</option>
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

      {failures.length > 0 ? (
        <section className="rounded-2xl border border-amber-300/15 bg-amber-400/[0.07] p-4" role="alert">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-200" />
            <div className="min-w-0 flex-1">
              <h2 className="text-sm font-semibold text-amber-100">Частина chamber catalog недоступна</h2>
              <p className="mt-1 text-xs leading-5 text-amber-100/70">
                Успішно завантажені активи залишаються доступними. Відсутні дані не підміняються demo
                fixtures.
              </p>
              <ul className="mt-2 space-y-1 text-xs text-amber-100/80">
                {failures.map((failure) => (
                  <li key={failure.chamberId}>
                    <strong>{failure.chamberLabel}:</strong> {failure.error}
                  </li>
                ))}
              </ul>
            </div>
            <button
              type="button"
              onClick={onRetry}
              className="shrink-0 rounded-xl border border-amber-200/20 px-3 py-2 text-xs font-semibold text-amber-100 hover:bg-amber-200/10 focus:ring-2 focus:ring-amber-200 focus:outline-none"
            >
              Повторити
            </button>
          </div>
        </section>
      ) : null}

      {state === "loading" || state === "idle" ? <RegistryLoading /> : null}
      {state === "error" && assets.length === 0 ? (
        <RegistryError message={error ?? "Реєстр обладнання недоступний."} onRetry={onRetry} />
      ) : null}
      {state !== "loading" && assets.length === 0 && state !== "error" ? <RegistryEmpty /> : null}
      {assets.length > 0 && filteredAssets.length === 0 ? (
        <section className="rounded-3xl border border-white/[0.07] bg-[#08182e]/80 p-8 text-center">
          <CircleDashed className="mx-auto h-8 w-8 text-slate-500" />
          <h2 className="mt-3 font-semibold text-white">За фільтрами активів не знайдено</h2>
          <button
            type="button"
            onClick={clearFilters}
            className="mt-3 text-sm text-cyan-300 hover:text-cyan-200"
          >
            Очистити фільтри
          </button>
        </section>
      ) : null}

      {filteredAssets.length > 0 ? (
        <section className="overflow-hidden rounded-3xl border border-white/[0.07] bg-[#08182e]/85">
          <div className="hidden overflow-x-auto lg:block">
            <table className="w-full min-w-[1050px] text-left text-xs">
              <thead className="border-b border-white/[0.07] bg-white/[0.025] text-[9px] tracking-[0.12em] text-slate-500 uppercase">
                <tr>
                  <th className="px-4 py-3">Актив</th>
                  <th className="px-4 py-3">Категорія</th>
                  <th className="px-4 py-3">Виробник / модель</th>
                  <th className="px-4 py-3">Розташування</th>
                  <th className="px-4 py-3">Статус</th>
                  <th className="px-4 py-3">Метрологія</th>
                  <th className="px-4 py-3 text-right">Дії</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.055]">
                {filteredAssets.map((asset) => (
                  <RegistryRow key={asset.key} asset={asset} onDetails={() => setSelectedKey(asset.key)} />
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid gap-3 p-3 lg:hidden">
            {filteredAssets.map((asset) => (
              <RegistryCard key={asset.key} asset={asset} onDetails={() => setSelectedKey(asset.key)} />
            ))}
          </div>
        </section>
      ) : null}

      {selectedAsset ? (
        <EquipmentAssetDetails asset={selectedAsset} onClose={() => setSelectedKey(null)} />
      ) : null}
    </div>
  );
}

function RegistryRow({ asset, onDetails }: { asset: EquipmentRegistryAsset; onDetails: () => void }) {
  const CategoryIcon = assetIcon(asset.category);
  return (
    <tr className="hover:bg-white/[0.025]">
      <td className="px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-cyan-300/10 bg-cyan-400/[0.06]">
            <CategoryIcon className="h-4 w-4 text-cyan-300" />
          </div>
          <div className="min-w-0">
            <p className="truncate font-semibold text-slate-100">{asset.displayName}</p>
            <p className="mt-0.5 truncate font-mono text-[10px] text-cyan-300">{asset.primaryIdentifier}</p>
          </div>
        </div>
      </td>
      <td className="px-4 py-3 text-slate-300">{categoryLabel(asset.category)}</td>
      <td className="px-4 py-3 text-slate-300">
        {asset.manufacturer ?? "Не задано"}
        <span className="block text-[10px] text-slate-500">{asset.model ?? asset.serialNumber ?? "—"}</span>
      </td>
      <td className="max-w-[260px] px-4 py-3 text-slate-300">
        <span className="block truncate">{asset.chamberLabel ?? "Не прив’язано"}</span>
        <span className="block truncate text-[10px] text-slate-500">{asset.locationLabel ?? "—"}</span>
      </td>
      <td className="px-4 py-3">
        <StatusSummary asset={asset} />
      </td>
      <td className="px-4 py-3">
        <CalibrationBadge value={asset.calibrationStatus} />
      </td>
      <td className="px-4 py-3">
        <div className="flex justify-end gap-2">
          <button
            type="button"
            aria-label={`Переглянути паспорт ${asset.primaryIdentifier}`}
            title="Переглянути"
            onClick={onDetails}
            className="grid h-9 w-9 place-items-center rounded-xl border border-white/10 text-slate-300 hover:bg-cyan-400/10 hover:text-cyan-200 focus:ring-2 focus:ring-cyan-300 focus:outline-none"
          >
            <Eye className="h-4 w-4" />
          </button>
          {asset.canonicalHref ? (
            <Link
              href={asset.canonicalHref}
              aria-label={`Відкрити канонічну картку ${asset.primaryIdentifier}`}
              title="Відкрити канонічну картку"
              className="grid h-9 w-9 place-items-center rounded-xl border border-blue-300/15 bg-blue-400/10 text-blue-100 hover:bg-blue-400/15 focus:ring-2 focus:ring-blue-300 focus:outline-none"
            >
              <ExternalLink className="h-4 w-4" />
            </Link>
          ) : null}
        </div>
      </td>
    </tr>
  );
}

function RegistryCard({ asset, onDetails }: { asset: EquipmentRegistryAsset; onDetails: () => void }) {
  const CategoryIcon = assetIcon(asset.category);
  return (
    <article className="rounded-2xl border border-white/[0.07] bg-[#091a31]/90 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-cyan-300/10 bg-cyan-400/[0.06]">
            <CategoryIcon className="h-4 w-4 text-cyan-300" />
          </div>
          <div className="min-w-0">
            <p className="truncate font-semibold text-white">{asset.displayName}</p>
            <p className="mt-1 truncate font-mono text-[10px] text-cyan-300">{asset.primaryIdentifier}</p>
            <p className="mt-1 text-[10px] text-slate-500">{categoryLabel(asset.category)}</p>
          </div>
        </div>
        <CalibrationBadge value={asset.calibrationStatus} />
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-2 text-xs">
        <CardMetadata label="Виробник" value={asset.manufacturer ?? "Не задано"} />
        <CardMetadata label="Модель" value={asset.model ?? "Не задано"} />
        <CardMetadata label="Камера" value={asset.chamberLabel ?? "Не прив’язано"} />
        <CardMetadata label="Статус" value={primaryStatus(asset)} />
      </dl>
      <div className="mt-4 flex justify-end gap-2 border-t border-white/[0.06] pt-3">
        <button
          type="button"
          onClick={onDetails}
          className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 px-3 text-xs font-semibold text-slate-200 hover:bg-white/[0.05] focus:ring-2 focus:ring-cyan-300 focus:outline-none"
        >
          <Eye className="h-4 w-4" />
          Паспорт
        </button>
        {asset.canonicalHref ? (
          <Link
            href={asset.canonicalHref}
            className="grid h-9 w-9 place-items-center rounded-xl border border-blue-300/15 bg-blue-400/10 text-blue-100 focus:ring-2 focus:ring-blue-300 focus:outline-none"
            aria-label={`Відкрити канонічну картку ${asset.primaryIdentifier}`}
          >
            <ExternalLink className="h-4 w-4" />
          </Link>
        ) : null}
      </div>
    </article>
  );
}

function StatusSummary({ asset }: { asset: EquipmentRegistryAsset }) {
  const values = [
    asset.lifecycleStatus,
    asset.healthStatus,
    asset.connectionStatus,
    asset.catalogStatus,
  ].filter((value): value is string => Boolean(value));
  return (
    <div className="flex max-w-[180px] flex-wrap gap-1">
      {values.map((value) => (
        <span
          key={value}
          className="rounded-full border border-white/10 bg-white/[0.035] px-2 py-1 text-[9px] text-slate-300"
        >
          {statusLabel(value)}
        </span>
      ))}
    </div>
  );
}

function CalibrationBadge({ value }: { value: EquipmentRegistryAsset["calibrationStatus"] }) {
  return (
    <span
      className={clsx(
        "inline-flex rounded-full border px-2 py-1 text-[9px] font-semibold",
        calibrationClass(value),
      )}
    >
      {calibrationLabel(value)}
    </span>
  );
}

function SummaryMetric({
  label,
  value,
  secondary,
  icon: Icon,
  emphasis = false,
}: {
  label: string;
  value: number;
  secondary?: string;
  icon: typeof Boxes;
  emphasis?: boolean;
}) {
  return (
    <div
      className={clsx(
        "rounded-2xl border p-3",
        emphasis ? "border-amber-300/15 bg-amber-400/[0.06]" : "border-white/[0.07] bg-white/[0.025]",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-[9px] tracking-[0.12em] text-slate-500 uppercase">{label}</p>
          <p className="mt-1 text-xl font-semibold text-white">{value}</p>
        </div>
        <Icon className={clsx("h-5 w-5", emphasis ? "text-amber-200" : "text-cyan-300")} />
      </div>
      {secondary ? <p className="mt-1 text-[9px] text-slate-500">{secondary}</p> : null}
    </div>
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
  values: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  return (
    <label>
      <span className="sr-only">{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} className={selectClass}>
        <option value="all">{label}: усі</option>
        {values.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function CardMetadata({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-xl border border-white/[0.05] bg-white/[0.02] p-2.5">
      <dt className="text-[9px] tracking-wide text-slate-500 uppercase">{label}</dt>
      <dd className="mt-1 truncate text-slate-200">{value}</dd>
    </div>
  );
}

function RegistryLoading() {
  return (
    <section
      className="grid gap-3 md:grid-cols-2 xl:grid-cols-3"
      aria-label="Завантаження реєстру обладнання"
    >
      {Array.from({ length: 6 }, (_, index) => (
        <div
          key={index}
          className="h-52 animate-pulse rounded-2xl border border-white/[0.06] bg-white/[0.03]"
        />
      ))}
    </section>
  );
}

function RegistryError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <section className="rounded-3xl border border-rose-300/15 bg-rose-400/10 p-6 text-rose-100" role="alert">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
        <div>
          <h2 className="font-semibold">Реєстр обладнання недоступний</h2>
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

function RegistryEmpty() {
  return (
    <section className="rounded-3xl border border-white/[0.07] bg-[#08182e]/80 p-8 text-center">
      <Boxes className="mx-auto h-9 w-9 text-slate-500" />
      <h2 className="mt-3 font-semibold text-white">Реєстр обладнання порожній</h2>
      <p className="mt-1 text-sm text-slate-500">Authenticated API не повернув підтримуваних активів.</p>
    </section>
  );
}

function readFilters(searchParams: Pick<URLSearchParams, "get">): EquipmentRegistryFilters {
  const defaults = defaultEquipmentRegistryFilters();
  const category = searchParams.get("category") ?? defaults.category;
  const calibration = searchParams.get("calibration") ?? defaults.calibration;
  return {
    search: searchParams.get("q") ?? "",
    category: categories.has(category) ? (category as EquipmentAssetCategory | "all") : "all",
    chamber: searchParams.get("chamber") ?? "all",
    manufacturer: searchParams.get("manufacturer") ?? "all",
    status: searchParams.get("status") ?? "all",
    calibration: calibrations.has(calibration) ? (calibration as EquipmentCalibrationStatus | "all") : "all",
  };
}

function filterParameter(key: keyof EquipmentRegistryFilters): string {
  return {
    search: "q",
    category: "category",
    chamber: "chamber",
    manufacturer: "manufacturer",
    status: "status",
    calibration: "calibration",
  }[key];
}

function countActiveFilters(filters: EquipmentRegistryFilters): number {
  return Object.values(filters).filter((value) => Boolean(value) && value !== "all").length;
}

function primaryStatus(asset: EquipmentRegistryAsset): string {
  return statusLabel(
    asset.lifecycleStatus ?? asset.connectionStatus ?? asset.catalogStatus ?? asset.healthStatus ?? "unknown",
  );
}

function assetIcon(category: EquipmentRegistryAsset["category"]) {
  return {
    "refrigeration-equipment": Refrigerator,
    "temperature-controller": Cpu,
    "energy-meter": Gauge,
    "physical-sensor": Thermometer,
  }[category];
}

function calibrationClass(value: EquipmentRegistryAsset["calibrationStatus"]): string {
  return {
    "not-applicable": "border-slate-300/10 bg-slate-400/[0.06] text-slate-400",
    untracked: "border-violet-300/15 bg-violet-400/10 text-violet-100",
    current: "border-emerald-300/15 bg-emerald-400/10 text-emerald-100",
    due: "border-amber-300/20 bg-amber-400/10 text-amber-100",
    expired: "border-rose-300/20 bg-rose-400/10 text-rose-100",
  }[value];
}

const inputClass =
  "h-11 w-full rounded-xl border border-white/[0.08] bg-[#06142a] pr-3 pl-10 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-cyan-300/35 focus:ring-2 focus:ring-cyan-300/10";
const selectClass =
  "h-11 w-full rounded-xl border border-white/[0.08] bg-[#06142a] px-3 text-xs text-slate-200 outline-none focus:border-cyan-300/35 focus:ring-2 focus:ring-cyan-300/10";
