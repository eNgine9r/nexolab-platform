"use client";

import { useMemo } from "react";
import { AlertTriangle, Clock3, LoaderCircle, Radio, RotateCcw, Thermometer } from "lucide-react";

import { chartSeries } from "@/data/dashboard";
import type { DashboardHistoryRange, DashboardHistoryStatus } from "@/hooks/use-dashboard-telemetry";
import type { DashboardTelemetryStatus } from "@/lib/telemetry/dashboard-state";
import type { TelemetrySample } from "@/lib/telemetry/types";

const ranges: Array<{ value: DashboardHistoryRange; label: string }> = [
  { value: "1h", label: "1г" },
  { value: "6h", label: "6г" },
  { value: "24h", label: "24г" },
];

function isXjpTemperature(sample: TelemetrySample): boolean {
  const metric = sample.metric.trim().toLowerCase().replaceAll("-", "_").replaceAll(".", "_");
  return sample.source === "dixell-xjp60d" && (metric === "temperature" || metric.startsWith("temperature_"));
}

function channelOrder(left: TelemetrySample, right: TelemetrySample): number {
  const [leftUnit = 0, leftChannel = 0] = left.channel_id.split("-").map(Number);
  const [rightUnit = 0, rightChannel = 0] = right.channel_id.split("-").map(Number);
  return leftUnit - rightUnit || leftChannel - rightChannel;
}

function formatValue(sample: TelemetrySample): string {
  if (sample.quality !== "valid" || sample.value === null) return "—";
  return `${new Intl.NumberFormat("uk-UA", { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(sample.value)} ${sample.unit}`;
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("uk-UA", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function statusLabel(sample: TelemetrySample): string {
  if (sample.quality === "communication_error") return "Контролер недоступний";
  if (sample.quality === "sensor_error") return "Датчик не підключений або несправний";
  if (sample.alarm === "high") return "Вище верхньої межі";
  if (sample.alarm === "low") return "Нижче нижньої межі";
  return "Live · валідне значення";
}

function HistorySummary({
  samples,
  range,
  state,
  error,
  onRangeChange,
  onRetry,
}: {
  samples: TelemetrySample[];
  range: DashboardHistoryRange;
  state: DashboardHistoryStatus;
  error: Error | null;
  onRangeChange: (range: DashboardHistoryRange) => void;
  onRetry: () => void;
}) {
  const channels = useMemo(
    () =>
      [...new Set(samples.filter(isXjpTemperature).map((sample) => sample.channel_id))].sort((left, right) => {
        const [leftUnit = 0, leftChannel = 0] = left.split("-").map(Number);
        const [rightUnit = 0, rightChannel = 0] = right.split("-").map(Number);
        return leftUnit - rightUnit || leftChannel - rightChannel;
      }),
    [samples],
  );

  return (
    <section className="mt-4 rounded-2xl border border-white/[0.055] bg-[#071a35]/60 p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[10px] font-medium text-slate-200">PostgreSQL history</p>
          <p className="mt-0.5 text-[9px] text-slate-500">
            {samples.length} записів · {channels.length} каналів XJP60D
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-xl border border-white/[0.06] bg-black/10 p-1">
          {ranges.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => onRangeChange(item.value)}
              className={`rounded-lg px-2.5 py-1.5 text-[9px] ${range === item.value ? "bg-blue-600 text-white" : "text-slate-500"}`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>
      {state === "loading" ? (
        <p className="mt-4 inline-flex items-center gap-2 text-[10px] text-cyan-200">
          <LoaderCircle className="h-4 w-4 animate-spin" /> Завантаження історії…
        </p>
      ) : state === "error" ? (
        <div className="mt-4 flex items-center justify-between gap-3 rounded-xl border border-amber-300/15 bg-amber-400/[0.04] p-3 text-[10px] text-amber-100">
          <span>{error?.message ?? "Не вдалося завантажити історію."}</span>
          <button type="button" onClick={onRetry} aria-label="Повторити завантаження історії">
            <RotateCcw className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          {channels.map((channel) => (
            <span key={channel} className="rounded-full border border-white/[0.06] px-2 py-1 text-[8px] text-slate-400">
              {channel}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

function LiveTemperatures({
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
    .filter(isXjpTemperature)
    .filter((sample) => sample.quality === "valid" || sample.quality === "communication_error" || sample.alarm !== null)
    .sort(channelOrder);
  const liveCount = visible.filter((sample) => sample.quality === "valid").length;

  return (
    <div className="p-4 sm:p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[10px] tracking-[0.14em] text-cyan-300 uppercase">Production telemetry</p>
          <p className="mt-1 text-[11px] text-slate-400">Автоматичне виявлення XJP60D · КК1 і КК2</p>
        </div>
        <span className="rounded-full border border-white/[0.07] px-3 py-1.5 text-[9px] text-slate-300">
          {status} · {liveCount} valid
        </span>
      </div>

      {visible.length === 0 ? (
        <div className="rounded-2xl border border-amber-300/15 bg-amber-400/[0.04] p-5 text-sm text-amber-100">
          Немає валідних підключених датчиків. Зареєстровані входи продовжують опитуватися.
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {visible.map((sample) => {
            const problem = sample.quality !== "valid" || sample.alarm !== null;
            const controller = sample.channel_id.split("-")[0] ?? "—";
            return (
              <article
                key={`${sample.node_id}:${sample.channel_id}`}
                className={`rounded-2xl border p-4 ${problem ? "border-red-300/15 bg-red-400/[0.045]" : "border-cyan-300/10 bg-[#071a35]/70"}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <span className="grid h-10 w-10 place-items-center rounded-xl border border-white/[0.07] bg-white/[0.025] text-cyan-300">
                      {problem ? <AlertTriangle className="h-4 w-4 text-red-300" /> : <Thermometer className="h-4 w-4" />}
                    </span>
                    <div>
                      <p className="text-[10px] font-semibold text-white">{sample.channel_id}</p>
                      <p className="mt-0.5 text-[9px] text-slate-500">XJP60D Unit {controller}</p>
                    </div>
                  </div>
                  <span className="rounded-full border border-white/[0.06] px-2 py-1 text-[8px] text-slate-400">
                    {sample.quality}
                  </span>
                </div>
                <p className="mt-5 text-3xl font-semibold tracking-tight text-white">{formatValue(sample)}</p>
                <p className={`mt-2 text-[10px] font-medium ${problem ? "text-red-300" : "text-emerald-300"}`}>
                  {statusLabel(sample)}
                </p>
                <div className="mt-3 flex items-center gap-1.5 text-[9px] text-slate-500">
                  <Clock3 className="h-3 w-3" /> captured_at {formatTime(sample.captured_at)}
                </div>
              </article>
            );
          })}
        </div>
      )}

      <HistorySummary
        samples={[...historySamples, ...samples]}
        range={historyRange}
        state={historyStatus}
        error={historyError}
        onRangeChange={onHistoryRangeChange}
        onRetry={onHistoryRetry}
      />
      <p className="mt-3 flex items-start gap-2 rounded-xl border border-white/[0.055] p-3 text-[9px] text-slate-500">
        <Radio className="h-3.5 w-3.5 shrink-0 text-cyan-400" />
        Новий probe з’являється після першого валідного Modbus циклу без ручної зміни frontend.
      </p>
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
      <LiveTemperatures
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
