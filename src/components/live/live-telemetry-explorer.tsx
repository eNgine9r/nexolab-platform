"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  FilterX,
  Pause,
  Play,
  Radio,
  RefreshCw,
  Search,
  Signal,
  WifiOff,
} from "lucide-react";

import { LiveChartPanel } from "@/components/live/live-chart-panel";
import {
  CANONICAL_CHART_TIME_RANGES,
  chartSeriesKey,
  type CanonicalChartTimeRangeId,
  type ChartXDomain,
} from "@/features/charts";
import { buildLiveChartGroups, liveSampleChartIdentity } from "@/features/live/live-chart";
import {
  defaultLiveTelemetryFilters,
  filterLiveTelemetry,
  liveChannelKey,
  liveTelemetryFilterOptions,
  liveTelemetryState,
  selectedLiveSamples,
  toggleLiveSelection,
  type LiveAlarmFilter,
  type LiveTelemetryFilters,
  type LiveTelemetryState,
} from "@/features/live/live-telemetry";
import type { LiveHistoryRange, LiveTelemetryModel, LiveTelemetryStatus } from "@/hooks/use-live-telemetry";
import type { TelemetryQuality, TelemetrySample } from "@/lib/telemetry/types";

const QUALITY_VALUES: TelemetryQuality[] = ["valid", "sensor_error", "communication_error", "unknown"];
const ALARM_VALUES: LiveAlarmFilter[] = ["all", "active", "none", "low", "high"];
const CUSTOM_MAX_MS = 7 * 24 * 60 * 60_000;

function queryValue(value: string | null, allowed?: readonly string[]): string {
  if (!value) return "all";
  return !allowed || allowed.includes(value) ? value : "all";
}

function filtersFromParams(searchParams: URLSearchParams): LiveTelemetryFilters {
  return {
    ...defaultLiveTelemetryFilters(),
    search: searchParams.get("search") ?? "",
    nodeId: queryValue(searchParams.get("node")),
    equipmentId: queryValue(searchParams.get("equipment")),
    channelId: queryValue(searchParams.get("channel")),
    metric: queryValue(searchParams.get("metric")),
    quality: queryValue(searchParams.get("quality"), ["all", ...QUALITY_VALUES]) as "all" | TelemetryQuality,
    alarm: queryValue(searchParams.get("alarm"), ALARM_VALUES) as LiveAlarmFilter,
  };
}

function canonicalRangeFromParams(searchParams: URLSearchParams): CanonicalChartTimeRangeId {
  const value = searchParams.get("range") as CanonicalChartTimeRangeId | null;
  return CANONICAL_CHART_TIME_RANGES.some((range) => range.id === value) ? value! : "live";
}

function baseHistoryRange(range: CanonicalChartTimeRangeId): LiveHistoryRange {
  if (range === "6h") return "6h";
  if (range === "24h") return "24h";
  if (range === "7d" || range === "custom") return "7d";
  return "1h";
}

function rangeDuration(range: CanonicalChartTimeRangeId): number | null {
  return CANONICAL_CHART_TIME_RANGES.find((item) => item.id === range)?.durationMs ?? null;
}

function stateCopy(state: LiveTelemetryState): string {
  if (state === "live") return "Live";
  if (state === "stale") return "Застарілі дані";
  if (state === "sensor_error") return "Помилка датчика";
  if (state === "communication_error") return "Помилка зв’язку";
  return "Невідомий стан";
}

function stateClasses(state: LiveTelemetryState): string {
  if (state === "live") return "border-emerald-300/20 bg-emerald-400/10 text-emerald-200";
  if (state === "stale") return "border-amber-300/20 bg-amber-400/10 text-amber-100";
  if (state === "sensor_error" || state === "communication_error") {
    return "border-red-300/20 bg-red-400/10 text-red-200";
  }
  return "border-slate-400/20 bg-slate-400/10 text-slate-300";
}

function formatValue(sample: TelemetrySample): string {
  if (sample.value === null || !Number.isFinite(sample.value)) return "—";
  const absolute = Math.abs(sample.value);
  const digits = absolute >= 100 ? 0 : absolute >= 10 ? 1 : 2;
  return `${new Intl.NumberFormat("uk-UA", { maximumFractionDigits: digits }).format(sample.value)} ${sample.unit}`;
}

function formatTimestamp(value: string): string {
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return "Невідомий час";
  return new Intl.DateTimeFormat("uk-UA", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(parsed);
}

function toLocalInput(timestampMs: number): string {
  const date = new Date(timestampMs);
  const offsetMs = date.getTimezoneOffset() * 60_000;
  return new Date(timestampMs - offsetMs).toISOString().slice(0, 16);
}

function fromLocalInput(value: string): number | null {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function statusMessage(status: LiveTelemetryStatus): {
  title: string;
  detail: string;
  tone: string;
  icon: typeof Activity;
} {
  if (status === "live") {
    return {
      title: "Живий потік підключено",
      detail: "Latest inventory і WebSocket updates синхронізовані.",
      tone: "border-emerald-300/15 bg-emerald-400/[0.06] text-emerald-100",
      icon: Radio,
    };
  }
  if (status === "connecting") {
    return {
      title: "Підключення до телеметрії",
      detail: "Спочатку встановлюється authenticated WebSocket coverage, потім REST snapshot.",
      tone: "border-cyan-300/15 bg-cyan-400/[0.06] text-cyan-100",
      icon: Signal,
    };
  }
  if (status === "reconnecting") {
    return {
      title: "Відновлення live-з’єднання",
      detail: "Останні значення збережено; нові події тимчасово не надходять.",
      tone: "border-amber-300/15 bg-amber-400/[0.06] text-amber-100",
      icon: RefreshCw,
    };
  }
  if (status === "stale") {
    return {
      title: "Телеметрія застаріла",
      detail: "Останні значення залишаються видимими, але не позначаються як live.",
      tone: "border-amber-300/15 bg-amber-400/[0.06] text-amber-100",
      icon: Clock3,
    };
  }
  if (status === "offline") {
    return {
      title: "Live-потік офлайн",
      detail: "Перевірте локальний Telemetry Service, MQTT і мережевий шлях.",
      tone: "border-slate-300/15 bg-slate-400/[0.06] text-slate-200",
      icon: WifiOff,
    };
  }
  return {
    title: status === "forbidden" ? "Доступ заборонено" : "Помилка телеметрії",
    detail: "Перевірте локальну конфігурацію, авторизацію та журнали Telemetry Service.",
    tone: "border-red-300/15 bg-red-400/[0.06] text-red-100",
    icon: AlertTriangle,
  };
}

function FilterSelect({
  label,
  value,
  values,
  onChange,
}: {
  label: string;
  value: string;
  values: readonly string[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid gap-1.5 text-xs font-medium text-slate-400">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 min-w-0 rounded-xl border border-white/10 bg-[#081a32] px-3 text-sm text-slate-100 transition outline-none focus:border-cyan-300/50 focus:ring-2 focus:ring-cyan-400/10"
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

function deriveResetDomain(
  range: CanonicalChartTimeRangeId,
  historyToMs: number,
  customFromMs: number | null,
  customToMs: number | null,
): ChartXDomain {
  if (range === "custom" && customFromMs !== null && customToMs !== null && customFromMs < customToMs) {
    return { fromMs: customFromMs, toMs: customToMs };
  }
  const durationMs = rangeDuration(range) ?? 15 * 60_000;
  return { fromMs: historyToMs - durationMs, toMs: historyToMs };
}

export function LiveTelemetryExplorer({ telemetry }: { telemetry: LiveTelemetryModel }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [filters, setFilters] = useState<LiveTelemetryFilters>(() =>
    filtersFromParams(new URLSearchParams(searchParams.toString())),
  );
  const [range, setRange] = useState<CanonicalChartTimeRangeId>(() =>
    canonicalRangeFromParams(new URLSearchParams(searchParams.toString())),
  );
  const [initialTo] = useState(() => Date.now());
  const [customFrom, setCustomFrom] = useState(
    () => searchParams.get("from") ?? toLocalInput(initialTo - 60 * 60_000),
  );
  const [customTo, setCustomTo] = useState(() => searchParams.get("to") ?? toLocalInput(initialTo));
  const [customError, setCustomError] = useState<string | null>(null);
  const [selectionMessage, setSelectionMessage] = useState<string | null>(null);
  const [hiddenSeriesKeys, setHiddenSeriesKeys] = useState<Set<string>>(() => new Set());
  const [soloSeriesKey, setSoloSeriesKey] = useState<string | null>(null);
  const [sharedCursorMs, setSharedCursorMs] = useState<number | null>(null);
  const [viewportDomain, setViewportDomain] = useState<ChartXDomain | null>(null);
  const [liveFollow, setLiveFollow] = useState(range === "live");
  const lastUrlRef = useRef("");

  const filtered = useMemo(
    () => filterLiveTelemetry(telemetry.samples, filters),
    [filters, telemetry.samples],
  );
  const options = useMemo(() => liveTelemetryFilterOptions(telemetry.samples), [telemetry.samples]);
  const selected = useMemo(
    () => selectedLiveSamples(telemetry.selectedKeys, telemetry.samples),
    [telemetry.samples, telemetry.selectedKeys],
  );
  const availableKeys = useMemo(() => new Set(telemetry.samples.map(liveChannelKey)), [telemetry.samples]);
  const status = statusMessage(telemetry.status);
  const StatusIcon = status.icon;
  const historyToMs = telemetry.historyWindow?.to.getTime() ?? initialTo;
  const customFromMs = fromLocalInput(customFrom);
  const customToMs = fromLocalInput(customTo);
  const resetDomain = useMemo(
    () => deriveResetDomain(range, historyToMs, customFromMs, customToMs),
    [customFromMs, customToMs, historyToMs, range],
  );
  const effectiveDomain = liveFollow && range === "live" ? resetDomain : (viewportDomain ?? resetDomain);
  const groups = useMemo(
    () =>
      buildLiveChartGroups({
        selectedIdentities: selected,
        historySamples: telemetry.historySamples,
        status: telemetry.status,
        xDomain: effectiveDomain,
        hiddenSeriesKeys,
        soloSeriesKey,
      }),
    [effectiveDomain, hiddenSeriesKeys, selected, soloSeriesKey, telemetry.historySamples, telemetry.status],
  );
  const rangeLabel = CANONICAL_CHART_TIME_RANGES.find((item) => item.id === range)?.label ?? range;

  const syncUrl = (
    nextFilters: LiveTelemetryFilters,
    nextSelected: readonly string[],
    nextRange: CanonicalChartTimeRangeId,
    nextCustomFrom = customFrom,
    nextCustomTo = customTo,
  ) => {
    const params = new URLSearchParams();
    params.set("workspace", "explorer");
    if (nextFilters.search.trim()) params.set("search", nextFilters.search.trim());
    if (nextFilters.nodeId !== "all") params.set("node", nextFilters.nodeId);
    if (nextFilters.equipmentId !== "all") params.set("equipment", nextFilters.equipmentId);
    if (nextFilters.channelId !== "all") params.set("channel", nextFilters.channelId);
    if (nextFilters.metric !== "all") params.set("metric", nextFilters.metric);
    if (nextFilters.quality !== "all") params.set("quality", nextFilters.quality);
    if (nextFilters.alarm !== "all") params.set("alarm", nextFilters.alarm);
    for (const key of nextSelected) params.append("compare", key);
    if (nextRange !== "live") params.set("range", nextRange);
    if (nextRange === "custom") {
      params.set("from", nextCustomFrom);
      params.set("to", nextCustomTo);
    }
    const nextUrl = `${pathname}?${params.toString()}`;
    lastUrlRef.current = nextUrl;
    router.replace(nextUrl, { scroll: false });
  };

  const updateFilters = (patch: Partial<LiveTelemetryFilters>) => {
    const next = { ...filters, ...patch };
    setFilters(next);
    syncUrl(next, telemetry.selectedKeys, range);
  };

  const selectRange = (nextRange: CanonicalChartTimeRangeId) => {
    if (nextRange === "custom") {
      setRange(nextRange);
      telemetry.setHistoryRange("7d");
      setLiveFollow(false);
      setViewportDomain(null);
      syncUrl(filters, telemetry.selectedKeys, nextRange);
      return;
    }
    setCustomError(null);
    setRange(nextRange);
    telemetry.setHistoryRange(baseHistoryRange(nextRange));
    setViewportDomain(null);
    setLiveFollow(nextRange === "live");
    syncUrl(filters, telemetry.selectedKeys, nextRange);
  };

  const applyCustomRange = () => {
    const fromMs = fromLocalInput(customFrom);
    const toMs = fromLocalInput(customTo);
    if (fromMs === null || toMs === null || fromMs >= toMs) {
      setCustomError("Вкажіть коректний початок і кінець інтервалу.");
      return;
    }
    if (toMs - fromMs > CUSTOM_MAX_MS) {
      setCustomError("Custom interval у цьому Live Data workspace обмежений 7 днями.");
      return;
    }
    const historyNowMs = telemetry.historyWindow?.to.getTime() ?? initialTo;
    if (toMs > historyNowMs + 30_000 || fromMs < historyNowMs - CUSTOM_MAX_MS - 60_000) {
      setCustomError("Custom interval має бути в межах доступного локального 7-денного history window.");
      return;
    }
    setCustomError(null);
    setRange("custom");
    telemetry.setHistoryRange("7d");
    setLiveFollow(false);
    setViewportDomain({ fromMs, toMs });
    syncUrl(filters, telemetry.selectedKeys, "custom", customFrom, customTo);
  };

  useEffect(() => {
    const selectedChartKeys = new Set(
      selected.map((sample) => chartSeriesKey(liveSampleChartIdentity(sample))),
    );
    if (soloSeriesKey && !selectedChartKeys.has(soloSeriesKey)) {
      void Promise.resolve().then(() => setSoloSeriesKey(null));
    }
  }, [selected, soloSeriesKey]);

  useEffect(() => {
    const params = new URLSearchParams();
    params.set("workspace", "explorer");
    if (filters.search.trim()) params.set("search", filters.search.trim());
    if (filters.nodeId !== "all") params.set("node", filters.nodeId);
    if (filters.equipmentId !== "all") params.set("equipment", filters.equipmentId);
    if (filters.channelId !== "all") params.set("channel", filters.channelId);
    if (filters.metric !== "all") params.set("metric", filters.metric);
    if (filters.quality !== "all") params.set("quality", filters.quality);
    if (filters.alarm !== "all") params.set("alarm", filters.alarm);
    for (const key of telemetry.selectedKeys) params.append("compare", key);
    if (range !== "live") params.set("range", range);
    if (range === "custom") {
      params.set("from", customFrom);
      params.set("to", customTo);
    }
    const expected = `${pathname}?${params.toString()}`;
    if (expected === lastUrlRef.current) return;
    lastUrlRef.current = expected;
    router.replace(expected, { scroll: false });
  }, [customFrom, customTo, filters, pathname, range, router, telemetry.selectedKeys]);

  return (
    <div className="min-w-0 space-y-4 sm:space-y-5">
      <section className="overflow-hidden rounded-3xl border border-cyan-300/10 bg-[#091a31]/95 p-4 shadow-2xl shadow-black/20 sm:p-5 xl:p-6">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-3xl">
            <div className="flex items-center gap-2 text-xs tracking-[0.2em] text-cyan-300 uppercase">
              <Activity className="h-4 w-4" aria-hidden="true" />
              Canonical realtime telemetry explorer
            </div>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-white sm:text-3xl">Live дані</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">
              Реальний inventory, ECharts comparison і локальна persisted history. Графік не керує acquisition
              або Modbus polling.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:min-w-[520px]">
            {[
              ["Каналів", telemetry.samples.length],
              ["Результатів", filtered.length],
              ["Обрано", `${telemetry.selectedKeys.length} / 8`],
              ["Груп", groups.length],
            ].map(([label, value]) => (
              <div key={label} className="rounded-2xl border border-white/[0.08] bg-white/[0.025] p-3">
                <p className="text-xs text-slate-500">{label}</p>
                <p className="mt-1 text-xl font-semibold text-white">{value}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section
        className={`flex flex-col gap-3 rounded-2xl border p-4 sm:flex-row sm:items-center sm:justify-between ${status.tone}`}
      >
        <div className="flex items-start gap-3">
          <StatusIcon className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
          <div>
            <p className="text-sm font-semibold">{status.title}</p>
            <p className="mt-0.5 text-xs opacity-75">{status.detail}</p>
          </div>
        </div>
        {telemetry.status !== "live" ? (
          <button
            type="button"
            onClick={telemetry.retry}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-xl border border-current/20 px-3 text-xs font-medium hover:bg-white/5 focus-visible:ring-2 focus-visible:ring-cyan-300"
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            Повторити
          </button>
        ) : null}
      </section>

      <section className="rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-white">Пошук і фільтри</h2>
            <p className="mt-1 text-xs text-slate-500">
              Усі умови застосовуються одночасно та зберігаються в URL.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              const next = defaultLiveTelemetryFilters();
              setFilters(next);
              syncUrl(next, telemetry.selectedKeys, range);
            }}
            className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 px-3 text-xs text-slate-300 hover:border-cyan-300/30 hover:text-white focus-visible:ring-2 focus-visible:ring-cyan-300"
          >
            <FilterX className="h-4 w-4" aria-hidden="true" />
            Очистити
          </button>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-7">
          <label className="grid gap-1.5 text-xs font-medium text-slate-400 sm:col-span-2 xl:col-span-2">
            Пошук
            <span className="relative">
              <Search
                className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-slate-500"
                aria-hidden="true"
              />
              <input
                value={filters.search}
                onChange={(event) => updateFilters({ search: event.target.value })}
                placeholder="node, equipment, channel, metric, source..."
                className="h-10 w-full rounded-xl border border-white/10 bg-[#081a32] pr-3 pl-10 text-sm text-white outline-none placeholder:text-slate-600 focus:border-cyan-300/50 focus:ring-2 focus:ring-cyan-400/10"
              />
            </span>
          </label>
          <FilterSelect
            label="Node"
            value={filters.nodeId}
            values={options.nodeIds}
            onChange={(nodeId) => updateFilters({ nodeId })}
          />
          <FilterSelect
            label="Equipment"
            value={filters.equipmentId}
            values={options.equipmentIds}
            onChange={(equipmentId) => updateFilters({ equipmentId })}
          />
          <FilterSelect
            label="Channel"
            value={filters.channelId}
            values={options.channelIds}
            onChange={(channelId) => updateFilters({ channelId })}
          />
          <FilterSelect
            label="Metric"
            value={filters.metric}
            values={options.metrics}
            onChange={(metric) => updateFilters({ metric })}
          />
          <FilterSelect
            label="Quality"
            value={filters.quality}
            values={QUALITY_VALUES}
            onChange={(quality) => updateFilters({ quality: quality as "all" | TelemetryQuality })}
          />
          <FilterSelect
            label="Alarm"
            value={filters.alarm}
            values={["active", "none", "low", "high"]}
            onChange={(alarm) => updateFilters({ alarm: alarm as LiveAlarmFilter })}
          />
        </div>
      </section>

      <section className="overflow-hidden rounded-3xl border border-white/[0.08] bg-[#091a31]/90">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.07] px-4 py-4 sm:px-5">
          <div>
            <h2 className="text-base font-semibold text-white">Latest values</h2>
            <p className="mt-1 text-xs text-slate-500">
              {filtered.length} каналів відповідають поточному запиту
            </p>
          </div>
          {selectionMessage ? (
            <p className="text-xs font-medium text-amber-200" role="status">
              {selectionMessage}
            </p>
          ) : null}
        </div>
        {telemetry.status === "connecting" && telemetry.samples.length === 0 ? (
          <div className="grid min-h-48 place-items-center p-8 text-center text-sm text-slate-400">
            Завантаження реального channel inventory…
          </div>
        ) : filtered.length === 0 ? (
          <div className="grid min-h-48 place-items-center p-8 text-center">
            <div>
              <Signal className="mx-auto h-8 w-8 text-slate-600" aria-hidden="true" />
              <p className="mt-3 text-sm font-medium text-slate-200">Каналів не знайдено</p>
              <p className="mt-1 text-xs text-slate-500">
                Змініть фільтри або перевірте надходження телеметрії.
              </p>
            </div>
          </div>
        ) : (
          <div className="max-w-full overflow-x-auto">
            <table className="w-full min-w-[1080px] text-left text-sm">
              <thead className="bg-white/[0.025] text-xs tracking-wide text-slate-500 uppercase">
                <tr>
                  <th className="w-16 px-4 py-3">Compare</th>
                  <th className="px-3 py-3">Node</th>
                  <th className="px-3 py-3">Equipment</th>
                  <th className="px-3 py-3">Channel</th>
                  <th className="px-3 py-3">Metric</th>
                  <th className="px-3 py-3">Value</th>
                  <th className="px-3 py-3">State</th>
                  <th className="px-3 py-3">Alarm</th>
                  <th className="px-3 py-3">Captured</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.055]">
                {filtered.map((sample) => {
                  const key = liveChannelKey(sample);
                  const selectedNow = telemetry.selectedKeys.includes(key);
                  const state = liveTelemetryState(sample);
                  return (
                    <tr key={key} className="text-slate-300 hover:bg-white/[0.02]">
                      <td className="px-4 py-3">
                        <input
                          type="checkbox"
                          checked={selectedNow}
                          aria-label={`Порівнювати ${sample.equipment_id} ${sample.channel_id} ${sample.metric}`}
                          onChange={() => {
                            const result = toggleLiveSelection(telemetry.selectedKeys, key, availableKeys);
                            if (!result.changed) {
                              setSelectionMessage(
                                result.reason === "limit"
                                  ? "Можна порівнювати не більше 8 каналів."
                                  : "Канал більше недоступний.",
                              );
                              return;
                            }
                            setSelectionMessage(null);
                            telemetry.setSelectedKeys(result.selected);
                            syncUrl(filters, result.selected, range);
                          }}
                          className="h-4 w-4 accent-cyan-400"
                        />
                      </td>
                      <td className="px-3 py-3 text-xs">{sample.node_id}</td>
                      <td className="px-3 py-3 text-xs">{sample.equipment_id}</td>
                      <td className="px-3 py-3 text-xs">{sample.channel_id}</td>
                      <td className="px-3 py-3 text-xs">{sample.metric}</td>
                      <td className="px-3 py-3 font-medium text-white">{formatValue(sample)}</td>
                      <td className="px-3 py-3">
                        <span
                          className={`inline-flex rounded-lg border px-2 py-1 text-xs ${stateClasses(state)}`}
                        >
                          {stateCopy(state)}
                        </span>
                      </td>
                      <td className="px-3 py-3">
                        {sample.alarm ? (
                          <span className="inline-flex items-center gap-1 rounded-lg border border-red-300/20 bg-red-400/10 px-2 py-1 text-xs text-red-200">
                            <AlertTriangle className="h-3 w-3" aria-hidden="true" /> {sample.alarm}
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-xs text-slate-500">
                            <CheckCircle2 className="h-3 w-3" aria-hidden="true" /> none
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-3 text-xs text-slate-400">
                        {formatTimestamp(sample.captured_at)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="min-w-0 rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-4 sm:p-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <p className="text-xs tracking-[0.18em] text-cyan-300 uppercase">Canonical Chart System</p>
            <h2 className="mt-1 text-lg font-semibold text-white">Синхронізована історія</h2>
            <p className="mt-1 max-w-2xl text-xs leading-5 text-slate-500">
              До 8 каналів. Несумісні одиниці мають окремі синхронізовані шкали. Zoom/pan — display-only і не
              змінює acquisition.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {CANONICAL_CHART_TIME_RANGES.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => selectRange(item.id)}
                className={`min-h-10 rounded-xl border px-3 text-xs font-medium transition focus-visible:ring-2 focus-visible:ring-cyan-300 ${range === item.id ? "border-cyan-300/40 bg-cyan-400/10 text-cyan-100" : "border-white/10 text-slate-400 hover:text-white"}`}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        {range === "custom" ? (
          <div className="mt-4 flex flex-wrap items-end gap-3 rounded-2xl border border-white/[0.07] bg-[#081a32]/60 p-3">
            <label className="grid gap-1 text-xs text-slate-400">
              Від
              <input
                type="datetime-local"
                value={customFrom}
                onChange={(event) => setCustomFrom(event.target.value)}
                className="h-10 rounded-xl border border-white/10 bg-[#06142A] px-3 text-sm text-white"
              />
            </label>
            <label className="grid gap-1 text-xs text-slate-400">
              До
              <input
                type="datetime-local"
                value={customTo}
                onChange={(event) => setCustomTo(event.target.value)}
                className="h-10 rounded-xl border border-white/10 bg-[#06142A] px-3 text-sm text-white"
              />
            </label>
            <button
              type="button"
              onClick={applyCustomRange}
              className="min-h-10 rounded-xl bg-cyan-400/15 px-4 text-xs font-medium text-cyan-100 focus-visible:ring-2 focus-visible:ring-cyan-300"
            >
              Застосувати
            </button>
            {customError ? (
              <p className="basis-full text-xs text-red-200" role="alert">
                {customError}
              </p>
            ) : null}
          </div>
        ) : null}

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-white/[0.07] bg-[#081a32]/50 p-3">
          <div className="flex items-center gap-2 text-xs text-slate-300">
            {liveFollow && range === "live" ? (
              <Play className="h-4 w-4 text-emerald-300" aria-hidden="true" />
            ) : range !== "live" && viewportDomain === null ? (
              <Clock3 className="h-4 w-4 text-cyan-300" aria-hidden="true" />
            ) : (
              <Pause className="h-4 w-4 text-amber-300" aria-hidden="true" />
            )}
            <span>
              {liveFollow && range === "live"
                ? "Live Follow"
                : range !== "live" && viewportDomain === null
                  ? "Rolling range"
                  : "Paused view"}
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {liveFollow && range === "live" ? (
              <button
                type="button"
                onClick={() => {
                  setViewportDomain(resetDomain);
                  setLiveFollow(false);
                }}
                className="min-h-10 rounded-xl border border-white/10 px-3 text-xs text-slate-200 focus-visible:ring-2 focus-visible:ring-cyan-300"
              >
                Pause View
              </button>
            ) : (
              <button
                type="button"
                onClick={() => {
                  setRange("live");
                  telemetry.setHistoryRange("1h");
                  setViewportDomain(null);
                  setLiveFollow(true);
                  syncUrl(filters, telemetry.selectedKeys, "live");
                }}
                className="min-h-10 rounded-xl border border-cyan-300/30 bg-cyan-400/10 px-3 text-xs font-medium text-cyan-100 focus-visible:ring-2 focus-visible:ring-cyan-300"
              >
                Return to Live
              </button>
            )}
          </div>
        </div>

        {selected.length === 0 ? (
          <div className="mt-5 grid min-h-44 place-items-center rounded-2xl border border-dashed border-white/10 bg-[#081a32]/50 p-8 text-center">
            <div>
              <Activity className="mx-auto h-8 w-8 text-slate-600" aria-hidden="true" />
              <p className="mt-3 text-sm font-medium text-slate-200">Оберіть канали в таблиці</p>
              <p className="mt-1 text-xs text-slate-500">
                History requests не виконуються, доки comparison selection порожній.
              </p>
            </div>
          </div>
        ) : telemetry.historyStatus === "loading" ? (
          <div className="mt-5 grid min-h-44 place-items-center rounded-2xl border border-white/[0.07] bg-[#081a32]/50 p-8 text-sm text-slate-400">
            Завантаження history window за одним ingestion watermark…
          </div>
        ) : telemetry.historyStatus === "error" ? (
          <div className="mt-5 flex min-h-44 flex-col items-center justify-center rounded-2xl border border-red-300/15 bg-red-400/[0.04] p-8 text-center">
            <AlertTriangle className="h-8 w-8 text-red-300" aria-hidden="true" />
            <p className="mt-3 text-sm font-medium text-red-100">Не вдалося завантажити історію</p>
            <p className="mt-1 max-w-xl text-xs text-red-200/60">
              {telemetry.historyError?.message ?? "Unknown history error"}
            </p>
            <button
              type="button"
              onClick={telemetry.retryHistory}
              className="mt-4 inline-flex h-9 items-center gap-2 rounded-xl border border-red-200/20 px-3 text-xs text-red-100 hover:bg-red-400/10 focus-visible:ring-2 focus-visible:ring-red-300"
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" /> Повторити history
            </button>
          </div>
        ) : telemetry.historyWindow && telemetry.historySamples.length > 0 && groups.length > 0 ? (
          <div className="mt-5 min-w-0 space-y-4">
            {groups.map((group) => (
              <LiveChartPanel
                key={group.id}
                group={group}
                rangeLabel={rangeLabel}
                sharedCursorMs={sharedCursorMs}
                resetDomain={resetDomain}
                onSharedCursorChange={setSharedCursorMs}
                onXDomainChange={(domain) => {
                  setViewportDomain(domain);
                  setLiveFollow(false);
                }}
                onToggleSeries={(seriesKey) => {
                  setSoloSeriesKey(null);
                  setHiddenSeriesKeys((current) => {
                    const next = new Set(current);
                    if (next.has(seriesKey)) next.delete(seriesKey);
                    else next.add(seriesKey);
                    return next;
                  });
                }}
                onSoloSeries={(seriesKey) => {
                  setSoloSeriesKey((current) => (current === seriesKey ? null : seriesKey));
                }}
              />
            ))}
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
              <span>Snapshot watermark: {telemetry.historySnapshotAt ?? "—"}</span>
              <span>Future samples rejected: {telemetry.rejectedFutureSamples}</span>
            </div>
          </div>
        ) : (
          <div className="mt-5 grid min-h-44 place-items-center rounded-2xl border border-dashed border-white/10 bg-[#081a32]/50 p-8 text-center text-sm text-slate-400">
            У вибраному інтервалі немає persisted telemetry.
          </div>
        )}
      </section>
    </div>
  );
}
