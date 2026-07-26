"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, Clock3, LoaderCircle, Radio, RotateCcw, Settings2, Thermometer } from "lucide-react";

import { chartSeries } from "@/data/dashboard";
import type { DashboardHistoryRange, DashboardHistoryStatus } from "@/hooks/use-dashboard-telemetry";
import type { DashboardTelemetryStatus } from "@/lib/telemetry/dashboard-state";
import { buildTemperatureHistoryChart, mergeTelemetryHistory } from "@/lib/telemetry/history-series";
import type { TelemetrySample } from "@/lib/telemetry/types";

const demoRanges = ["1г", "6г", "24г", "7д", "30д"];
const liveRanges: Array<{ value: DashboardHistoryRange; label: string }> = [
  { value: "1h", label: "1г" },
  { value: "6h", label: "6г" },
  { value: "24h", label: "24г" },
];
const channelColors: Record<string, string> = {
  "106-03": "#00c6e0",
  "106-04": "#7ed321",
};

function createPath(points: readonly number[]) {
  return points
    .map((point, index) => {
      const x = 32 + (index / (points.length - 1)) * 568;
      const y = 162 - (point / 100) * 135;
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
}

function qualityLabel(sample: TelemetrySample): string {
  if (sample.quality === "sensor_error") return "Помилка датчика";
  if (sample.quality === "communication_error") return "Помилка зв’язку";
  if (sample.quality === "unknown") return "Невідома якість";
  return sample.alarm === null
    ? "Valid · без тривоги"
    : `Valid · ${sample.alarm === "high" ? "вище межі" : "нижче межі"}`;
}

function valueLabel(sample: TelemetrySample): string {
  if (sample.value === null || sample.quality !== "valid") return "—";
  return `${new Intl.NumberFormat("uk-UA", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(sample.value)} ${sample.unit}`;
}

function timeLabel(sample: TelemetrySample): string {
  return new Intl.DateTimeFormat("uk-UA", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(sample.captured_at));
}

function axisTime(value: string): string {
  return new Intl.DateTimeFormat("uk-UA", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function temperatureLabel(value: number | null): string {
  return value === null
    ? "—"
    : `${new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 1 }).format(value)} °C`;
}

function LiveHistoryChart({
  latestSamples,
  historySamples,
  historyRange,
  historyStatus,
  historyWindow,
  historyError,
  onHistoryRangeChange,
  onHistoryRetry,
}: {
  latestSamples: TelemetrySample[];
  historySamples: TelemetrySample[];
  historyRange: DashboardHistoryRange;
  historyStatus: DashboardHistoryStatus;
  historyWindow: { from: string; to: string } | null;
  historyError: Error | null;
  onHistoryRangeChange: (range: DashboardHistoryRange) => void;
  onHistoryRetry: () => void;
}) {
  const fallbackTo = new Date();
  const fallbackFrom = new Date(
    fallbackTo.getTime() - (historyRange === "1h" ? 1 : historyRange === "6h" ? 6 : 24) * 60 * 60 * 1000,
  );
  const window = historyWindow ?? {
    from: fallbackFrom.toISOString(),
    to: fallbackTo.toISOString(),
  };
  const merged = useMemo(
    () => mergeTelemetryHistory(historySamples, latestSamples),
    [historySamples, latestSamples],
  );
  const chart = useMemo(() => buildTemperatureHistoryChart(merged, window), [merged, window.from, window.to]);

  return (
    <div className="mt-4 rounded-2xl border border-white/[0.055] bg-[#071a35]/60 p-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[10px] font-medium text-slate-200">PostgreSQL history</p>
          <p className="mt-0.5 text-[9px] text-slate-500">
            {axisTime(chart.from)} — {axisTime(chart.to)} · {merged.length} records
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-xl border border-white/[0.06] bg-black/10 p-1">
          {liveRanges.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => onHistoryRangeChange(item.value)}
              className={`rounded-lg px-2.5 py-1.5 text-[9px] font-medium transition ${
                historyRange === item.value
                  ? "bg-blue-600 text-white shadow-[0_5px_15px_rgba(0,119,255,.2)]"
                  : "text-slate-500 hover:text-slate-200"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {historyStatus === "loading" ? (
        <div className="grid h-[190px] place-items-center text-[10px] text-cyan-200">
          <span className="inline-flex items-center gap-2">
            <LoaderCircle className="h-4 w-4 animate-spin" />
            Завантаження захищеної історії…
          </span>
        </div>
      ) : historyStatus === "error" ? (
        <div className="grid h-[190px] place-items-center text-center">
          <div>
            <AlertTriangle className="mx-auto h-5 w-5 text-amber-300" />
            <p className="mt-2 text-[10px] text-amber-200">
              {historyError?.message ?? "Не вдалося завантажити telemetry history."}
            </p>
            <button
              type="button"
              onClick={onHistoryRetry}
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-[9px] text-slate-200"
            >
              <RotateCcw className="h-3 w-3" />
              Повторити
            </button>
          </div>
        </div>
      ) : chart.series.length === 0 ? (
        <div className="grid h-[190px] place-items-center text-center text-[10px] leading-5 text-slate-500">
          Немає валідних температурних records у вибраному діапазоні.
        </div>
      ) : (
        <>
          <svg
            viewBox="0 0 630 180"
            className="h-[190px] w-full"
            role="img"
            aria-label="Реальний графік історії температур XJP60D"
          >
            {[20, 47, 74, 101, 128, 155].map((y) => (
              <line key={y} x1="32" y1={y} x2="600" y2={y} stroke="rgba(148,163,184,.1)" strokeWidth="1" />
            ))}
            {[32, 174, 316, 458, 600].map((x) => (
              <line key={x} x1={x} y1="20" x2={x} y2="155" stroke="rgba(148,163,184,.055)" strokeWidth="1" />
            ))}
            {chart.series.map((series) => (
              <g key={series.channelId}>
                {series.path ? (
                  <path
                    d={series.path}
                    fill="none"
                    stroke={channelColors[series.channelId] ?? "#38bdf8"}
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                ) : null}
                {series.points.map((point) => (
                  <circle
                    key={point.eventId}
                    cx={point.x}
                    cy={point.y}
                    r="2.2"
                    fill="#071a35"
                    stroke={channelColors[series.channelId] ?? "#38bdf8"}
                    strokeWidth="1.4"
                  />
                ))}
              </g>
            ))}
            <text x="32" y="174" fill="#64748b" fontSize="9">
              {axisTime(chart.from)}
            </text>
            <text x="600" y="174" textAnchor="end" fill="#64748b" fontSize="9">
              {axisTime(chart.to)}
            </text>
            <text x="24" y="25" textAnchor="end" fill="#64748b" fontSize="9">
              {temperatureLabel(chart.maximum)}
            </text>
            <text x="24" y="155" textAnchor="end" fill="#64748b" fontSize="9">
              {temperatureLabel(chart.minimum)}
            </text>
          </svg>
          <div className="mt-2 flex flex-wrap gap-2">
            {chart.series.map((series) => (
              <span
                key={series.channelId}
                className="inline-flex items-center gap-1.5 rounded-full border border-white/[0.06] px-2 py-1 text-[8px] text-slate-400"
              >
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: channelColors[series.channelId] ?? "#38bdf8" }}
                />
                {series.channelId} · {series.points.length}
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function LiveTemperatureView({
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
  const byChannel = new Map(samples.map((sample) => [sample.channel_id, sample]));
  const channels = ["106-03", "106-04"];

  return (
    <div className="p-4 sm:p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[10px] tracking-[0.14em] text-cyan-300 uppercase">Production telemetry</p>
          <p className="mt-1 text-[11px] text-slate-400">
            XJP60D · edge-01 · authenticated latest, WebSocket та PostgreSQL history
          </p>
        </div>
        <span className="rounded-full border border-white/[0.07] bg-white/[0.025] px-3 py-1.5 text-[9px] text-slate-300">
          {status}
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {channels.map((channelId) => {
          const sample = byChannel.get(channelId);
          const hasError = sample !== undefined && sample.quality !== "valid";
          const hasAlarm = sample?.alarm !== null && sample?.alarm !== undefined;

          return (
            <article
              key={channelId}
              className={`rounded-2xl border p-4 ${
                hasError || hasAlarm
                  ? "border-red-300/15 bg-red-400/[0.045]"
                  : "border-cyan-300/10 bg-[#071a35]/70"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span className="grid h-10 w-10 place-items-center rounded-xl border border-white/[0.07] bg-white/[0.025] text-cyan-300">
                    {hasError || hasAlarm ? (
                      <AlertTriangle className="h-4 w-4 text-red-300" />
                    ) : (
                      <Thermometer className="h-4 w-4" />
                    )}
                  </span>
                  <div>
                    <p className="text-[10px] font-semibold text-white">{channelId}</p>
                    <p className="mt-0.5 text-[9px] text-slate-500">XJP60D Unit 106</p>
                  </div>
                </div>
                <span className="rounded-full border border-white/[0.06] bg-black/10 px-2 py-1 text-[8px] text-slate-400">
                  {sample?.quality ?? "no_data"}
                </span>
              </div>

              <p className="mt-5 text-3xl font-semibold tracking-tight text-white">
                {sample === undefined ? "—" : valueLabel(sample)}
              </p>
              <p
                className={`mt-2 text-[10px] font-medium ${
                  hasError || hasAlarm ? "text-red-300" : "text-emerald-300"
                }`}
              >
                {sample === undefined ? "Немає telemetry record" : qualityLabel(sample)}
              </p>
              <div className="mt-3 flex items-center gap-1.5 text-[9px] text-slate-500">
                <Clock3 className="h-3 w-3" />
                {sample === undefined ? "captured_at —" : `captured_at ${timeLabel(sample)}`}
              </div>
            </article>
          );
        })}
      </div>

      <LiveHistoryChart
        latestSamples={samples}
        historySamples={historySamples}
        historyRange={historyRange}
        historyStatus={historyStatus}
        historyWindow={historyWindow}
        historyError={historyError}
        onHistoryRangeChange={onHistoryRangeChange}
        onHistoryRetry={onHistoryRetry}
      />

      <div className="mt-3 flex items-start gap-2 rounded-xl border border-white/[0.055] bg-white/[0.018] p-3 text-[9px] leading-5 text-slate-500">
        <Radio className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cyan-400" />
        Latest/WebSocket freshness та history loading мають незалежні стани. Історичний збій не маскує свіжий
        live record.
      </div>
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
  const [range, setRange] = useState("24г");
  const paths = useMemo(
    () => chartSeries.map((series) => ({ ...series, path: createPath(series.points) })),
    [],
  );

  if (mode === "live") {
    return (
      <LiveTemperatureView
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
    <div className="p-4 sm:p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[10px] tracking-[0.14em] text-blue-300 uppercase">Demo telemetry</p>
          <p className="mt-1 text-[11px] text-slate-400">Ізольований preview · не production measurements</p>
        </div>
        <div className="flex items-center gap-1 rounded-xl border border-white/[0.06] bg-black/10 p-1">
          {demoRanges.map((item) => (
            <button
              key={item}
              onClick={() => setRange(item)}
              className={`rounded-lg px-2.5 py-1.5 text-[9px] font-medium transition ${
                range === item
                  ? "bg-blue-600 text-white shadow-[0_5px_15px_rgba(0,119,255,.2)]"
                  : "text-slate-500 hover:text-slate-200"
              }`}
            >
              {item}
            </button>
          ))}
          <button
            className="ml-1 grid h-7 w-7 place-items-center rounded-lg text-slate-500 transition hover:bg-white/[0.05] hover:text-slate-200"
            aria-label="Налаштування графіка"
          >
            <Settings2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-white/[0.045] bg-[#071a35]/60 p-2">
        <svg
          viewBox="0 0 630 190"
          className="h-[200px] w-full"
          role="img"
          aria-label="Демонстраційний графік температур"
        >
          <defs>
            <linearGradient id="chartFade" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="#0077ff" stopOpacity="0.13" />
              <stop offset="1" stopColor="#0077ff" stopOpacity="0" />
            </linearGradient>
            <filter id="softGlow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="1.8" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>
          {[28, 55, 82, 109, 136, 163].map((y) => (
            <line key={y} x1="32" y1={y} x2="600" y2={y} stroke="rgba(148,163,184,.11)" strokeWidth="1" />
          ))}
          {[32, 145, 258, 371, 484, 600].map((x) => (
            <line key={x} x1={x} y1="20" x2={x} y2="163" stroke="rgba(148,163,184,.055)" strokeWidth="1" />
          ))}
          <path d={`${paths[2].path} L600 163 L32 163 Z`} fill="url(#chartFade)" />
          {paths.map((series) => (
            <g key={series.id} filter="url(#softGlow)">
              <path
                d={series.path}
                fill="none"
                stroke={series.color}
                strokeWidth="1.9"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              {[0, 5, 10, 15, 20, 23].map((index) => {
                const x = 32 + (index / 23) * 568;
                const y = 162 - (series.points[index] / 100) * 135;
                return (
                  <circle
                    key={index}
                    cx={x}
                    cy={y}
                    r="2.1"
                    fill="#071a35"
                    stroke={series.color}
                    strokeWidth="1.4"
                  />
                );
              })}
            </g>
          ))}
          {["00:00", "04:00", "08:00", "12:00", "16:00", "24:00"].map((label, index) => (
            <text
              key={label}
              x={32 + index * 113.6}
              y="181"
              textAnchor={index === 0 ? "start" : index === 5 ? "end" : "middle"}
              fill="#64748b"
              fontSize="9"
            >
              {label}
            </text>
          ))}
          {["20", "10", "0", "−10", "−20", "−30"].map((label, index) => (
            <text key={label} x="24" y={31 + index * 27} textAnchor="end" fill="#64748b" fontSize="9">
              {label}
            </text>
          ))}
        </svg>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {chartSeries.map((series) => (
          <button
            key={series.id}
            className="rounded-xl border border-white/[0.055] bg-white/[0.018] p-2.5 text-left transition hover:border-white/[0.1] hover:bg-white/[0.03]"
          >
            <div className="flex items-center gap-1.5 text-[9px] text-slate-500">
              <span className="h-2 w-2 rounded-[3px]" style={{ backgroundColor: series.color }} />
              {series.id}
            </div>
            <p className="mt-1.5 text-lg font-medium tracking-tight text-slate-100">{series.value}</p>
          </button>
        ))}
      </div>
    </div>
  );
}
