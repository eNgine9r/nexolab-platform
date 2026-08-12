"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, LoaderCircle, RotateCcw, Thermometer } from "lucide-react";

import { OverviewChartPanel } from "@/components/dashboard/overview-chart-panel";
import { chartSeries } from "@/data/dashboard";
import type { ChartXDomain } from "@/features/charts/domain";
import { buildOverviewChartGroups, overviewResetDomain } from "@/features/dashboard/overview-chart";
import type { DashboardHistoryRange, DashboardHistoryStatus } from "@/hooks/use-dashboard-telemetry";
import type { DashboardTelemetryStatus } from "@/lib/telemetry/dashboard-state";
import { isTemperatureProbeSample } from "@/lib/telemetry/temperature-channel";
import type { TelemetrySample } from "@/lib/telemetry/types";

const ranges: Array<{ value: DashboardHistoryRange; label: string }> = [
  { value: "1h", label: "1г" },
  { value: "6h", label: "6г" },
  { value: "24h", label: "24г" },
];

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
  range,
  status,
  telemetryStatus,
  historyWindow,
  error,
  onRangeChange,
  onRetry,
}: {
  samples: TelemetrySample[];
  range: DashboardHistoryRange;
  status: DashboardHistoryStatus;
  telemetryStatus: DashboardTelemetryStatus;
  historyWindow: { from: string; to: string } | null;
  error: Error | null;
  onRangeChange: (range: DashboardHistoryRange) => void;
  onRetry: () => void;
}) {
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
  const groups = useMemo(
    () =>
      buildOverviewChartGroups({
        samples,
        status: telemetryStatus,
        xDomain: effectiveDomain,
        hiddenSeriesKeys,
        soloSeriesKey,
      }),
    [effectiveDomain, hiddenSeriesKeys, samples, soloSeriesKey, telemetryStatus],
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
  const rangeLabel = ranges.find((item) => item.value === range)?.label ?? range;

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
      className="mt-4 rounded-2xl border border-white/[0.055] bg-[#071a35]/60 p-3"
      data-testid="overview-history-chart-system"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[10px] font-medium text-slate-200">PostgreSQL history</p>
          <p className="mt-0.5 text-[9px] text-slate-500">
            {samples.length} записів · {seriesCount} температурних каналів
          </p>
        </div>
        <div className="flex gap-1 rounded-xl border border-white/[0.06] p-1">
          {ranges.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => onRangeChange(item.value)}
              className={`rounded-lg px-2.5 py-1.5 text-[9px] ${
                range === item.value ? "bg-blue-600 text-white" : "text-slate-500"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {status === "loading" ? (
        <p className="mt-4 inline-flex items-center gap-2 text-[10px] text-cyan-200">
          <LoaderCircle className="h-4 w-4 animate-spin" /> Завантаження історії…
        </p>
      ) : status === "error" ? (
        <div className="mt-4 flex items-center justify-between rounded-xl border border-amber-300/15 p-3 text-[10px] text-amber-100">
          <span>{error?.message ?? "Не вдалося завантажити історію."}</span>
          <button type="button" onClick={onRetry} aria-label="Повторити завантаження історії">
            <RotateCcw className="h-4 w-4" />
          </button>
        </div>
      ) : renderedPointCount === 0 ? (
        <p className="mt-4 text-[10px] text-slate-500">Немає валідної температурної історії.</p>
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
        </div>
      )}
    </section>
  );
}

function LiveTemperatureGrid({
  status,
  samples,
  historySamples,
  historyRange,
  historyStatus,
  historyWindow,
  historyError,
  onHistoryRangeChange,
  onHistoryRetry,
}: {
  status: DashboardTelemetryStatus;
  samples: TelemetrySample[];
  historySamples: TelemetrySample[];
  historyRange: DashboardHistoryRange;
  historyStatus: DashboardHistoryStatus;
  historyWindow: { from: string; to: string } | null;
  historyError: Error | null;
  onHistoryRangeChange: (range: DashboardHistoryRange) => void;
  onHistoryRetry: () => void;
}) {
  const visible = samples
    .filter(isTemperatureProbeSample)
    .filter(
      (sample) =>
        sample.quality === "valid" || sample.quality === "communication_error" || sample.alarm !== null,
    )
    .sort((left, right) => compareChannels(left.channel_id, right.channel_id));

  return (
    <div className="p-4 sm:p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <p className="text-[10px] tracking-[0.14em] text-cyan-300 uppercase">Production telemetry</p>
          <p className="mt-1 text-[11px] text-slate-400">
            Опитуються лише обрані оператором канали КК1 і КК2
          </p>
        </div>
        <span className="rounded-full border border-white/[0.07] px-3 py-1.5 text-[9px] text-slate-300">
          {status} · {visible.filter((sample) => sample.quality === "valid").length} valid
        </span>
      </div>

      {visible.length === 0 ? (
        <div className="grid min-h-32 place-items-center rounded-2xl border border-dashed border-white/[0.07] text-center">
          <div>
            <Thermometer className="mx-auto h-5 w-5 text-slate-600" />
            <p className="mt-2 text-[10px] text-slate-400">Немає активних температурних каналів.</p>
            <p className="mt-1 text-[9px] text-slate-600">
              Відкрийте керування датчиками у заголовку панелі.
            </p>
          </div>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {visible.map((sample) => {
            const problem = sample.quality !== "valid" || sample.alarm !== null;
            return (
              <article
                key={`${sample.node_id}:${sample.channel_id}`}
                className={`rounded-2xl border p-4 ${
                  problem ? "border-red-300/15 bg-red-400/[0.045]" : "border-cyan-300/10 bg-[#071a35]/70"
                }`}
              >
                <div className="flex items-center gap-3">
                  {problem ? (
                    <AlertTriangle className="h-4 w-4 text-red-300" />
                  ) : (
                    <Thermometer className="h-4 w-4 text-cyan-300" />
                  )}
                  <div>
                    <p className="text-[10px] font-semibold text-white">{sample.channel_id}</p>
                    <p className="text-[9px] text-slate-500">{sample.quality}</p>
                  </div>
                </div>
                <p className="mt-4 text-3xl font-semibold text-white">{formatValue(sample)}</p>
              </article>
            );
          })}
        </div>
      )}

      <HistoryChart
        samples={[...historySamples, ...samples]}
        range={historyRange}
        status={historyStatus}
        telemetryStatus={status}
        historyWindow={historyWindow}
        error={historyError}
        onRangeChange={onHistoryRangeChange}
        onRetry={onHistoryRetry}
      />
    </div>
  );
}

export function TemperatureChart({
  mode = "demo",
  status = "demo",
  samples = [],
  historySamples = [],
  historyRange = "24h",
  historyStatus = "idle",
  historyWindow = null,
  historyError = null,
  onHistoryRangeChange = () => undefined,
  onHistoryRetry = () => undefined,
}: {
  mode?: "demo" | "live";
  status?: DashboardTelemetryStatus;
  samples?: TelemetrySample[];
  historySamples?: TelemetrySample[];
  historyRange?: DashboardHistoryRange;
  historyStatus?: DashboardHistoryStatus;
  historyWindow?: { from: string; to: string } | null;
  historyError?: Error | null;
  onHistoryRangeChange?: (range: DashboardHistoryRange) => void;
  onHistoryRetry?: () => void;
}) {
  if (mode === "live") {
    return (
      <LiveTemperatureGrid
        status={status}
        samples={samples}
        historySamples={historySamples}
        historyRange={historyRange}
        historyStatus={historyStatus}
        historyWindow={historyWindow}
        historyError={historyError}
        onHistoryRangeChange={onHistoryRangeChange}
        onHistoryRetry={onHistoryRetry}
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
