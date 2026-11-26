"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ChevronDown, ChevronUp, LoaderCircle, RotateCcw, Thermometer } from "lucide-react";

import { OverviewChartPanel } from "@/components/dashboard/overview-chart-panel";
import { chartSeries } from "@/data/dashboard";
import { CHART_SERIES_TOKENS, type ChartXDomain } from "@/features/charts/domain";
import { DashboardIntervalStatistics } from "@/components/live-dashboards/dashboard-interval-statistics";
import {
  overviewColumnStatisticsRows,
  overviewStatisticsRows,
} from "@/features/dashboard/overview-statistics";
import {
  overviewRecentTimestamps,
  overviewSeriesStatistics,
  overviewViewportDetail,
  type OverviewHistoryStore,
} from "@/features/dashboard/overview-history";
import { chartPointBudget } from "@/features/charts/point-budget";
import type { IntervalStatistics } from "@/features/charts/interval-statistics";
import { CADENCE_OBSERVATION_LIMIT } from "@/features/live/freshness";
import { mergeViewportDetail } from "@/features/live/live-aggregate-history";
import { liveChannelKey } from "@/features/live/live-telemetry";
import { useDisplayTimeZone } from "@/hooks/use-display-time-zone";
import { DashboardAlertEvents } from "@/components/live-dashboards/dashboard-alert-events";
import { annotateChartGroups } from "@/features/charts/alert-events";
import { useDashboardAlertEvents } from "@/features/live-dashboards/use-dashboard-alert-events";
import { applyFreshnessClock } from "@/features/charts/series-freshness";
import {
  buildOverviewChartBase,
  overviewChartGroupsForDomain,
  overviewResetDomain,
} from "@/features/dashboard/overview-chart";
import { CustomHistoryRangeForm } from "@/components/charts/custom-history-range-form";
import {
  CUSTOM_HISTORY_FIXED_NOTICE,
  CUSTOM_HISTORY_RANGE_LABEL,
  customHistoryRangeKey,
  formatCustomHistoryWindow,
} from "@/features/charts/custom-history-range";
import type {
  DashboardHistoryPreset,
  DashboardHistoryRange,
  DashboardHistoryStatus,
} from "@/hooks/use-dashboard-telemetry";
import type { Xjp60dTargetDiagnostic } from "@/hooks/use-xjp60d-sensor-management";
import type { DashboardTelemetryStatus } from "@/lib/telemetry/dashboard-state";
import { isTemperatureProbeSample } from "@/lib/telemetry/temperature-channel";
import type { TelemetrySample } from "@/lib/telemetry/types";

const COMPACT_SENSOR_LIMIT = 8;

const ranges: Array<{ value: DashboardHistoryPreset; label: string }> = [
  { value: "1h", label: "1 година" },
  { value: "6h", label: "6 годин" },
  { value: "24h", label: "24 години" },
  { value: "7d", label: "7 днів" },
];

const rangeButtonClass = (active: boolean) =>
  `min-h-9 rounded-lg px-3 py-1.5 text-xs font-medium ${
    active ? "bg-blue-600 text-white" : "text-slate-300 hover:bg-white/[0.06]"
  }`;

function compareChannels(left: string, right: string): number {
  const [leftUnit = 0, leftInput = 0] = left.split("-").map(Number);
  const [rightUnit = 0, rightInput = 0] = right.split("-").map(Number);
  return leftUnit - rightUnit || leftInput - rightInput || left.localeCompare(right);
}

function displayUnit(unit: string): string {
  return unit.trim().toLowerCase() === "degc" ? "°C" : unit;
}

function formatValue(sample: TelemetrySample): string {
  if (sample.quality !== "valid" || sample.value === null) return "—";
  return `${new Intl.NumberFormat("uk-UA", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(sample.value)} ${displayUnit(sample.unit)}`;
}

function HistoryChart({
  samples,
  historyStore = null,
  historyVersion = 0,
  range,
  status,
  telemetryStatus,
  historyWindow,
  error,
  onRangeChange,
  onApplyCustomRange,
  onRetry,
}: {
  samples: TelemetrySample[];
  /** RAW history columns (P0 charts); without them `samples` are RAW samples (session views, tests). */
  historyStore?: OverviewHistoryStore | null;
  historyVersion?: number;
  range: DashboardHistoryRange;
  status: DashboardHistoryStatus;
  telemetryStatus: DashboardTelemetryStatus;
  historyWindow: { from: string; to: string } | null;
  error: Error | null;
  onRangeChange: (range: DashboardHistoryPreset) => void;
  onApplyCustomRange?: (fromMs: number | null, toMs: number | null) => void;
  onRetry: () => void;
}) {
  const historical = range === "custom";
  const [customOpen, setCustomOpen] = useState(false);
  const [hiddenSeriesKeys, setHiddenSeriesKeys] = useState<Set<string>>(() => new Set());
  const [soloSeriesKey, setSoloSeriesKey] = useState<string | null>(null);
  const [sharedCursorMs, setSharedCursorMs] = useState<number | null>(null);
  const [viewportDomain, setViewportDomain] = useState<ChartXDomain | null>(null);
  const historyViewKey = `${range}:${historyWindow?.from ?? "pending"}:${historyWindow?.to ?? "pending"}`;
  const resetDomain = useMemo(
    () => overviewResetDomain(range, historyWindow, samples),
    [historyWindow, range, samples],
  );
  const effectiveDomain = viewportDomain ?? resetDomain;
  const displayTimeZone = useDisplayTimeZone();
  const [clockMs, setClockMs] = useState(() => Date.now());
  useEffect(() => {
    const timer = globalThis.setInterval(() => setClockMs(Date.now()), 5_000);
    return () => globalThis.clearInterval(timer);
  }, []);
  // P0 charts: with RAW history columns, a committed zoom/pan shows the original measurements of the
  // visible window (±50 %) merged into the display history; only channels shown on the chart.
  const rawSource = useMemo(
    () =>
      historyStore
        ? {
            latestFor: (key: string) => historyStore.latest.get(key),
            recentTimestampsFor: (key: string) =>
              overviewRecentTimestamps(historyStore.columns[key], CADENCE_OBSERVATION_LIMIT),
          }
        : undefined,
    // historyVersion: the store is mutated in place by live samples.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [historyStore, historyVersion],
  );
  const displayedSamples = useMemo(() => {
    if (!historyStore || !viewportDomain) return samples;
    const shown = new Set(samples.map(liveChannelKey));
    const detail = overviewViewportDetail(historyStore, viewportDomain, chartPointBudget("overview"));
    return [
      ...mergeViewportDetail(samples, {
        ...detail,
        channels: new Set([...detail.channels].filter((key) => shown.has(key))),
        samples: detail.samples.filter((sample) => shown.has(liveChannelKey(sample))),
      }),
    ];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [historyStore, historyVersion, samples, viewportDomain]);
  // #1827: series are built once per display change; a zoom/pan only rebuilds the reduced points.
  const chartBase = useMemo(
    () =>
      buildOverviewChartBase({
        samples: displayedSamples,
        status: telemetryStatus,
        hiddenSeriesKeys,
        soloSeriesKey,
        historical,
        rawSource,
      }),
    [displayedSamples, hiddenSeriesKeys, historical, rawSource, soloSeriesKey, telemetryStatus],
  );
  const builtGroups = useMemo(
    () => overviewChartGroupsForDomain(chartBase, effectiveDomain),
    [chartBase, effectiveDomain],
  );
  // The clock only flips silent series to stale; it never rebuilds scenes.
  const alertEvents = useDashboardAlertEvents({
    enabled: samples.length > 0,
    rangeKey:
      historical && historyWindow ? `overview:${customHistoryRangeKey(historyWindow)}` : `overview:${range}`,
  });
  // A fixed period ends at its own `to`: open alerts extend to the end of the shown window, not to now.
  const fixedWindowEndMs = historical && historyWindow ? Date.parse(historyWindow.to) : Number.NaN;
  const annotationNowMs = Number.isFinite(fixedWindowEndMs) ? fixedWindowEndMs : clockMs;
  const annotatedGroups = useMemo(
    () => annotateChartGroups(builtGroups, alertEvents.alerts, annotationNowMs),
    [alertEvents.alerts, builtGroups, annotationNowMs],
  );
  const groups = useMemo(() => applyFreshnessClock(annotatedGroups, clockMs), [annotatedGroups, clockMs]);
  // Exact statistics: from the RAW columns (cached per range and content) or the RAW samples; never
  // recomputed per render or cursor move.
  const [statisticsCache] = useState(() => new Map<string, IntervalStatistics | null>());
  const statisticsRows = useMemo(
    () =>
      historyStore
        ? overviewColumnStatisticsRows(
            groups,
            (key, fromMs, toMs) => overviewSeriesStatistics(historyStore, statisticsCache, key, fromMs, toMs),
            effectiveDomain,
          )
        : overviewStatisticsRows(groups, samples, effectiveDomain),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [effectiveDomain, groups, historyStore, historyVersion, samples, statisticsCache],
  );
  const seriesCount = groups.reduce((count, group) => count + group.scene.series.length, 0);
  const renderedPointCount = groups.reduce(
    (count, group) =>
      count +
      group.scene.series.reduce(
        (seriesTotal, series) =>
          seriesTotal +
          series.segments.reduce((segmentTotal, segment) => segmentTotal + segment.points.length, 0),
        0,
      ),
    0,
  );
  const rangeLabel =
    historical && historyWindow
      ? formatCustomHistoryWindow(historyWindow, displayTimeZone)
      : (ranges.find((item) => item.value === range)?.label ?? range);

  useEffect(() => {
    void Promise.resolve().then(() => {
      setHiddenSeriesKeys(new Set());
      setSoloSeriesKey(null);
      setSharedCursorMs(null);
      setViewportDomain(null);
    });
  }, [historyViewKey]);

  const toggleSeries = (seriesKey: string) => {
    setSoloSeriesKey(null);
    setHiddenSeriesKeys((current) => {
      const next = new Set(current);
      if (next.has(seriesKey)) next.delete(seriesKey);
      else next.add(seriesKey);
      return next;
    });
  };

  const soloSeries = (seriesKey: string) => {
    setSoloSeriesKey((current) => (current === seriesKey ? null : seriesKey));
  };

  return (
    <section
      className="mt-3 rounded-2xl border border-white/[0.055] bg-[#071a35]/60 p-3"
      data-testid="overview-history-chart-system"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-100">Історія температур</p>
          <p className="mt-0.5 text-xs text-slate-400">
            {samples.length} записів · {seriesCount} каналів
          </p>
        </div>
        <div className="flex flex-wrap gap-1 rounded-xl border border-white/[0.06] p-1">
          {ranges.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => {
                setCustomOpen(false);
                onRangeChange(item.value);
              }}
              aria-pressed={range === item.value}
              className={rangeButtonClass(range === item.value)}
            >
              {item.label}
            </button>
          ))}
          {onApplyCustomRange ? (
            <button
              type="button"
              onClick={() => setCustomOpen(true)}
              aria-pressed={historical}
              className={rangeButtonClass(historical)}
            >
              {CUSTOM_HISTORY_RANGE_LABEL}
            </button>
          ) : null}
        </div>
      </div>

      {customOpen && onApplyCustomRange ? (
        <CustomHistoryRangeForm
          testId="overview-custom-range-form"
          initialWindow={historyWindow}
          onApply={(fromMs, toMs) => {
            onApplyCustomRange(fromMs, toMs);
            setCustomOpen(false);
          }}
          onCancel={() => setCustomOpen(false)}
        />
      ) : null}
      {historical ? (
        <p className="mt-2 text-xs text-slate-400" data-testid="overview-custom-range-notice">
          {historyWindow ? `${formatCustomHistoryWindow(historyWindow, displayTimeZone)} · ` : null}
          {CUSTOM_HISTORY_FIXED_NOTICE}
        </p>
      ) : null}

      {status === "loading" ? (
        <p className="mt-4 inline-flex items-center gap-2 text-xs text-cyan-200">
          <LoaderCircle className="h-4 w-4 animate-spin" /> Завантаження історії…
        </p>
      ) : status === "error" ? (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-300/15 p-3 text-xs text-amber-100">
          <span>{error?.message ?? "Не вдалося завантажити історію."}</span>
          <button
            type="button"
            onClick={onRetry}
            aria-label="Повторити завантаження історії"
            className="inline-flex min-h-9 min-w-9 items-center justify-center rounded-lg border border-amber-300/15"
          >
            <RotateCcw className="h-4 w-4" />
          </button>
        </div>
      ) : renderedPointCount === 0 ? (
        <p className="mt-4 text-xs text-slate-400">Немає валідної температурної історії.</p>
      ) : (
        <div className="mt-3 grid min-w-0 gap-3">
          {groups.map((group) => (
            <OverviewChartPanel
              key={group.id}
              group={group}
              rangeLabel={rangeLabel}
              sharedCursorMs={sharedCursorMs}
              resetDomain={resetDomain}
              onSharedCursorChange={setSharedCursorMs}
              onXDomainChange={setViewportDomain}
              onResetView={() => setViewportDomain(null)}
              onToggleSeries={toggleSeries}
              onSoloSeries={soloSeries}
            />
          ))}
          <DashboardAlertEvents
            events={groups.flatMap((group) => group.scene.events ?? [])}
            status={alertEvents.status}
            message={alertEvents.message}
            displayTimeZone={displayTimeZone}
          />
          <DashboardIntervalStatistics
            rows={statisticsRows}
            fromMs={effectiveDomain.fromMs}
            toMs={effectiveDomain.toMs}
            isViewport={viewportDomain !== null}
            displayTimeZone={displayTimeZone}
          />
        </div>
      )}
    </section>
  );
}

function LiveTemperatureGrid({
  status,
  samples,
  historySamples,
  historyStore = null,
  historyVersion = 0,
  historyRange,
  historyStatus,
  historyWindow,
  historyError,
  onHistoryRangeChange,
  onHistoryCustomRange,
  onHistoryRetry,
  targetDiagnostics,
  allMonitoredChannelsHidden,
}: {
  status: DashboardTelemetryStatus;
  samples: TelemetrySample[];
  historySamples: TelemetrySample[];
  historyStore?: OverviewHistoryStore | null;
  historyVersion?: number;
  historyRange: DashboardHistoryRange;
  historyStatus: DashboardHistoryStatus;
  historyWindow: { from: string; to: string } | null;
  historyError: Error | null;
  onHistoryRangeChange: (range: DashboardHistoryPreset) => void;
  onHistoryCustomRange?: (fromMs: number | null, toMs: number | null) => void;
  onHistoryRetry: () => void;
  targetDiagnostics: Xjp60dTargetDiagnostic[];
  allMonitoredChannelsHidden: boolean;
}) {
  const visible = samples
    .filter(isTemperatureProbeSample)
    .filter(
      (sample) =>
        sample.quality === "valid" ||
        sample.quality === "sensor_error" ||
        sample.quality === "communication_error" ||
        sample.alarm !== null,
    )
    .sort((left, right) => compareChannels(left.channel_id, right.channel_id));
  const visibleChannels = new Set(visible.map((sample) => sample.channel_id));
  const awaitingFirstSample = targetDiagnostics
    .filter((item) => item.state === "initializing" && !visibleChannels.has(item.channel_id))
    .sort((left, right) => compareChannels(left.channel_id, right.channel_id));
  const [sensorGridExpanded, setSensorGridExpanded] = useState(false);
  const sensorTiles = [
    ...awaitingFirstSample.map((diagnostic) => ({
      kind: "initializing" as const,
      key: diagnostic.target_id,
      channelId: diagnostic.channel_id,
      diagnostic,
    })),
    ...visible.map((sample, visualIndex) => ({
      kind: "sample" as const,
      key: `${sample.node_id}:${sample.channel_id}`,
      channelId: sample.channel_id,
      sample,
      visualIndex,
    })),
  ].sort((left, right) => {
    const leftProblem =
      left.kind === "sample" && (left.sample.quality !== "valid" || left.sample.alarm !== null);
    const rightProblem =
      right.kind === "sample" && (right.sample.quality !== "valid" || right.sample.alarm !== null);

    if (leftProblem !== rightProblem) {
      return leftProblem ? -1 : 1;
    }

    return compareChannels(left.channelId, right.channelId);
  });
  const displayedTiles = sensorGridExpanded ? sensorTiles : sensorTiles.slice(0, COMPACT_SENSOR_LIMIT);
  const hiddenSensorCount = Math.max(0, sensorTiles.length - displayedTiles.length);

  return (
    <div className="p-3 sm:p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-[10px] font-semibold text-slate-200">Поточні значення</p>
          <p className="mt-0.5 text-[8px] text-slate-500">
            Обрані канали КК1 і КК2 · {sensorTiles.length} на Огляді
          </p>
        </div>
        <span className="rounded-full border border-white/[0.07] px-2 py-1 text-[8px] text-slate-400">
          {status} · {visible.filter((sample) => sample.quality === "valid").length} валідних
        </span>
      </div>

      {allMonitoredChannelsHidden ? (
        <div className="grid min-h-24 place-items-center rounded-xl border border-dashed border-white/[0.07] px-4 text-center">
          <div>
            <Thermometer className="mx-auto h-4 w-4 text-slate-600" />
            <p className="mt-1.5 text-[9px] text-slate-400">Усі температурні канали приховані на Огляді.</p>
            <p className="mt-0.5 text-[8px] text-slate-600">Безперервний збір даних продовжується.</p>
          </div>
        </div>
      ) : sensorTiles.length === 0 ? (
        <div className="grid min-h-24 place-items-center rounded-xl border border-dashed border-white/[0.07] px-4 text-center">
          <div>
            <Thermometer className="mx-auto h-4 w-4 text-slate-600" />
            <p className="mt-1.5 text-[9px] text-slate-400">Немає активних температурних каналів.</p>
            <p className="mt-0.5 text-[8px] text-slate-600">Додайте канали через налаштування панелі.</p>
          </div>
        </div>
      ) : (
        <>
          <div
            className="grid grid-cols-2 gap-2 md:grid-cols-4 2xl:grid-cols-6"
            data-testid="overview-live-value-grid"
          >
            {displayedTiles.map((tile) => {
              if (tile.kind === "initializing") {
                return (
                  <article
                    key={tile.key}
                    className="min-w-0 rounded-xl border border-cyan-300/10 bg-[#071a35]/60 px-3 py-2.5"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-cyan-300" />
                        <p className="truncate text-[9px] font-semibold text-white">{tile.channelId}</p>
                      </div>
                      <LoaderCircle className="h-3 w-3 shrink-0 animate-spin text-cyan-300" />
                    </div>
                    <p className="mt-1.5 text-sm font-semibold text-slate-400">—</p>
                    <p className="mt-0.5 truncate text-[7px] text-cyan-200">Ініціалізація</p>
                  </article>
                );
              }

              const sample = tile.sample;
              const token = CHART_SERIES_TOKENS[tile.visualIndex % CHART_SERIES_TOKENS.length];
              const problem = sample.quality !== "valid" || sample.alarm !== null;
              return (
                <article
                  key={tile.key}
                  className={`min-w-0 rounded-xl border px-3 py-2.5 ${
                    problem ? "border-red-300/15 bg-red-400/[0.04]" : "border-white/[0.055] bg-[#071a35]/60"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <span
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{ backgroundColor: token.color }}
                        aria-hidden="true"
                      />
                      <p className="truncate text-[9px] font-semibold text-white">{sample.channel_id}</p>
                    </div>
                    {problem ? (
                      <AlertTriangle className="h-3 w-3 shrink-0 text-red-300" aria-label="Проблема каналу" />
                    ) : null}
                  </div>
                  <p className="mt-1.5 truncate text-base font-semibold text-white">{formatValue(sample)}</p>
                  <p className={`mt-0.5 truncate text-[7px] ${problem ? "text-red-300" : "text-slate-500"}`}>
                    {sample.quality}
                  </p>
                </article>
              );
            })}
          </div>
          {sensorTiles.length > COMPACT_SENSOR_LIMIT ? (
            <button
              type="button"
              onClick={() => setSensorGridExpanded((current) => !current)}
              className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-white/[0.06] bg-white/[0.02] px-2.5 py-1.5 text-[8px] font-medium text-slate-400 transition hover:border-cyan-300/20 hover:text-cyan-200"
              aria-expanded={sensorGridExpanded}
            >
              {sensorGridExpanded ? (
                <>
                  <ChevronUp className="h-3 w-3" /> Згорнути
                </>
              ) : (
                <>
                  <ChevronDown className="h-3 w-3" /> + {hiddenSensorCount} датчиків · Показати всі
                </>
              )}
            </button>
          ) : null}
        </>
      )}

      {!allMonitoredChannelsHidden ? (
        <HistoryChart
          samples={historySamples}
          historyStore={historyStore}
          historyVersion={historyVersion}
          range={historyRange}
          status={historyStatus}
          telemetryStatus={status}
          historyWindow={historyWindow}
          error={historyError}
          onRangeChange={onHistoryRangeChange}
          onApplyCustomRange={onHistoryCustomRange}
          onRetry={onHistoryRetry}
        />
      ) : null}
    </div>
  );
}

export function TemperatureChart({
  mode = "demo",
  status = "demo",
  samples = [],
  historySamples = [],
  historyStore = null,
  historyVersion = 0,
  historyRange = "24h",
  historyStatus = "idle",
  historyWindow = null,
  historyError = null,
  onHistoryRangeChange = () => undefined,
  onHistoryCustomRange,
  onHistoryRetry = () => undefined,
  targetDiagnostics = [],
  allMonitoredChannelsHidden = false,
}: {
  mode?: "demo" | "live";
  status?: DashboardTelemetryStatus;
  samples?: TelemetrySample[];
  historySamples?: TelemetrySample[];
  historyStore?: OverviewHistoryStore | null;
  historyVersion?: number;
  historyRange?: DashboardHistoryRange;
  historyStatus?: DashboardHistoryStatus;
  historyWindow?: { from: string; to: string } | null;
  historyError?: Error | null;
  onHistoryRangeChange?: (range: DashboardHistoryPreset) => void;
  onHistoryCustomRange?: (fromMs: number | null, toMs: number | null) => void;
  onHistoryRetry?: () => void;
  targetDiagnostics?: Xjp60dTargetDiagnostic[];
  allMonitoredChannelsHidden?: boolean;
}) {
  if (mode === "live") {
    return (
      <LiveTemperatureGrid
        status={status}
        samples={samples}
        historySamples={historySamples}
        historyStore={historyStore}
        historyVersion={historyVersion}
        historyRange={historyRange}
        historyStatus={historyStatus}
        historyWindow={historyWindow}
        historyError={historyError}
        onHistoryRangeChange={onHistoryRangeChange}
        onHistoryCustomRange={onHistoryCustomRange}
        onHistoryRetry={onHistoryRetry}
        targetDiagnostics={targetDiagnostics}
        allMonitoredChannelsHidden={allMonitoredChannelsHidden}
      />
    );
  }

  return (
    <div className="grid grid-cols-2 gap-2 p-4 sm:grid-cols-4">
      {chartSeries.map((series) => (
        <article key={series.id} className="rounded-xl border border-white/[0.055] p-3">
          <p className="text-[9px] text-slate-500">{series.id}</p>
          <p className="mt-1.5 text-lg text-slate-100">{series.value}</p>
        </article>
      ))}
    </div>
  );
}
