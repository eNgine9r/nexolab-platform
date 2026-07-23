"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, Clock3, Radio, Settings2, Thermometer } from "lucide-react";

import { chartSeries } from "@/data/dashboard";
import type { DashboardTelemetryStatus } from "@/lib/telemetry/dashboard-state";
import type { TelemetrySample } from "@/lib/telemetry/types";

const ranges = ["1г", "6г", "24г", "7д", "30д"];

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
  if (sample.quality === "sensor_error") {
    return "Помилка датчика";
  }
  if (sample.quality === "communication_error") {
    return "Помилка зв’язку";
  }
  if (sample.quality === "unknown") {
    return "Невідома якість";
  }
  return sample.alarm === null
    ? "Valid · без тривоги"
    : `Valid · ${sample.alarm === "high" ? "вище межі" : "нижче межі"}`;
}

function valueLabel(sample: TelemetrySample): string {
  if (sample.value === null || sample.quality !== "valid") {
    return "—";
  }
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

function LiveTemperatureView({
  status,
  samples,
}: {
  status: DashboardTelemetryStatus;
  samples: TelemetrySample[];
}) {
  const byChannel = new Map(samples.map((sample) => [sample.channel_id, sample]));
  const channels = ["106-03", "106-04"];

  return (
    <div className="p-4 sm:p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[10px] tracking-[0.14em] text-cyan-300 uppercase">Production telemetry</p>
          <p className="mt-1 text-[11px] text-slate-400">
            XJP60D · edge-01 · фактичні latest/WebSocket records
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

      <div className="mt-3 flex items-start gap-2 rounded-xl border border-white/[0.055] bg-white/[0.018] p-3 text-[9px] leading-5 text-slate-500">
        <Radio className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cyan-400" />
        Історичні криві в live mode не симулюються. Панель графіка використовуватиме лише реальні records з{" "}
        <code className="text-slate-300">/telemetry/history</code> після підключення history view.
      </div>
    </div>
  );
}

export function TemperatureChart({
  mode = "demo",
  status = "demo",
  samples = [],
}: {
  mode?: "demo" | "live";
  status?: DashboardTelemetryStatus;
  samples?: TelemetrySample[];
}) {
  const [range, setRange] = useState("24г");
  const paths = useMemo(
    () => chartSeries.map((series) => ({ ...series, path: createPath(series.points) })),
    [],
  );

  if (mode === "live") {
    return <LiveTemperatureView status={status} samples={samples} />;
  }

  return (
    <div className="p-4 sm:p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[10px] tracking-[0.14em] text-blue-300 uppercase">Demo telemetry</p>
          <p className="mt-1 text-[11px] text-slate-400">Ізольований preview · не production measurements</p>
        </div>
        <div className="flex items-center gap-1 rounded-xl border border-white/[0.06] bg-black/10 p-1">
          {ranges.map((item) => (
            <button
              key={item}
              onClick={() => setRange(item)}
              className={`rounded-lg px-2.5 py-1.5 text-[9px] font-medium transition ${range === item ? "bg-blue-600 text-white shadow-[0_5px_15px_rgba(0,119,255,.2)]" : "text-slate-500 hover:text-slate-200"}`}
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
