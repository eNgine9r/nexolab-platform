"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  FilterX,
  Radio,
  RefreshCw,
  Search,
  Signal,
  WifiOff,
} from "lucide-react";

import { liveHistorySegments, type LiveHistoryWindow } from "@/features/live/live-history";
import {
  defaultLiveTelemetryFilters,
  filterLiveTelemetry,
  groupLiveSamplesByUnit,
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

const SERIES_COLORS = [
  "#00C6E0",
  "#7ED321",
  "#0077FF",
  "#A855F7",
  "#F5B301",
  "#14B8A6",
  "#F97316",
  "#F43F5E",
];
const QUALITY_VALUES: TelemetryQuality[] = ["valid", "sensor_error", "communication_error", "unknown"];
const ALARM_VALUES: LiveAlarmFilter[] = ["all", "active", "none", "low", "high"];
const RANGE_LABELS: Record<LiveHistoryRange, string> = {
  "1h": "1 год",
  "6h": "6 год",
  "24h": "24 год",
  "7d": "7 днів",
};

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

function channelLabel(sample: TelemetrySample): string {
  return `${sample.node_id} · ${sample.equipment_id} · ${sample.channel_id} · ${sample.metric}`;
}

function ComparisonChart({
  unit,
  identities,
  history,
  window,
  cursorRatio,
  onCursorRatioChange,
}: {
  unit: string;
  identities: TelemetrySample[];
  history: TelemetrySample[];
  window: LiveHistoryWindow;
  cursorRatio: number | null;
  onCursorRatioChange: (ratio: number | null) => void;
}) {
  const width = 960;
  const height = 270;
  const padding = { left: 58, right: 24, top: 24, bottom: 38 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const selectedKeys = new Set(identities.map(liveChannelKey));
  const relevant = history.filter((sample) => selectedKeys.has(liveChannelKey(sample)));
  const numericValues = relevant
    .filter((sample) => sample.value !== null && Number.isFinite(sample.value))
    .map((sample) => sample.value!);
  const minimum = numericValues.length ? Math.min(...numericValues) : 0;
  const maximum = numericValues.length ? Math.max(...numericValues) : 1;
  const valueRange = Math.max(0.000_001, maximum - minimum);
  const from = window.from.getTime();
  const duration = Math.max(1, window.to.getTime() - from);
  const x = (captured: string) => padding.left + ((Date.parse(captured) - from) / duration) * plotWidth;
  const y = (value: number) => padding.top + (1 - (value - minimum) / valueRange) * plotHeight;
  const series = identities.map((identity, index) => {
    const key = liveChannelKey(identity);
    const samples = relevant.filter((sample) => liveChannelKey(sample) === key);
    return {
      identity,
      color: SERIES_COLORS[index % SERIES_COLORS.length],
      segments: liveHistorySegments(samples),
    };
  });
  const segmentCount = series.reduce((sum, item) => sum + item.segments.length, 0);

  return (
    <section className="rounded-2xl border border-white/[0.08] bg-[#081a32]/80 p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs tracking-[0.18em] text-cyan-300 uppercase">Окрема шкала</p>
          <h3 className="mt-1 text-base font-semibold text-white">Одиниця: {unit}</h3>
        </div>
        <div className="flex flex-wrap gap-2 text-xs text-slate-300">
          <span className="rounded-lg border border-white/10 px-2.5 py-1">min {minimum.toFixed(2)}</span>
          <span className="rounded-lg border border-white/10 px-2.5 py-1">max {maximum.toFixed(2)}</span>
          <span className="rounded-lg border border-white/10 px-2.5 py-1">segments {segmentCount}</span>
        </div>
      </div>
      <div className="mt-4 overflow-x-auto">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="min-w-[720px]"
          role="img"
          aria-label={`Порівняння ${identities.length} каналів у ${unit}`}
          data-segments={segmentCount}
          onMouseLeave={() => onCursorRatioChange(null)}
          onMouseMove={(event) => {
            const rectangle = event.currentTarget.getBoundingClientRect();
            onCursorRatioChange(Math.max(0, Math.min(1, (event.clientX - rectangle.left) / rectangle.width)));
          }}
        >
          <rect width={width} height={height} rx="16" fill="#06162b" />
          {[0, 0.25, 0.5, 0.75, 1].map((ratio) => (
            <g key={ratio}>
              <line
                x1={padding.left}
                y1={padding.top + ratio * plotHeight}
                x2={width - padding.right}
                y2={padding.top + ratio * plotHeight}
                stroke="rgba(148,163,184,0.13)"
              />
              <text
                x={padding.left - 10}
                y={padding.top + ratio * plotHeight + 4}
                textAnchor="end"
                fill="#7f93aa"
                fontSize="11"
              >
                {(maximum - ratio * valueRange).toFixed(1)}
              </text>
            </g>
          ))}
          {[0, 0.25, 0.5, 0.75, 1].map((ratio) => (
            <line
              key={ratio}
              x1={padding.left + ratio * plotWidth}
              y1={padding.top}
              x2={padding.left + ratio * plotWidth}
              y2={height - padding.bottom}
              stroke="rgba(148,163,184,0.08)"
            />
          ))}
          {series.flatMap((item) =>
            item.segments.map((segment, segmentIndex) => {
              const path = segment
                .filter((sample) => sample.value !== null)
                .map(
                  (sample, index) =>
                    `${index === 0 ? "M" : "L"}${x(sample.captured_at).toFixed(2)},${y(sample.value!).toFixed(2)}`,
                )
                .join(" ");
              return path ? (
                <path
                  key={`${liveChannelKey(item.identity)}-${segmentIndex}`}
                  d={path}
                  fill="none"
                  stroke={item.color}
                  strokeWidth="2.3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              ) : null;
            }),
          )}
          {cursorRatio !== null ? (
            <line
              x1={padding.left + cursorRatio * plotWidth}
              y1={padding.top}
              x2={padding.left + cursorRatio * plotWidth}
              y2={height - padding.bottom}
              stroke="#E6ECF2"
              strokeWidth="1"
              strokeDasharray="5 5"
            />
          ) : null}
          <text x={padding.left} y={height - 13} fill="#7f93aa" fontSize="11">
            {formatTimestamp(window.from.toISOString())}
          </text>
          <text x={width - padding.right} y={height - 13} textAnchor="end" fill="#7f93aa" fontSize="11">
            {formatTimestamp(window.to.toISOString())}
          </text>
        </svg>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {series.map((item) => (
          <span
            key={liveChannelKey(item.identity)}
            className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-2.5 py-1 text-xs text-slate-300"
          >
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: item.color }} />
            {item.identity.equipment_id} · {item.identity.channel_id} · {item.identity.metric}
          </span>
        ))}
      </div>
    </section>
  );
}

export function LiveTelemetryExplorer({ telemetry }: { telemetry: LiveTelemetryModel }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [filters, setFilters] = useState<LiveTelemetryFilters>(() =>
    filtersFromParams(new URLSearchParams(searchParams.toString())),
  );
  const [selectionMessage, setSelectionMessage] = useState<string | null>(null);
  const [cursorRatio, setCursorRatio] = useState<number | null>(null);
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
  const unitGroups = useMemo(() => groupLiveSamplesByUnit(selected), [selected]);
  const availableKeys = useMemo(() => new Set(telemetry.samples.map(liveChannelKey)), [telemetry.samples]);
  const status = statusMessage(telemetry.status);
  const StatusIcon = status.icon;

  const syncUrl = (
    nextFilters: LiveTelemetryFilters,
    nextSelected: readonly string[],
    nextRange: LiveHistoryRange,
  ) => {
    const params = new URLSearchParams();
    if (nextFilters.search.trim()) params.set("search", nextFilters.search.trim());
    if (nextFilters.nodeId !== "all") params.set("node", nextFilters.nodeId);
    if (nextFilters.equipmentId !== "all") params.set("equipment", nextFilters.equipmentId);
    if (nextFilters.channelId !== "all") params.set("channel", nextFilters.channelId);
    if (nextFilters.metric !== "all") params.set("metric", nextFilters.metric);
    if (nextFilters.quality !== "all") params.set("quality", nextFilters.quality);
    if (nextFilters.alarm !== "all") params.set("alarm", nextFilters.alarm);
    for (const key of nextSelected) params.append("compare", key);
    if (nextRange !== "1h") params.set("range", nextRange);
    const nextUrl = `${pathname}${params.size ? `?${params.toString()}` : ""}`;
    lastUrlRef.current = nextUrl;
    router.replace(nextUrl, { scroll: false });
  };

  const updateFilters = (patch: Partial<LiveTelemetryFilters>) => {
    const next = { ...filters, ...patch };
    setFilters(next);
    syncUrl(next, telemetry.selectedKeys, telemetry.historyRange);
  };

  useEffect(() => {
    const params = new URLSearchParams();
    if (filters.search.trim()) params.set("search", filters.search.trim());
    if (filters.nodeId !== "all") params.set("node", filters.nodeId);
    if (filters.equipmentId !== "all") params.set("equipment", filters.equipmentId);
    if (filters.channelId !== "all") params.set("channel", filters.channelId);
    if (filters.metric !== "all") params.set("metric", filters.metric);
    if (filters.quality !== "all") params.set("quality", filters.quality);
    if (filters.alarm !== "all") params.set("alarm", filters.alarm);
    for (const key of telemetry.selectedKeys) params.append("compare", key);
    if (telemetry.historyRange !== "1h") params.set("range", telemetry.historyRange);
    const expected = `${pathname}${params.size ? `?${params.toString()}` : ""}`;
    if (expected === lastUrlRef.current) return;
    lastUrlRef.current = expected;
    router.replace(expected, { scroll: false });
  }, [filters, pathname, router, telemetry.historyRange, telemetry.selectedKeys]);

  return (
    <div className="space-y-4 sm:space-y-5">
      <section className="overflow-hidden rounded-3xl border border-cyan-300/10 bg-[#091a31]/95 p-4 shadow-2xl shadow-black/20 sm:p-5 xl:p-6">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-3xl">
            <div className="flex items-center gap-2 text-xs tracking-[0.2em] text-cyan-300 uppercase">
              <Activity className="h-4 w-4" />
              Realtime telemetry explorer
            </div>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-white sm:text-3xl">Live дані</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">
              Реальний inventory каналів, synchronized comparison і повна локальна історія без demo fallback.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:min-w-[520px]">
            {[
              ["Каналів", telemetry.samples.length],
              ["Результатів", filtered.length],
              ["Обрано", `${telemetry.selectedKeys.length} / 8`],
              ["Одиниць", unitGroups.size],
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
          <StatusIcon className="mt-0.5 h-5 w-5 shrink-0" />
          <div>
            <p className="text-sm font-semibold">{status.title}</p>
            <p className="mt-0.5 text-xs opacity-75">{status.detail}</p>
          </div>
        </div>
        {telemetry.status !== "live" ? (
          <button
            type="button"
            onClick={telemetry.retry}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-xl border border-current/20 px-3 text-xs font-medium hover:bg-white/5"
          >
            <RefreshCw className="h-3.5 w-3.5" />
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
              syncUrl(next, telemetry.selectedKeys, telemetry.historyRange);
            }}
            className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 px-3 text-xs text-slate-300 hover:border-cyan-300/30 hover:text-white"
          >
            <FilterX className="h-4 w-4" />
            Очистити
          </button>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-7">
          <label className="grid gap-1.5 text-xs font-medium text-slate-400 sm:col-span-2 xl:col-span-2">
            Пошук
            <span className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-slate-500" />
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
          {selectionMessage ? <p className="text-xs font-medium text-amber-200">{selectionMessage}</p> : null}
        </div>
        {telemetry.status === "connecting" && telemetry.samples.length === 0 ? (
          <div className="grid min-h-48 place-items-center p-8 text-center text-sm text-slate-400">
            Завантаження реального channel inventory…
          </div>
        ) : filtered.length === 0 ? (
          <div className="grid min-h-48 place-items-center p-8 text-center">
            <div>
              <Signal className="mx-auto h-8 w-8 text-slate-600" />
              <p className="mt-3 text-sm font-medium text-slate-200">Каналів не знайдено</p>
              <p className="mt-1 text-xs text-slate-500">
                Змініть фільтри або перевірте надходження телеметрії.
              </p>
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1180px] text-left text-sm">
              <thead className="bg-white/[0.025] text-xs tracking-wide text-slate-500 uppercase">
                <tr>
                  <th className="w-14 px-4 py-3">Compare</th>
                  <th className="px-3 py-3">Node</th>
                  <th className="px-3 py-3">Equipment</th>
                  <th className="px-3 py-3">Channel</th>
                  <th className="px-3 py-3">Metric</th>
                  <th className="px-3 py-3">Value</th>
                  <th className="px-3 py-3">Quality</th>
                  <th className="px-3 py-3">Alarm</th>
                  <th className="px-3 py-3">Captured</th>
                  <th className="px-3 py-3">Source</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.06]">
                {filtered.map((sample) => {
                  const key = liveChannelKey(sample);
                  const checked = telemetry.selectedKeys.includes(key);
                  const state = liveTelemetryState(sample);
                  return (
                    <tr key={key} className="transition hover:bg-white/[0.025]">
                      <td className="px-4 py-3">
                        <input
                          type="checkbox"
                          checked={checked}
                          aria-label={`${checked ? "Виключити" : "Додати"} канал ${channelLabel(sample)} ${checked ? "з" : "до"} порівняння`}
                          onChange={() => {
                            const result = toggleLiveSelection(telemetry.selectedKeys, key, availableKeys);
                            if (result.reason === "limit") {
                              setSelectionMessage("Досягнуто ліміт: максимум 8 каналів.");
                              return;
                            }
                            setSelectionMessage(null);
                            telemetry.setSelectedKeys(result.selected);
                            syncUrl(filters, result.selected, telemetry.historyRange);
                          }}
                          className="h-4 w-4 rounded border-white/20 bg-[#06142a] accent-cyan-400"
                        />
                      </td>
                      <td className="px-3 py-3 font-medium text-slate-200">{sample.node_id}</td>
                      <td className="px-3 py-3 text-slate-300">{sample.equipment_id}</td>
                      <td className="px-3 py-3 text-slate-300">{sample.channel_id}</td>
                      <td className="px-3 py-3 text-slate-300">{sample.metric}</td>
                      <td className="px-3 py-3 font-semibold text-white">{formatValue(sample)}</td>
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
                            <AlertTriangle className="h-3 w-3" />
                            {sample.alarm}
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-xs text-slate-500">
                            <CheckCircle2 className="h-3 w-3" /> none
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-3 text-xs text-slate-400">
                        {formatTimestamp(sample.captured_at)}
                      </td>
                      <td className="px-3 py-3 text-xs text-slate-500">{sample.source}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-4 sm:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-xs tracking-[0.18em] text-cyan-300 uppercase">Multi-channel comparison</p>
            <h2 className="mt-1 text-lg font-semibold text-white">Синхронізована історія</h2>
            <p className="mt-1 text-xs text-slate-500">
              До 8 каналів; несумісні одиниці автоматично розділяються.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {(Object.keys(RANGE_LABELS) as LiveHistoryRange[]).map((range) => (
              <button
                key={range}
                type="button"
                onClick={() => {
                  telemetry.setHistoryRange(range);
                  syncUrl(filters, telemetry.selectedKeys, range);
                }}
                className={`h-9 rounded-xl border px-3 text-xs font-medium transition ${telemetry.historyRange === range ? "border-cyan-300/40 bg-cyan-400/10 text-cyan-100" : "border-white/10 text-slate-400 hover:text-white"}`}
              >
                {RANGE_LABELS[range]}
              </button>
            ))}
          </div>
        </div>

        {selected.length === 0 ? (
          <div className="mt-5 grid min-h-44 place-items-center rounded-2xl border border-dashed border-white/10 bg-[#081a32]/50 p-8 text-center">
            <div>
              <Activity className="mx-auto h-8 w-8 text-slate-600" />
              <p className="mt-3 text-sm font-medium text-slate-200">Оберіть канали в таблиці</p>
              <p className="mt-1 text-xs text-slate-500">
                History requests не виконуються, доки comparison selection порожній.
              </p>
            </div>
          </div>
        ) : telemetry.historyStatus === "loading" ? (
          <div className="mt-5 grid min-h-44 place-items-center rounded-2xl border border-white/[0.07] bg-[#081a32]/50 p-8 text-sm text-slate-400">
            Завантаження повного history window за одним ingestion watermark…
          </div>
        ) : telemetry.historyStatus === "error" ? (
          <div className="mt-5 flex min-h-44 flex-col items-center justify-center rounded-2xl border border-red-300/15 bg-red-400/[0.04] p-8 text-center">
            <AlertTriangle className="h-8 w-8 text-red-300" />
            <p className="mt-3 text-sm font-medium text-red-100">Не вдалося завантажити історію</p>
            <p className="mt-1 max-w-xl text-xs text-red-200/60">
              {telemetry.historyError?.message ?? "Unknown history error"}
            </p>
            <button
              type="button"
              onClick={telemetry.retryHistory}
              className="mt-4 inline-flex h-9 items-center gap-2 rounded-xl border border-red-200/20 px-3 text-xs text-red-100 hover:bg-red-400/10"
            >
              <RefreshCw className="h-3.5 w-3.5" /> Повторити history
            </button>
          </div>
        ) : telemetry.historyWindow && telemetry.historySamples.length > 0 ? (
          <div className="mt-5 space-y-4">
            {[...unitGroups.entries()].map(([unit, identities]) => (
              <ComparisonChart
                key={unit}
                unit={unit}
                identities={identities}
                history={telemetry.historySamples}
                window={telemetry.historyWindow!}
                cursorRatio={cursorRatio}
                onCursorRatioChange={setCursorRatio}
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
