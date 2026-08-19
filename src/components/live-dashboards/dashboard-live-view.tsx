"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  CalendarRange,
  Clock3,
  Download,
  Edit3,
  Gauge,
  Radio,
  RefreshCw,
  Signal,
  WifiOff,
} from "lucide-react";

import { DashboardChartPanel } from "@/components/live-dashboards/dashboard-chart-panel";
import type { ChartXDomain } from "@/features/charts/domain";
import { buildSavedDashboardChartGroups } from "@/features/live-dashboards/chart";
import { LIVE_DASHBOARD_HISTORY_PRESETS } from "@/features/live-dashboards/history-range";
import type { LiveDashboard, LiveDashboardTelemetryStatus } from "@/features/live-dashboards/types";
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

function seriesState(series: LiveDashboardTelemetryModel["series"][number]): string {
  if (!series.latest) return "Немає persisted sample";
  const state = liveTelemetryState(series.latest);
  if (state === "live") return "Live";
  if (state === "stale") return "Застарілі";
  if (state === "sensor_error") return "Помилка датчика";
  if (state === "communication_error") return "Помилка зв’язку";
  return "Невідомий стан";
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
  const [hiddenSeriesKeys, setHiddenSeriesKeys] = useState<Set<string>>(() => new Set());
  const [soloSeriesKey, setSoloSeriesKey] = useState<string | null>(null);
  const [sharedCursorMs, setSharedCursorMs] = useState<number | null>(null);
  const [viewportDomain, setViewportDomain] = useState<ChartXDomain | null>(null);
  const [customOpen, setCustomOpen] = useState(false);
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [customError, setCustomError] = useState<string | null>(null);
  const dashboardViewKey = `${dashboard.id}:${dashboard.version}:${telemetry.historyRange.kind}:${telemetry.historyRange.from}:${telemetry.historyRange.to}`;
  const resetDomain = useMemo(
    () => ({
      fromMs: Date.parse(telemetry.historyWindow.from),
      toMs: Date.parse(telemetry.historyWindow.to),
    }),
    [telemetry.historyWindow.from, telemetry.historyWindow.to],
  );
  const effectiveDomain = viewportDomain ?? resetDomain;
  const chartGroups = useMemo(
    () =>
      buildSavedDashboardChartGroups({
        dashboardId: dashboard.id,
        series: telemetry.series,
        status: telemetry.status,
        xDomain: effectiveDomain,
        hiddenSeriesKeys,
        soloSeriesKey,
      }),
    [dashboard.id, effectiveDomain, hiddenSeriesKeys, soloSeriesKey, telemetry.series, telemetry.status],
  );
  const valueSeries = telemetry.series.filter(
    (item) => item.item.visualization === "value" || item.item.visualization === "gauge",
  );

  useEffect(() => {
    void Promise.resolve().then(() => {
      setHiddenSeriesKeys(new Set());
      setSoloSeriesKey(null);
      setSharedCursorMs(null);
      setViewportDomain(null);
    });
  }, [dashboardViewKey]);

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

  const localInputValue = (value: string): string => {
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return "";
    const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
    return local.toISOString().slice(0, 16);
  };

  const openCustomRange = () => {
    setCustomFrom(localInputValue(telemetry.historyWindow.from));
    setCustomTo(localInputValue(telemetry.historyWindow.to));
    setCustomError(null);
    setCustomOpen(true);
  };

  const applyCustomRange = () => {
    try {
      telemetry.applyCustomHistoryRange(new Date(customFrom), new Date(customTo));
      setCustomError(null);
      setCustomOpen(false);
    } catch (error) {
      setCustomError(error instanceof Error ? error.message : "Некоректний Custom діапазон.");
    }
  };

  const downloadCsv = async () => {
    try {
      const download = await telemetry.exportCsv();
      const url = URL.createObjectURL(download.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = download.filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch {
      // The hook owns the truthful export error state rendered below the controls.
    }
  };

  return (
    <section className="min-w-0 space-y-5" aria-labelledby="live-dashboard-title">
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
              {dashboard.items.length} series · {dashboard.time_window} · display refresh{" "}
              {dashboard.refresh_seconds} с · latest {formatTimestamp(telemetry.lastCapturedAt)}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={telemetry.retry}
              className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-slate-300 hover:border-cyan-300/30 focus-visible:ring-2 focus-visible:ring-cyan-300"
            >
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              Перепідключити
            </button>
            {canManage ? (
              <button
                type="button"
                onClick={onEdit}
                className="inline-flex min-h-10 items-center gap-2 rounded-xl bg-blue-500 px-3 text-sm font-medium text-white hover:bg-blue-400 focus-visible:ring-2 focus-visible:ring-cyan-300"
              >
                <Edit3 className="h-4 w-4" aria-hidden="true" />
                Редагувати
              </button>
            ) : null}
          </div>
        </div>
      </div>

      <div className={`flex items-start gap-3 rounded-2xl border p-4 ${status.classes}`} role="status">
        <StatusIcon
          className={`mt-0.5 h-5 w-5 shrink-0 ${telemetry.status === "connecting" ? "animate-pulse" : ""}`}
          aria-hidden="true"
        />
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
            <article
              key={item.item.id}
              className="rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-5"
              data-testid={`saved-dashboard-${item.item.visualization}-card`}
            >
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
              <h2
                className="mt-3 truncate text-sm font-medium text-slate-300"
                title={`${item.item.channel_id} ${item.item.metric}`}
              >
                {item.item.channel_id} · {item.item.metric}
              </h2>
              <p className="mt-3 text-3xl font-semibold tracking-tight text-white">
                {formatValue(item.latest)}
              </p>
              <p className="mt-3 text-xs text-slate-500">{seriesState(item)}</p>
              <p className="mt-1 text-xs text-slate-600">
                {formatTimestamp(item.latest?.captured_at ?? null)}
              </p>
              {item.item.visualization === "gauge" ? (
                <p className="mt-3 rounded-xl border border-white/[0.06] bg-[#06142a]/70 p-2 text-[11px] leading-4 text-slate-500">
                  Межі gauge не зберігаються доменом; значення показано без вигаданого діапазону.
                </p>
              ) : null}
            </article>
          ))}
        </div>
      ) : null}

      {dashboard.items.length > 0 ? (
        <section
          className="rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-4 sm:p-5"
          aria-label="Saved Dashboard history range and export"
        >
          <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <CalendarRange className="h-4 w-4 text-cyan-300" aria-hidden="true" />
                <h2 className="text-sm font-semibold text-white">Persisted history</h2>
              </div>
              <p className="mt-1 text-xs text-slate-500">
                Діапазон графіка та CSV не змінює фізичний polling або збережене визначення Dashboard.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {LIVE_DASHBOARD_HISTORY_PRESETS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => telemetry.selectHistoryPreset(preset)}
                  className={`min-h-9 rounded-xl border px-3 text-xs font-medium transition ${
                    telemetry.historyRange.kind === preset
                      ? "border-cyan-300/35 bg-cyan-400/10 text-cyan-100"
                      : "border-white/10 text-slate-400 hover:border-cyan-300/25 hover:text-slate-200"
                  }`}
                >
                  {preset}
                </button>
              ))}
              <button
                type="button"
                onClick={openCustomRange}
                className={`min-h-9 rounded-xl border px-3 text-xs font-medium transition ${
                  telemetry.historyRange.kind === "custom"
                    ? "border-cyan-300/35 bg-cyan-400/10 text-cyan-100"
                    : "border-white/10 text-slate-400 hover:border-cyan-300/25 hover:text-slate-200"
                }`}
              >
                Custom
              </button>
              <button
                type="button"
                onClick={() => void downloadCsv()}
                disabled={
                  telemetry.historyStatus === "loading" ||
                  telemetry.exportStatus === "exporting" ||
                  dashboard.items.length === 0
                }
                className="inline-flex min-h-9 items-center gap-2 rounded-xl border border-emerald-300/20 bg-emerald-400/[0.06] px-3 text-xs font-medium text-emerald-100 hover:bg-emerald-400/10 disabled:cursor-not-allowed disabled:opacity-45"
              >
                <Download className="h-4 w-4" aria-hidden="true" />
                {telemetry.exportStatus === "exporting" ? "Експорт…" : "Export CSV"}
              </button>
            </div>
          </div>

          {customOpen ? (
            <div className="mt-4 grid gap-3 rounded-2xl border border-white/[0.07] bg-[#06142a]/70 p-4 md:grid-cols-[1fr_1fr_auto] md:items-end">
              <label className="grid gap-1.5 text-xs text-slate-400">
                Від · локальний час
                <input
                  type="datetime-local"
                  value={customFrom}
                  onChange={(event) => setCustomFrom(event.target.value)}
                  className="min-h-10 rounded-xl border border-white/10 bg-[#081a32] px-3 text-sm text-slate-100 outline-none focus:border-cyan-300/35"
                />
              </label>
              <label className="grid gap-1.5 text-xs text-slate-400">
                До · локальний час
                <input
                  type="datetime-local"
                  value={customTo}
                  onChange={(event) => setCustomTo(event.target.value)}
                  className="min-h-10 rounded-xl border border-white/10 bg-[#081a32] px-3 text-sm text-slate-100 outline-none focus:border-cyan-300/35"
                />
              </label>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={applyCustomRange}
                  className="min-h-10 rounded-xl bg-blue-500 px-4 text-sm font-medium text-white hover:bg-blue-400"
                >
                  Apply
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setCustomOpen(false);
                    setCustomError(null);
                  }}
                  className="min-h-10 rounded-xl border border-white/10 px-4 text-sm text-slate-400 hover:text-slate-200"
                >
                  Cancel
                </button>
              </div>
              {customError ? <p className="text-xs text-red-200 md:col-span-3">{customError}</p> : null}
            </div>
          ) : null}

          {telemetry.historyStatus === "loading" ? (
            <p className="mt-3 text-xs text-cyan-200">Завантаження повної persisted history…</p>
          ) : telemetry.historyStatus === "error" ? (
            <p className="mt-3 text-xs text-red-200">
              {telemetry.historyError?.message ?? "Не вдалося завантажити persisted history."}
            </p>
          ) : null}
          {telemetry.exportError ? (
            <p className="mt-3 text-xs text-red-200">{telemetry.exportError.message}</p>
          ) : null}
        </section>
      ) : null}

      {chartGroups.map((group) => (
        <DashboardChartPanel
          key={group.id}
          group={group}
          rangeLabel={telemetry.historyRange.label}
          sharedCursorMs={sharedCursorMs}
          resetDomain={resetDomain}
          onSharedCursorChange={setSharedCursorMs}
          onXDomainChange={(domain) => setViewportDomain(domain)}
          onResetView={() => setViewportDomain(null)}
          onToggleSeries={toggleSeries}
          onSoloSeries={soloSeries}
        />
      ))}

      <section className="overflow-hidden rounded-3xl border border-white/[0.08] bg-[#091a31]/90">
        <div className="border-b border-white/[0.07] px-5 py-4">
          <h2 className="text-lg font-semibold text-white">Latest selected channels</h2>
          <p className="mt-1 text-xs text-slate-500">
            Кожен рядок відповідає збереженому item; універсальний inventory не запитується.
          </p>
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
                  <td className="px-5 py-3 text-slate-500">
                    {formatTimestamp(item.latest?.captured_at ?? null)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}
