"use client";

import { useMemo } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Clock3,
  Edit3,
  Gauge,
  Radio,
  RefreshCw,
  Signal,
  WifiOff,
} from "lucide-react";

import type {
  LiveDashboard,
  LiveDashboardSeries,
  LiveDashboardTelemetryStatus,
} from "@/features/live-dashboards/types";
import { liveTelemetryState } from "@/features/live/live-telemetry";
import type { LiveDashboardTelemetryModel } from "@/hooks/use-live-dashboard-telemetry";
import type { TelemetrySample } from "@/lib/telemetry/types";

function formatValue(sample: TelemetrySample | null): string {
  if (!sample || sample.value === null || !Number.isFinite(sample.value)) return "—";
  const absolute = Math.abs(sample.value);
  const digits = absolute >= 100 ? 0 : absolute >= 10 ? 1 : 2;
  return `${new Intl.NumberFormat("uk-UA", { maximumFractionDigits: digits }).format(sample.value)} ${sample.unit}`;
}

function formatTimestamp(value: string | null): string {
  if (!value) return "Даних ще немає";
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

function statusPresentation(status: LiveDashboardTelemetryStatus): {
  label: string;
  detail: string;
  classes: string;
  icon: typeof Radio;
} {
  if (status === "live") {
    return {
      label: "Live",
      detail: "Selected-series WebSocket і persisted snapshots синхронізовані.",
      classes: "border-emerald-300/20 bg-emerald-400/[0.07] text-emerald-100",
      icon: Radio,
    };
  }
  if (status === "connecting") {
    return {
      label: "Підключення",
      detail: "Завантажуються тільки вибрані latest/history series.",
      classes: "border-cyan-300/20 bg-cyan-400/[0.07] text-cyan-100",
      icon: Signal,
    };
  }
  if (status === "reconnecting") {
    return {
      label: "Reconnecting",
      detail: "Останні значення збережено, але нові події тимчасово не підтверджені.",
      classes: "border-amber-300/20 bg-amber-400/[0.07] text-amber-100",
      icon: RefreshCw,
    };
  }
  if (status === "stale") {
    return {
      label: "Застарілі дані",
      detail: "Значення залишаються видимими, але не позначаються як live.",
      classes: "border-amber-300/20 bg-amber-400/[0.07] text-amber-100",
      icon: Clock3,
    };
  }
  if (status === "offline") {
    return {
      label: "Offline",
      detail: "Persisted values збережено. Live delivery зараз недоступна.",
      classes: "border-slate-300/15 bg-slate-400/[0.06] text-slate-200",
      icon: WifiOff,
    };
  }
  return {
    label: status === "forbidden" ? "Доступ заборонено" : "Помилка live delivery",
    detail: "Перевірте локальний API, авторизацію та WebSocket path.",
    classes: "border-red-300/20 bg-red-400/[0.07] text-red-100",
    icon: AlertTriangle,
  };
}

function seriesState(series: LiveDashboardSeries): string {
  if (!series.latest) return "Немає persisted sample";
  const state = liveTelemetryState(series.latest);
  if (state === "live") return "Live";
  if (state === "stale") return "Застарілі";
  if (state === "sensor_error") return "Помилка датчика";
  if (state === "communication_error") return "Помилка зв’язку";
  return "Невідомий стан";
}

function SeriesChart({ unit, series }: { unit: string; series: LiveDashboardSeries[] }) {
  const width = 980;
  const height = 300;
  const padding = { left: 58, right: 22, top: 28, bottom: 42 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const samples = series.flatMap((item) => item.history).filter((sample) => sample.value !== null);
  const values = samples.map((sample) => sample.value!).filter(Number.isFinite);
  const timestamps = samples.map((sample) => Date.parse(sample.captured_at)).filter(Number.isFinite);
  const minimum = values.length ? Math.min(...values) : 0;
  const maximum = values.length ? Math.max(...values) : 1;
  const valueRange = Math.max(0.000_001, maximum - minimum);
  const from = timestamps.length ? Math.min(...timestamps) : Date.now() - 60_000;
  const to = timestamps.length ? Math.max(...timestamps) : Date.now();
  const timeRange = Math.max(1, to - from);
  const x = (capturedAt: string) => padding.left + ((Date.parse(capturedAt) - from) / timeRange) * plotWidth;
  const y = (value: number) => padding.top + (1 - (value - minimum) / valueRange) * plotHeight;

  return (
    <section className="rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-white">Історія · {unit}</h2>
          <p className="mt-1 text-xs text-slate-500">
            {series.length} series · bounded history · без впливу на acquisition cadence
          </p>
        </div>
        <div className="flex flex-wrap gap-2" aria-label={`Легенда графіка ${unit}`}>
          {series.map((item) => (
            <span key={item.item.id} className="inline-flex items-center gap-2 rounded-full border border-white/10 px-2.5 py-1 text-[11px] text-slate-300">
              <span
                className="h-2.5 w-2.5 rounded-full border border-white/20"
                style={{ backgroundColor: item.item.color ?? "#00C6E0" }}
                aria-hidden="true"
              />
              {item.item.channel_id} · {item.item.metric}
            </span>
          ))}
        </div>
      </div>

      {samples.length === 0 ? (
        <div className="grid min-h-64 place-items-center text-center text-sm text-slate-500">
          <p>У вибраному time window ще немає persisted history.</p>
        </div>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <svg
            viewBox={`0 0 ${width} ${height}`}
            role="img"
            aria-label={`Графік ${series.length} вибраних series в одиницях ${unit}`}
            className="min-w-[720px]"
          >
            {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
              const gridY = padding.top + ratio * plotHeight;
              const value = maximum - ratio * valueRange;
              return (
                <g key={ratio}>
                  <line x1={padding.left} x2={width - padding.right} y1={gridY} y2={gridY} stroke="rgba(148,163,184,0.12)" />
                  <text x={padding.left - 10} y={gridY + 4} textAnchor="end" fill="#64748b" fontSize="11">
                    {new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 2 }).format(value)}
                  </text>
                </g>
              );
            })}
            {series.map((item) => {
              const numeric = item.history.filter(
                (sample): sample is TelemetrySample & { value: number } =>
                  sample.value !== null && Number.isFinite(sample.value),
              );
              if (numeric.length === 0) return null;
              const points = numeric.map((sample) => `${x(sample.captured_at)},${y(sample.value)}`).join(" ");
              const color = item.item.color ?? "#00C6E0";
              const areaPoints = `${x(numeric[0].captured_at)},${padding.top + plotHeight} ${points} ${x(
                numeric[numeric.length - 1].captured_at,
              )},${padding.top + plotHeight}`;
              return (
                <g key={item.item.id}>
                  {item.item.visualization === "area" ? (
                    <polygon points={areaPoints} fill={color} fillOpacity="0.12" />
                  ) : null}
                  <polyline
                    points={points}
                    fill="none"
                    stroke={color}
                    strokeWidth="2.5"
                    strokeLinejoin="round"
                    strokeLinecap="round"
                  />
                </g>
              );
            })}
            <line x1={padding.left} x2={width - padding.right} y1={padding.top + plotHeight} y2={padding.top + plotHeight} stroke="rgba(148,163,184,0.3)" />
            <text x={padding.left} y={height - 12} fill="#64748b" fontSize="11">
              {formatTimestamp(new Date(from).toISOString())}
            </text>
            <text x={width - padding.right} y={height - 12} textAnchor="end" fill="#64748b" fontSize="11">
              {formatTimestamp(new Date(to).toISOString())}
            </text>
          </svg>
        </div>
      )}
    </section>
  );
}

export function DashboardLiveView({
  dashboard,
  telemetry,
  canManage,
  onBack,
  onEdit,
}: {
  dashboard: LiveDashboard;
  telemetry: LiveDashboardTelemetryModel;
  canManage: boolean;
  onBack: () => void;
  onEdit: () => void;
}) {
  const status = statusPresentation(telemetry.status);
  const StatusIcon = status.icon;
  const chartGroups = useMemo(() => {
    const groups = new Map<string, LiveDashboardSeries[]>();
    for (const item of telemetry.series) {
      if (item.item.visualization !== "line" && item.item.visualization !== "area") continue;
      const current = groups.get(item.item.native_unit) ?? [];
      current.push(item);
      groups.set(item.item.native_unit, current);
    }
    return [...groups.entries()];
  }, [telemetry.series]);
  const valueSeries = telemetry.series.filter(
    (item) => item.item.visualization === "value" || item.item.visualization === "gauge",
  );

  return (
    <section className="space-y-5" aria-labelledby="live-dashboard-title">
      <div className="rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <button
              type="button"
              onClick={onBack}
              className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-cyan-200"
            >
              <ArrowLeft className="h-4 w-4" aria-hidden="true" />
              До library
            </button>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <h1 id="live-dashboard-title" className="text-2xl font-semibold text-white sm:text-3xl">
                {dashboard.name}
              </h1>
              <span className="rounded-full border border-white/10 px-2.5 py-1 text-xs text-slate-400">
                v{dashboard.version}
              </span>
            </div>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
              {dashboard.description ?? "Збережений channel-scoped operator workspace."}
            </p>
            <p className="mt-2 text-xs text-slate-500">
              {dashboard.items.length} series · {dashboard.time_window} · display refresh {dashboard.refresh_seconds} с ·
              latest {formatTimestamp(telemetry.lastCapturedAt)}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={telemetry.retry}
              className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-slate-300 hover:border-cyan-300/30"
            >
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              Перепідключити
            </button>
            {canManage ? (
              <button
                type="button"
                onClick={onEdit}
                className="inline-flex min-h-10 items-center gap-2 rounded-xl bg-blue-500 px-3 text-sm font-medium text-white hover:bg-blue-400"
              >
                <Edit3 className="h-4 w-4" aria-hidden="true" />
                Редагувати
              </button>
            ) : null}
          </div>
        </div>
      </div>

      <div className={`flex items-start gap-3 rounded-2xl border p-4 ${status.classes}`} role="status">
        <StatusIcon className={`mt-0.5 h-5 w-5 shrink-0 ${telemetry.status === "connecting" ? "animate-pulse" : ""}`} aria-hidden="true" />
        <div>
          <p className="font-semibold">{status.label}</p>
          <p className="mt-1 text-sm opacity-75">{status.detail}</p>
          {telemetry.error ? <p className="mt-1 text-xs opacity-65">{telemetry.error.message}</p> : null}
        </div>
      </div>

      {dashboard.items.length === 0 ? (
        <div className="grid min-h-72 place-items-center rounded-3xl border border-dashed border-white/10 bg-[#081a32]/55 p-8 text-center">
          <div>
            <Gauge className="mx-auto h-8 w-8 text-slate-500" aria-hidden="true" />
            <h2 className="mt-3 text-lg font-semibold text-white">Dashboard не містить каналів</h2>
            <p className="mt-2 text-sm text-slate-500">Редагування потрібне до запуску live view.</p>
          </div>
        </div>
      ) : null}

      {valueSeries.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {valueSeries.map((item) => (
            <article key={item.item.id} className="rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-5">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-semibold tracking-[0.12em] text-slate-500 uppercase">
                  {item.item.visualization === "gauge" ? "Gauge value" : "Current value"}
                </span>
                <span
                  className="h-3 w-3 rounded-full border border-white/20"
                  style={{ backgroundColor: item.item.color ?? "#00C6E0" }}
                  aria-hidden="true"
                />
              </div>
              <h2 className="mt-3 truncate text-sm font-medium text-slate-300" title={`${item.item.channel_id} ${item.item.metric}`}>
                {item.item.channel_id} · {item.item.metric}
              </h2>
              <p className="mt-3 text-3xl font-semibold tracking-tight text-white">{formatValue(item.latest)}</p>
              <p className="mt-3 text-xs text-slate-500">{seriesState(item)}</p>
              <p className="mt-1 text-xs text-slate-600">{formatTimestamp(item.latest?.captured_at ?? null)}</p>
              {item.item.visualization === "gauge" ? (
                <p className="mt-3 rounded-xl border border-white/[0.06] bg-[#06142a]/70 p-2 text-[11px] leading-4 text-slate-500">
                  Межі gauge не зберігаються доменом; значення показано без вигаданого діапазону.
                </p>
              ) : null}
            </article>
          ))}
        </div>
      ) : null}

      {chartGroups.map(([unit, series]) => (
        <SeriesChart key={unit} unit={unit} series={series} />
      ))}

      <section className="overflow-hidden rounded-3xl border border-white/[0.08] bg-[#091a31]/90">
        <div className="border-b border-white/[0.07] px-5 py-4">
          <h2 className="text-lg font-semibold text-white">Latest selected channels</h2>
          <p className="mt-1 text-xs text-slate-500">Кожен рядок відповідає збереженому item; універсальний inventory не запитується.</p>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-[#06142a]/70 text-xs tracking-[0.08em] text-slate-500 uppercase">
              <tr>
                <th className="px-5 py-3 font-medium">Канал</th>
                <th className="px-5 py-3 font-medium">Показник</th>
                <th className="px-5 py-3 font-medium">Значення</th>
                <th className="px-5 py-3 font-medium">Стан</th>
                <th className="px-5 py-3 font-medium">Captured at</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.06]">
              {telemetry.series.map((item) => (
                <tr key={item.item.id} className="text-slate-300">
                  <td className="px-5 py-3 font-medium text-slate-100">{item.item.channel_id}</td>
                  <td className="px-5 py-3">{item.item.metric}</td>
                  <td className="px-5 py-3 font-semibold text-white">{formatValue(item.latest)}</td>
                  <td className="px-5 py-3">{seriesState(item)}</td>
                  <td className="px-5 py-3 text-slate-500">{formatTimestamp(item.latest?.captured_at ?? null)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}
