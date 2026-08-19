"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Boxes,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleDashed,
  Columns3,
  Cpu,
  ExternalLink,
  Eye,
  FilterX,
  Gauge,
  LayoutList,
  LoaderCircle,
  RefreshCcw,
  Refrigerator,
  Search,
  SlidersHorizontal,
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
import {
  equipmentAssetHasIssue,
  EQUIPMENT_REGISTRY_COLUMNS,
  EQUIPMENT_REGISTRY_PAGE_SIZE,
  filterEquipmentWorkspaceRisk,
  groupEquipmentWorkspace,
  paginateEquipmentWorkspace,
  sortEquipmentWorkspace,
  type EquipmentRegistryColumn,
  type EquipmentRegistryGroup,
  type EquipmentRegistryGroupMode,
  type EquipmentRegistryRiskFilter,
  type EquipmentRegistrySortDirection,
  type EquipmentRegistrySortKey,
} from "@/features/equipment/workspace";
import {
  DEFAULT_EQUIPMENT_WORKSPACE_COLUMNS,
  EQUIPMENT_WORKSPACE_COLUMNS_STORAGE_KEY,
  parseEquipmentWorkspaceColumns,
  serializeEquipmentWorkspaceColumns,
} from "@/features/equipment/workspace-preferences";
import type { SettingsTableDensity } from "@/features/settings/preferences";
import type { EquipmentRegistryState } from "@/hooks/use-equipment-registry";
import { useSettingsPreferences } from "@/hooks/use-settings-preferences";

const categories = new Set([
  "all",
  "refrigeration-equipment",
  "temperature-controller",
  "energy-meter",
  "physical-sensor",
]);
const calibrations = new Set(["all", "not-applicable", "untracked", "current", "due", "expired"]);
const risks = new Set<EquipmentRegistryRiskFilter>([
  "all",
  "offline",
  "attention",
  "calibration-risk",
  "calibration-untracked",
]);
const sortKeys = new Set<EquipmentRegistrySortKey>([
  "identity",
  "category",
  "manufacturer",
  "location",
  "status",
  "calibration",
]);
const groupModes = new Set<EquipmentRegistryGroupMode>([
  "none",
  "chamber",
  "category",
  "manufacturer",
  "state",
]);
const filterParameters = new Set([
  "q",
  "category",
  "chamber",
  "manufacturer",
  "status",
  "calibration",
  "risk",
]);

export function EquipmentRegistryCatalog({
  state,
  assets,
  failures,
  error,
  progress,
  onRetry,
}: {
  state: EquipmentRegistryState;
  assets: EquipmentRegistryAsset[];
  failures: EquipmentRegistryFailure[];
  error: string | null;
  progress?: { completedChambers: number; totalChambers: number } | null;
  onRetry: () => void;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const queryRef = useRef(searchParams.toString());
  const settings = useSettingsPreferences();
  const [filters, setFilters] = useState<EquipmentRegistryFilters>(() => readFilters(searchParams));
  const [risk, setRisk] = useState<EquipmentRegistryRiskFilter>(() => readRisk(searchParams));
  const [sortKey, setSortKey] = useState<EquipmentRegistrySortKey>(() => readSortKey(searchParams));
  const [sortDirection, setSortDirection] = useState<EquipmentRegistrySortDirection>(() =>
    readSortDirection(searchParams),
  );
  const [groupMode, setGroupMode] = useState<EquipmentRegistryGroupMode>(() => readGroupMode(searchParams));
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [columnPickerOpen, setColumnPickerOpen] = useState(false);
  const [visibleColumns, setVisibleColumns] = useState<EquipmentRegistryColumn[]>([
    ...DEFAULT_EQUIPMENT_WORKSPACE_COLUMNS,
  ]);

  const density = settings.preferences.tableDensity;
  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      try {
        setVisibleColumns(
          parseEquipmentWorkspaceColumns(
            window.localStorage.getItem(EQUIPMENT_WORKSPACE_COLUMNS_STORAGE_KEY),
          ),
        );
      } catch {
        setVisibleColumns([...DEFAULT_EQUIPMENT_WORKSPACE_COLUMNS]);
      }
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, []);

  const options = useMemo(() => collectEquipmentRegistryOptions(assets), [assets]);
  const summary = useMemo(() => summarizeEquipmentRegistry(assets), [assets]);
  const baseFilteredAssets = useMemo(() => filterEquipmentRegistry(assets, filters), [assets, filters]);
  const filteredAssets = useMemo(
    () => filterEquipmentWorkspaceRisk(baseFilteredAssets, risk),
    [baseFilteredAssets, risk],
  );
  const sortedAssets = useMemo(
    () => sortEquipmentWorkspace(filteredAssets, sortKey, sortDirection),
    [filteredAssets, sortDirection, sortKey],
  );
  const pageResult = useMemo(
    () => paginateEquipmentWorkspace(sortedAssets, page, EQUIPMENT_REGISTRY_PAGE_SIZE),
    [page, sortedAssets],
  );
  const allGroups = useMemo(
    () => groupEquipmentWorkspace(sortedAssets, groupMode),
    [groupMode, sortedAssets],
  );
  const pageGroups = useMemo(
    () => groupEquipmentWorkspace(pageResult.items, groupMode),
    [groupMode, pageResult.items],
  );
  const groupTotals = useMemo(() => new Map(allGroups.map((group) => [group.key, group])), [allGroups]);
  const selectedIndex = sortedAssets.findIndex((asset) => asset.key === selectedKey);
  const selectedAsset = selectedIndex >= 0 ? sortedAssets[selectedIndex] : null;
  const activeFilterCount = countActiveFilters(filters, risk);
  const resultRange = sortedAssets.length === 0 ? "0" : `${pageResult.start + 1}–${pageResult.end}`;
  const replaceQuery = (mutate: (next: URLSearchParams) => void): URLSearchParams => {
    setPage(0);
    const next = new URLSearchParams(queryRef.current);
    mutate(next);
    queryRef.current = next.toString();
    const href = next.size > 0 ? `${pathname}?${next.toString()}` : pathname;
    window.history.replaceState(window.history.state, "", href);
    return next;
  };

  const updateFilter = (key: keyof EquipmentRegistryFilters, value: string) => {
    const next = replaceQuery((query) => {
      const parameter = filterParameter(key);
      if (!value || value === "all") query.delete(parameter);
      else query.set(parameter, value);
    });
    setFilters(readFilters(next));
  };

  const updateRisk = (value: EquipmentRegistryRiskFilter) => {
    const next = replaceQuery((query) => {
      if (value === "all" || value === risk) query.delete("risk");
      else query.set("risk", value);
    });
    setRisk(readRisk(next));
  };

  const updateSort = (key: EquipmentRegistrySortKey) => {
    const next = replaceQuery((query) => {
      const direction = sortKey === key && sortDirection === "asc" ? "desc" : "asc";
      query.set("sort", key);
      query.set("order", direction);
    });
    setSortKey(readSortKey(next));
    setSortDirection(readSortDirection(next));
  };

  const updateGroup = (value: EquipmentRegistryGroupMode) => {
    const next = replaceQuery((query) => {
      if (value === "none") query.delete("group");
      else query.set("group", value);
    });
    setGroupMode(readGroupMode(next));
  };

  const clearFilters = () => {
    const next = replaceQuery((query) => {
      for (const key of filterParameters) query.delete(key);
    });
    setFilters(readFilters(next));
    setRisk(readRisk(next));
  };

  const toggleColumn = (column: EquipmentRegistryColumn) => {
    setVisibleColumns((current) => {
      const next = current.includes(column)
        ? current.filter((value) => value !== column)
        : [...current, column];
      const ordered = EQUIPMENT_REGISTRY_COLUMNS.filter((value) => next.includes(value));
      try {
        window.localStorage.setItem(
          EQUIPMENT_WORKSPACE_COLUMNS_STORAGE_KEY,
          serializeEquipmentWorkspaceColumns(ordered),
        );
      } catch {
        // Column preferences are optional and never affect acquisition/runtime behavior.
      }
      return ordered;
    });
  };

  const toggleGroup = (key: string) => {
    setCollapsedGroups((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
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
              Масштабований read-only workspace холодильного обладнання, вимірювальних пристроїв і фізичних
              датчиків. Відображаються лише дані, які фактично зберігає локальна NEXOLAB система.
            </p>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2 text-xs text-slate-400">
            {state === "refreshing" || state === "loading" ? (
              <LoaderCircle className="h-4 w-4 animate-spin text-cyan-300" />
            ) : null}
            {progress && progress.totalChambers > 0 && progress.completedChambers < progress.totalChambers ? (
              <span className="rounded-lg border border-cyan-300/10 bg-cyan-400/[0.05] px-2 py-1 text-cyan-100">
                Каталоги {progress.completedChambers}/{progress.totalChambers}
              </span>
            ) : null}
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

        <div className="mt-3 flex flex-wrap items-center gap-2" aria-label="Швидкі ризик-фільтри">
          <span className="mr-1 text-[10px] font-semibold tracking-[0.12em] text-slate-500 uppercase">
            Ризики
          </span>
          <QuickRiskChip
            label="Офлайн"
            value="offline"
            active={risk === "offline"}
            count={filterEquipmentWorkspaceRisk(assets, "offline").length}
            onClick={updateRisk}
          />
          <QuickRiskChip
            label="Тривога / warning"
            value="attention"
            active={risk === "attention"}
            count={filterEquipmentWorkspaceRisk(assets, "attention").length}
            onClick={updateRisk}
          />
          <QuickRiskChip
            label="Калібрування due / expired"
            value="calibration-risk"
            active={risk === "calibration-risk"}
            count={filterEquipmentWorkspaceRisk(assets, "calibration-risk").length}
            onClick={updateRisk}
          />
          <QuickRiskChip
            label="Калібрування untracked"
            value="calibration-untracked"
            active={risk === "calibration-untracked"}
            count={filterEquipmentWorkspaceRisk(assets, "calibration-untracked").length}
            onClick={updateRisk}
          />
        </div>

        <div className="mt-3 flex flex-col gap-2 rounded-2xl border border-white/[0.06] bg-[#06142a]/55 p-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 text-xs text-slate-400">
              <LayoutList className="h-4 w-4 text-cyan-300" />
              <span>Групування</span>
              <select
                aria-label="Групування реєстру"
                value={groupMode}
                onChange={(event) => updateGroup(event.target.value as EquipmentRegistryGroupMode)}
                className="h-9 rounded-lg border border-white/[0.08] bg-[#08182e] px-2 text-xs text-slate-200"
              >
                <option value="none">Без групування</option>
                <option value="chamber">Камера / локація</option>
                <option value="category">Категорія</option>
                <option value="manufacturer">Виробник</option>
                <option value="state">Lifecycle / connectivity</option>
              </select>
            </label>
            <button
              type="button"
              aria-pressed={density === "compact"}
              onClick={() =>
                settings.updatePreference("tableDensity", density === "compact" ? "comfortable" : "compact")
              }
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-white/[0.08] px-3 text-xs text-slate-300 hover:bg-white/[0.04] focus:ring-2 focus:ring-cyan-300 focus:outline-none"
            >
              <SlidersHorizontal className="h-4 w-4" />
              {density === "compact" ? "Компактна" : "Комфортна"} щільність
            </button>
            <div className="relative">
              <button
                type="button"
                aria-expanded={columnPickerOpen}
                aria-controls="equipment-column-picker"
                onClick={() => setColumnPickerOpen((value) => !value)}
                className="inline-flex h-9 items-center gap-2 rounded-lg border border-white/[0.08] px-3 text-xs text-slate-300 hover:bg-white/[0.04] focus:ring-2 focus:ring-cyan-300 focus:outline-none"
              >
                <Columns3 className="h-4 w-4" />
                Колонки {visibleColumns.length}/{EQUIPMENT_REGISTRY_COLUMNS.length}
              </button>
              {columnPickerOpen ? (
                <div
                  id="equipment-column-picker"
                  className="absolute top-11 left-0 z-40 w-60 rounded-2xl border border-white/10 bg-[#091a31] p-3 shadow-2xl shadow-black/50"
                >
                  <p className="mb-2 text-[10px] tracking-[0.1em] text-slate-500 uppercase">Видимі колонки</p>
                  {EQUIPMENT_REGISTRY_COLUMNS.map((column) => (
                    <label
                      key={column}
                      className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-2 text-xs text-slate-300 hover:bg-white/[0.04]"
                    >
                      <input
                        type="checkbox"
                        checked={visibleColumns.includes(column)}
                        onChange={() => toggleColumn(column)}
                      />
                      {columnLabel(column)}
                    </label>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-slate-400">
            <span>
              Рядки <strong className="text-slate-200">{resultRange}</strong> · сторінка {pageResult.page + 1}
              /{pageResult.pageCount}
            </span>
            {activeFilterCount > 0 ? (
              <button
                type="button"
                onClick={clearFilters}
                aria-label="Очистити активні фільтри"
                className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 font-medium text-cyan-200 hover:bg-white/[0.06] focus:ring-2 focus:ring-cyan-300 focus:outline-none"
              >
                <FilterX className="h-3.5 w-3.5" />
                Очистити {activeFilterCount} фільтрів
              </button>
            ) : null}
          </div>
        </div>
      </section>

      {failures.length > 0 ? <PartialFailures failures={failures} onRetry={onRetry} /> : null}

      {(state === "loading" || state === "idle") && assets.length === 0 ? <RegistryLoading /> : null}
      {state === "error" && assets.length === 0 ? (
        <RegistryError message={error ?? "Реєстр обладнання недоступний."} onRetry={onRetry} />
      ) : null}
      {state === "ready" && assets.length === 0 ? <RegistryEmpty /> : null}
      {assets.length > 0 && filteredAssets.length === 0 ? (
        <section className="rounded-3xl border border-white/[0.07] bg-[#08182e]/80 p-8 text-center">
          <CircleDashed className="mx-auto h-8 w-8 text-slate-500" />
          <h2 className="mt-3 font-semibold text-white">За фільтрами активів не знайдено</h2>
          <button
            type="button"
            onClick={clearFilters}
            aria-label="Очистити фільтри порожнього результату"
            className="mt-3 inline-block text-sm text-cyan-300 hover:text-cyan-200 focus:ring-2 focus:ring-cyan-300 focus:outline-none"
          >
            Очистити фільтри
          </button>
        </section>
      ) : null}

      {filteredAssets.length > 0 ? (
        <RegistryResults
          groups={pageGroups}
          groupTotals={groupTotals}
          grouped={groupMode !== "none"}
          collapsedGroups={collapsedGroups}
          onToggleGroup={toggleGroup}
          visibleColumns={visibleColumns}
          density={density}
          selectedKey={selectedKey}
          onDetails={setSelectedKey}
          sortKey={sortKey}
          sortDirection={sortDirection}
          onSort={updateSort}
        />
      ) : null}

      {pageResult.pageCount > 1 ? (
        <nav
          aria-label="Сторінки реєстру обладнання"
          className="flex items-center justify-center gap-3 rounded-2xl border border-white/[0.07] bg-[#08182e]/80 p-3"
        >
          <button
            type="button"
            disabled={pageResult.page === 0}
            onClick={() => setPage(Math.max(0, pageResult.page - 1))}
            className={pageButtonClass}
          >
            <ChevronLeft className="h-4 w-4" /> Попередня
          </button>
          <span className="text-xs text-slate-400">
            {pageResult.start + 1}–{pageResult.end} із {sortedAssets.length}
          </span>
          <button
            type="button"
            disabled={pageResult.page >= pageResult.pageCount - 1}
            onClick={() => setPage(Math.min(pageResult.pageCount - 1, pageResult.page + 1))}
            className={pageButtonClass}
          >
            Наступна <ChevronRight className="h-4 w-4" />
          </button>
        </nav>
      ) : null}

      {selectedAsset ? (
        <EquipmentAssetDetails
          asset={selectedAsset}
          onClose={() => setSelectedKey(null)}
          hasPrevious={selectedIndex > 0}
          hasNext={selectedIndex >= 0 && selectedIndex < sortedAssets.length - 1}
          onPrevious={() => selectedIndex > 0 && setSelectedKey(sortedAssets[selectedIndex - 1].key)}
          onNext={() =>
            selectedIndex >= 0 &&
            selectedIndex < sortedAssets.length - 1 &&
            setSelectedKey(sortedAssets[selectedIndex + 1].key)
          }
        />
      ) : null}
    </div>
  );
}

function RegistryResults({
  groups,
  groupTotals,
  grouped,
  collapsedGroups,
  onToggleGroup,
  visibleColumns,
  density,
  selectedKey,
  onDetails,
  sortKey,
  sortDirection,
  onSort,
}: {
  groups: EquipmentRegistryGroup[];
  groupTotals: Map<string, EquipmentRegistryGroup>;
  grouped: boolean;
  collapsedGroups: Set<string>;
  onToggleGroup: (key: string) => void;
  visibleColumns: EquipmentRegistryColumn[];
  density: SettingsTableDensity;
  selectedKey: string | null;
  onDetails: (key: string) => void;
  sortKey: EquipmentRegistrySortKey;
  sortDirection: EquipmentRegistrySortDirection;
  onSort: (key: EquipmentRegistrySortKey) => void;
}) {
  const columnCount = 2 + visibleColumns.length;
  return (
    <section
      className="overflow-hidden rounded-3xl border border-white/[0.07] bg-[#08182e]/85"
      data-testid="equipment-registry-results"
    >
      <div className="hidden max-h-[70vh] overflow-auto lg:block">
        <table
          className="w-full min-w-[1050px] border-separate border-spacing-0 text-left text-xs"
          data-testid="equipment-registry-table"
        >
          <thead className="sticky top-0 z-30 bg-[#0a1b32] text-[9px] tracking-[0.12em] text-slate-500 uppercase shadow-[0_1px_0_rgba(255,255,255,0.08)]">
            <tr>
              <SortableHeader
                label="Актив"
                sort="identity"
                active={sortKey}
                direction={sortDirection}
                onSort={onSort}
                sticky
              />
              {visibleColumns.includes("category") ? (
                <SortableHeader
                  label="Категорія"
                  sort="category"
                  active={sortKey}
                  direction={sortDirection}
                  onSort={onSort}
                />
              ) : null}
              {visibleColumns.includes("manufacturer") ? (
                <SortableHeader
                  label="Виробник / модель"
                  sort="manufacturer"
                  active={sortKey}
                  direction={sortDirection}
                  onSort={onSort}
                />
              ) : null}
              {visibleColumns.includes("location") ? (
                <SortableHeader
                  label="Розташування"
                  sort="location"
                  active={sortKey}
                  direction={sortDirection}
                  onSort={onSort}
                />
              ) : null}
              {visibleColumns.includes("status") ? (
                <SortableHeader
                  label="Статус"
                  sort="status"
                  active={sortKey}
                  direction={sortDirection}
                  onSort={onSort}
                />
              ) : null}
              {visibleColumns.includes("calibration") ? (
                <SortableHeader
                  label="Метрологія"
                  sort="calibration"
                  active={sortKey}
                  direction={sortDirection}
                  onSort={onSort}
                />
              ) : null}
              <th className="px-4 py-3 text-right">Дії</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => {
              const total = groupTotals.get(group.key) ?? group;
              const collapsed = grouped && collapsedGroups.has(group.key);
              return (
                <GroupRows
                  key={group.key}
                  group={group}
                  total={total}
                  grouped={grouped}
                  collapsed={collapsed}
                  columnCount={columnCount}
                  onToggle={() => onToggleGroup(group.key)}
                  visibleColumns={visibleColumns}
                  density={density}
                  selectedKey={selectedKey}
                  onDetails={onDetails}
                />
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="grid gap-3 p-3 lg:hidden">
        {groups.map((group) => {
          const total = groupTotals.get(group.key) ?? group;
          const collapsed = grouped && collapsedGroups.has(group.key);
          return (
            <div key={group.key} className="contents">
              {grouped ? (
                <GroupHeaderCard
                  group={total}
                  collapsed={collapsed}
                  onToggle={() => onToggleGroup(group.key)}
                />
              ) : null}
              {!collapsed
                ? group.assets.map((asset) => (
                    <RegistryCard key={asset.key} asset={asset} onDetails={() => onDetails(asset.key)} />
                  ))
                : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function GroupRows({
  group,
  total,
  grouped,
  collapsed,
  columnCount,
  onToggle,
  visibleColumns,
  density,
  selectedKey,
  onDetails,
}: {
  group: EquipmentRegistryGroup;
  total: EquipmentRegistryGroup;
  grouped: boolean;
  collapsed: boolean;
  columnCount: number;
  onToggle: () => void;
  visibleColumns: EquipmentRegistryColumn[];
  density: SettingsTableDensity;
  selectedKey: string | null;
  onDetails: (key: string) => void;
}) {
  return (
    <>
      {grouped ? (
        <tr className="bg-[#0a1b32]/95">
          <td colSpan={columnCount} className="border-b border-white/[0.06] px-3 py-2">
            <button
              type="button"
              aria-expanded={!collapsed}
              onClick={onToggle}
              className="flex w-full items-center gap-2 rounded-lg px-2 py-1 text-left focus:ring-2 focus:ring-cyan-300 focus:outline-none"
            >
              {collapsed ? (
                <ChevronRight className="h-4 w-4 text-slate-500" />
              ) : (
                <ChevronDown className="h-4 w-4 text-slate-500" />
              )}
              <span className="font-semibold text-slate-200">{total.label}</span>
              <span className="rounded-full border border-white/10 px-2 py-0.5 text-[9px] text-slate-400">
                {total.count}
              </span>
              {total.issueCount > 0 ? (
                <span className="rounded-full border border-amber-300/15 bg-amber-400/10 px-2 py-0.5 text-[9px] font-semibold text-amber-100">
                  {total.issueCount} ризиків
                </span>
              ) : null}
            </button>
          </td>
        </tr>
      ) : null}
      {!collapsed
        ? group.assets.map((asset) => (
            <RegistryRow
              key={asset.key}
              asset={asset}
              visibleColumns={visibleColumns}
              density={density}
              selected={selectedKey === asset.key}
              onDetails={() => onDetails(asset.key)}
            />
          ))
        : null}
    </>
  );
}

function RegistryRow({
  asset,
  visibleColumns,
  density,
  selected,
  onDetails,
}: {
  asset: EquipmentRegistryAsset;
  visibleColumns: EquipmentRegistryColumn[];
  density: SettingsTableDensity;
  selected: boolean;
  onDetails: () => void;
}) {
  const padding = density === "compact" ? "px-3 py-2" : "px-4 py-3";
  return (
    <tr
      tabIndex={0}
      aria-selected={selected}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onDetails();
        }
      }}
      className={clsx(
        "group border-b border-white/[0.055] hover:bg-white/[0.025] focus:bg-cyan-400/[0.05] focus:ring-2 focus:ring-cyan-300 focus:outline-none focus:ring-inset",
        selected && "bg-cyan-400/[0.05]",
      )}
    >
      <td
        className={clsx(
          "sticky left-0 z-10 bg-[#08182e] group-hover:bg-[#0b1c33] group-focus:bg-[#0b263d]",
          padding,
        )}
      >
        <div className="flex items-center gap-3">
          <div
            className={clsx(
              "grid shrink-0 place-items-center rounded-xl border border-cyan-300/10 bg-cyan-400/[0.06]",
              density === "compact" ? "h-8 w-8" : "h-9 w-9",
            )}
          >
            {renderAssetIcon(asset.category, "h-4 w-4 text-cyan-300")}
          </div>
          <div className="min-w-0">
            <p className="max-w-[260px] truncate font-semibold text-slate-100">{asset.displayName}</p>
            <p className="mt-0.5 max-w-[260px] truncate font-mono text-[10px] text-cyan-300">
              {asset.primaryIdentifier}
            </p>
          </div>
        </div>
      </td>
      {visibleColumns.includes("category") ? (
        <td className={clsx(padding, "text-slate-300")}>{categoryLabel(asset.category)}</td>
      ) : null}
      {visibleColumns.includes("manufacturer") ? (
        <td className={clsx(padding, "text-slate-300")}>
          {asset.manufacturer ?? "Не задано"}
          <span className="block text-[10px] text-slate-500">{asset.model ?? asset.serialNumber ?? "—"}</span>
        </td>
      ) : null}
      {visibleColumns.includes("location") ? (
        <td className={clsx("max-w-[260px] text-slate-300", padding)}>
          <span className="block truncate">{asset.chamberLabel ?? "Не прив’язано"}</span>
          <span className="block truncate text-[10px] text-slate-500">{asset.locationLabel ?? "—"}</span>
        </td>
      ) : null}
      {visibleColumns.includes("status") ? (
        <td className={padding}>
          <StatusSummary asset={asset} />
        </td>
      ) : null}
      {visibleColumns.includes("calibration") ? (
        <td className={padding}>
          <CalibrationBadge value={asset.calibrationStatus} />
        </td>
      ) : null}
      <td className={padding}>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            aria-label={`Переглянути паспорт ${asset.primaryIdentifier}`}
            title="Переглянути"
            onClick={onDetails}
            className="grid h-8 w-8 place-items-center rounded-lg border border-white/10 text-slate-300 hover:bg-cyan-400/10 hover:text-cyan-200 focus:ring-2 focus:ring-cyan-300 focus:outline-none"
          >
            <Eye className="h-4 w-4" />
          </button>
          {asset.canonicalHref ? (
            <Link
              href={asset.canonicalHref}
              aria-label={`Відкрити канонічну картку ${asset.primaryIdentifier}`}
              title="Відкрити канонічну картку"
              className="grid h-8 w-8 place-items-center rounded-lg border border-blue-300/15 bg-blue-400/10 text-blue-100 hover:bg-blue-400/15 focus:ring-2 focus:ring-blue-300 focus:outline-none"
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
  return (
    <article className="rounded-2xl border border-white/[0.07] bg-[#091a31]/90 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-cyan-300/10 bg-cyan-400/[0.06]">
            {renderAssetIcon(asset.category, "h-4 w-4 text-cyan-300")}
          </div>
          <div className="min-w-0">
            <p className="truncate font-semibold text-white">{asset.displayName}</p>
            <p className="mt-1 truncate font-mono text-[10px] text-cyan-300">{asset.primaryIdentifier}</p>
            <p className="mt-1 text-[10px] text-slate-500">{categoryLabel(asset.category)}</p>
          </div>
        </div>
        {equipmentAssetHasIssue(asset) ? (
          <AlertTriangle aria-label="Актив потребує уваги" className="h-4 w-4 shrink-0 text-amber-200" />
        ) : null}
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
          aria-label={`Переглянути паспорт ${asset.primaryIdentifier}`}
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

function GroupHeaderCard({
  group,
  collapsed,
  onToggle,
}: {
  group: EquipmentRegistryGroup;
  collapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      aria-expanded={!collapsed}
      onClick={onToggle}
      className="flex w-full items-center gap-2 rounded-xl border border-white/[0.07] bg-[#0a1b32] p-3 text-left"
    >
      <span className="font-semibold text-slate-200">{group.label}</span>
      <span className="text-xs text-slate-500">{group.count}</span>
      {group.issueCount > 0 ? (
        <span className="ml-auto text-xs text-amber-200">{group.issueCount} ризиків</span>
      ) : null}
      {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
    </button>
  );
}

function SortableHeader({
  label,
  sort,
  active,
  direction,
  onSort,
  sticky = false,
}: {
  label: string;
  sort: EquipmentRegistrySortKey;
  active: EquipmentRegistrySortKey;
  direction: EquipmentRegistrySortDirection;
  onSort: (key: EquipmentRegistrySortKey) => void;
  sticky?: boolean;
}) {
  return (
    <th className={clsx("px-4 py-3", sticky && "sticky left-0 z-40 bg-[#0a1b32]")}>
      <button
        type="button"
        onClick={() => onSort(sort)}
        aria-label={`Сортувати: ${label}`}
        className="inline-flex items-center gap-1 rounded focus:ring-2 focus:ring-cyan-300 focus:outline-none"
      >
        {label}
        {active === sort ? (
          direction === "asc" ? (
            <ArrowUp className="h-3 w-3 text-cyan-300" />
          ) : (
            <ArrowDown className="h-3 w-3 text-cyan-300" />
          )
        ) : null}
      </button>
    </th>
  );
}

function QuickRiskChip({
  label,
  value,
  active,
  count,
  onClick,
}: {
  label: string;
  value: EquipmentRegistryRiskFilter;
  active: boolean;
  count: number;
  onClick: (value: EquipmentRegistryRiskFilter) => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={() => onClick(value)}
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[10px] font-semibold focus:ring-2 focus:ring-cyan-300 focus:outline-none",
        active
          ? "border-cyan-300/30 bg-cyan-400/15 text-cyan-100"
          : "border-white/[0.08] bg-white/[0.025] text-slate-400 hover:text-slate-200",
      )}
    >
      <span>{label}</span>
      <span className="rounded-full bg-black/20 px-1.5 py-0.5">{count}</span>
    </button>
  );
}

function PartialFailures({
  failures,
  onRetry,
}: {
  failures: EquipmentRegistryFailure[];
  onRetry: () => void;
}) {
  return (
    <section className="rounded-2xl border border-amber-300/15 bg-amber-400/[0.07] p-4" role="alert">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-200" />
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-amber-100">Частина chamber catalog недоступна</h2>
          <p className="mt-1 text-xs leading-5 text-amber-100/70">
            Успішно завантажені активи залишаються доступними. Відсутні дані не підміняються demo fixtures.
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
  );
}

function StatusSummary({ asset }: { asset: EquipmentRegistryAsset }) {
  const values = [
    ...new Set(
      [asset.lifecycleStatus, asset.healthStatus, asset.connectionStatus, asset.catalogStatus].filter(
        (value): value is string => Boolean(value),
      ),
    ),
  ];
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

function readRisk(searchParams: Pick<URLSearchParams, "get">): EquipmentRegistryRiskFilter {
  const value = searchParams.get("risk") as EquipmentRegistryRiskFilter | null;
  return value && risks.has(value) ? value : "all";
}
function readSortKey(searchParams: Pick<URLSearchParams, "get">): EquipmentRegistrySortKey {
  const value = searchParams.get("sort") as EquipmentRegistrySortKey | null;
  return value && sortKeys.has(value) ? value : "identity";
}
function readSortDirection(searchParams: Pick<URLSearchParams, "get">): EquipmentRegistrySortDirection {
  return searchParams.get("order") === "desc" ? "desc" : "asc";
}
function readGroupMode(searchParams: Pick<URLSearchParams, "get">): EquipmentRegistryGroupMode {
  const value = searchParams.get("group") as EquipmentRegistryGroupMode | null;
  return value && groupModes.has(value) ? value : "none";
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
function countActiveFilters(filters: EquipmentRegistryFilters, risk: EquipmentRegistryRiskFilter): number {
  return (
    Object.values(filters).filter((value) => Boolean(value) && value !== "all").length +
    (risk === "all" ? 0 : 1)
  );
}
function primaryStatus(asset: EquipmentRegistryAsset): string {
  return statusLabel(
    asset.lifecycleStatus ?? asset.connectionStatus ?? asset.catalogStatus ?? asset.healthStatus ?? "unknown",
  );
}
function renderAssetIcon(category: EquipmentRegistryAsset["category"], className: string) {
  switch (category) {
    case "refrigeration-equipment":
      return <Refrigerator className={className} />;
    case "temperature-controller":
      return <Cpu className={className} />;
    case "energy-meter":
      return <Gauge className={className} />;
    case "physical-sensor":
      return <Thermometer className={className} />;
  }
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
function columnLabel(value: EquipmentRegistryColumn): string {
  return {
    category: "Категорія",
    manufacturer: "Виробник / модель",
    location: "Розташування",
    status: "Статус",
    calibration: "Метрологія",
  }[value];
}

const inputClass =
  "h-11 w-full rounded-xl border border-white/[0.08] bg-[#06142a] pr-3 pl-10 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-cyan-300/35 focus:ring-2 focus:ring-cyan-300/10";
const selectClass =
  "h-11 w-full rounded-xl border border-white/[0.08] bg-[#06142a] px-3 text-xs text-slate-200 outline-none focus:border-cyan-300/35 focus:ring-2 focus:ring-cyan-300/10";
const pageButtonClass =
  "inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 px-3 text-xs font-semibold text-slate-300 hover:bg-white/[0.05] disabled:cursor-not-allowed disabled:opacity-30";
