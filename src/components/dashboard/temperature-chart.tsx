"use client";

import { useMemo } from "react";
import { AlertTriangle, LoaderCircle, RotateCcw, Thermometer } from "lucide-react";

import { chartSeries } from "@/data/dashboard";
import type {
  DashboardHistoryRange,
  DashboardHistoryStatus,
} from "@/hooks/use-dashboard-telemetry";
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

function formatValue(sample: TelemetrySample): string {
  if (sample.quality !== "valid" || sample.value === null) return "—";
  return `${new Intl.NumberFormat("uk-UA", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(sample.value)} ${sample.unit}`;
}

function channelColor(channelId: string): string {
  const hue = [...channelId].reduce(
    (value, character) => (value * 31 + character.charCodeAt(0)) % 360,
    0,
  );
  return `hsl(${hue} 78% 60%)`;
}

type Series = {
  channelId: string;
  path: string;
  points: Array<{ id: string; x: number; y: number }>;
};

function buildSeries(samples: readonly TelemetrySample[]): Series[] {
  const accepted = samples
    .filter(isTemperatureProbeSample)
    .filter(
      (sample): sample is TelemetrySample & { value: number } =>
        sample.quality === "valid" &&
        sample.value !== null &&
        Number.isFinite(sample.value) &&
        Number.isFinite(Date.parse(sample.captured_at)),
    )
    .sort((left, right) => Date.parse(left.captured_at) - Date.parse(right.captured_at));
  if (accepted.length === 0) return [];

  const times = accepted.map((sample) => Date.parse(sample.captured_at));
  const values = accepted.map((sample) => sample.value);
  const from = Math.min(...times);
  const to = Math.max(...times);
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const timeSpan = Math.max(1, to - from);
  const valueSpan = Math.max(1, maximum - minimum);
  const channelIds = [...new Set(accepted.map((sample) => sample.channel_id))].sort(
    compareChannels,
  );

  return channelIds.map((channelId) => {
    const points = accepted
      .filter((sample) => sample.channel_id === channelId)
      .map((sample) => ({
        id: sample.event_id,
        x: 32 + ((Date.parse(sample.captured_at) - from) / timeSpan) * 568,
        y: 20 + (1 - (sample.value - minimum) / valueSpan) * 135,
      }));
    return {
      channelId,
      points,
      path: points
        .map(
          (point, index) =>
            `${index === 0 ? "M" : "L"}${point.x.toFixed(2)} ${point.y.toFixed(2)}`,
        )
        .join(" "),
    };
  });
}

function HistoryChart({
  samples,
  range,
  status,
  error,
  onRangeChange,
  onRetry,
}: {
  samples: TelemetrySample[];
  range: DashboardHistoryRange;
  status: DashboardHistoryStatus;
  error: Error | null;
  onRangeChange: (range: DashboardHistoryRange) => void;
  onRetry: () => void;
}) {
  const series = useMemo(() => buildSeries(samples), [samples]);
  return (
    <section className="mt-4 rounded-2xl border border-white/[0.055] bg-[#071a35]/60 p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[10px] font-medium text-slate-200">PostgreSQL history</p>
          <p className="mt-0.5 text-[9px] text-slate-500">
            {samples.length} записів · {series.length} температурних каналів
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
      ) : series.length === 0 ? (
        <p className="mt-4 text-[10px] text-slate-500">Немає валідної температурної історії.</p>
      ) : (
        <>
          <svg
            viewBox="0 0 630 180"
            className="mt-3 h-[190px] w-full"
            role="img"
            aria-label="Реальний графік історії температур XJP60D"
          >
            {[20, 47, 74, 101, 128, 155].map((y) => (
              <line key={y} x1="32" y1={y} x2="600" y2={y} stroke="rgba(148,163,184,.1)" />
            ))}
            {series.map((item) => (
              <g key={item.channelId}>
                <path
                  d={item.path}
                  fill="none"
                  stroke={channelColor(item.channelId)}
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                {item.points.map((point) => (
                  <circle
                    key={point.id}
                    cx={point.x}
                    cy={point.y}
                    r="2"
                    fill="#071a35"
                    stroke={channelColor(item.channelId)}
                  />
                ))}
              </g>
            ))}
          </svg>
          <div className="flex flex-wrap gap-2">
            {series.map((item) => (
              <span
                key={item.channelId}
                className="rounded-full border border-white/[0.06] px-2 py-1 text-[8px] text-slate-400"
              >
                {item.channelId} · {item.points.length}
              </span>
            ))}
          </div>
        </>
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
  historyError,
  onHistoryRangeChange,
  onHistoryRetry,
}: {
  status: DashboardTelemetryStatus;
  samples: TelemetrySample[];
  historySamples: TelemetrySample[];
  historyRange: DashboardHistoryRange;
  historyStatus: DashboardHistoryStatus;
  historyError: Error | null;
  onHistoryRangeChange: (range: DashboardHistoryRange) => void;
  onHistoryRetry: () => void;
}) {
  const visible = samples
    .filter(isTemperatureProbeSample)
    .filter(
      (sample) =>
        sample.quality === "valid" ||
        sample.quality === "communication_error" ||
        sample.alarm !== null,
    )
    .sort((left, right) => compareChannels(left.channel_id, right.channel_id));

  return (
    <div className="p-4 sm:p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <p className="text-[10px] tracking-[0.14em] text-cyan-300 uppercase">
            Production telemetry
          </p>
          <p className="mt-1 text-[11px] text-slate-400">
            Автоматичне виявлення входів КК1 і КК2
          </p>
        </div>
        <span className="rounded-full border border-white/[0.07] px-3 py-1.5 text-[9px] text-slate-300">
          {status} · {visible.filter((sample) => sample.quality === "valid").length} valid
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {visible.map((sample) => {
          const problem = sample.quality !== "valid" || sample.alarm !== null;
          return (
            <article
              key={`${sample.node_id}:${sample.channel_id}`}
              className={`rounded-2xl border p-4 ${
                problem
                  ? "border-red-300/15 bg-red-400/[0.045]"
                  : "border-cyan-300/10 bg-[#071a35]/70"
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

      <HistoryChart
        samples={[...historySamples, ...samples]}
        range={historyRange}
        status={historyStatus}
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
