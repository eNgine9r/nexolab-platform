"use client";

import Link from "next/link";
import { useEffect } from "react";
import { AlertTriangle, BellRing, CheckCircle2, Info, LoaderCircle, RefreshCw, Timer } from "lucide-react";

import { alarms } from "@/data/dashboard";
import { useOverviewAlertsReadModel } from "@/features/overview/use-overview-alerts-read-model";
import type { AlertInstance, AlertSeverity } from "@/lib/alerts/types";
import type { TelemetrySample } from "@/lib/telemetry/types";

const severityStyles = {
  critical: {
    border: "border-red-400/20",
    bg: "bg-red-500/[0.055]",
    icon: "text-red-400",
    value: "text-red-400",
    component: BellRing,
  },
  warning: {
    border: "border-amber-300/18",
    bg: "bg-amber-400/[0.045]",
    icon: "text-amber-300",
    value: "text-amber-300",
    component: AlertTriangle,
  },
  info: {
    border: "border-blue-300/15",
    bg: "bg-blue-500/[0.045]",
    icon: "text-cyan-300",
    value: "text-cyan-300",
    component: Info,
  },
} as const;

function visualSeverity(severity: AlertSeverity): keyof typeof severityStyles {
  if (severity === "critical" || severity === "alarm") return "critical";
  if (severity === "warning" || severity === "system") return "warning";
  return "info";
}

function alertTitle(alert: AlertInstance): string {
  if (alert.severity === "critical") return "Критична тривога";
  if (alert.severity === "alarm") return "Аварійне відхилення";
  if (alert.severity === "warning") return "Попередження";
  if (alert.severity === "system") return "Системна тривога";
  return "Інформаційна подія";
}

function alertValue(alert: AlertInstance): string {
  if (alert.trigger_value === null) return "—";
  const unit = typeof alert.context.unit === "string" ? alert.context.unit : "";
  return `${new Intl.NumberFormat("uk-UA", {
    maximumFractionDigits: 3,
  }).format(alert.trigger_value)}${unit ? ` ${unit}` : ""}`;
}

function alertTime(alert: AlertInstance): string {
  return new Intl.DateTimeFormat("uk-UA", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(alert.triggered_at));
}

export function AlarmsPanel({
  mode = "demo",
  organizationId = null,
}: {
  mode?: "demo" | "live";
  organizationId?: string | null;
  samples?: TelemetrySample[];
}) {
  const alertsModel = useOverviewAlertsReadModel({ enabled: mode === "live", organizationId });
  const liveAlerts = alertsModel.value ?? [];

  useEffect(() => {
    if (mode !== "live") return;
    const refresh = window.setInterval(alertsModel.retry, 5_000);
    return () => window.clearInterval(refresh);
  }, [alertsModel.retry, mode]);

  if (mode === "live") {
    if (alertsModel.status === "loading" && alertsModel.value === null) {
      return (
        <div className="grid min-h-48 place-items-center p-5 text-center">
          <div>
            <LoaderCircle className="mx-auto h-5 w-5 animate-spin text-cyan-300" />
            <p className="mt-3 text-[10px] text-slate-500">Завантаження production alerts…</p>
          </div>
        </div>
      );
    }

    if (alertsModel.error && alertsModel.value === null) {
      return (
        <div className="flex min-h-48 flex-col items-center justify-center p-5 text-center">
          <span className="grid h-10 w-10 place-items-center rounded-xl border border-amber-300/15 bg-amber-400/[0.05] text-amber-300">
            <AlertTriangle className="h-4 w-4" />
          </span>
          <p className="mt-3 text-[11px] font-medium text-slate-200">Alerts API недоступний</p>
          <p className="mt-1 max-w-60 text-[9px] leading-5 text-slate-500">{alertsModel.error.message}</p>
          <button className="secondary-button mt-3" onClick={alertsModel.retry}>
            <RefreshCw className="h-3.5 w-3.5" />
            Повторити
          </button>
        </div>
      );
    }

    if (liveAlerts.length === 0) {
      return (
        <div className="flex min-h-48 flex-col items-center justify-center p-5 text-center">
          <span className="grid h-10 w-10 place-items-center rounded-xl border border-emerald-300/10 bg-emerald-400/[0.04] text-emerald-300">
            <CheckCircle2 className="h-4 w-4" />
          </span>
          <p className="mt-3 text-[11px] font-medium text-slate-200">Активні тривоги відсутні</p>
          <p className="mt-1 max-w-52 text-[9px] leading-5 text-slate-500">
            Перевірено organization-scoped alert instances у central backend.
          </p>
          {alertsModel.error ? (
            <p className="mt-2 text-[9px] text-amber-300">
              Оновлення не вдалося; показано останній валідний snapshot.
            </p>
          ) : null}
        </div>
      );
    }

    return (
      <div className="space-y-2 p-3 sm:p-4">
        {alertsModel.error ? (
          <div className="rounded-xl border border-amber-300/15 bg-amber-400/[0.045] px-3 py-2 text-[9px] text-amber-200">
            Оновлення не вдалося; показано останній валідний snapshot.
          </div>
        ) : null}
        {liveAlerts.map((alert) => {
          const style = severityStyles[visualSeverity(alert.severity)];
          const Icon = style.component;
          return (
            <Link
              key={alert.id}
              href="/alerts"
              className={`flex w-full items-start gap-3 rounded-xl border p-3 text-left transition hover:translate-x-0.5 ${style.border} ${style.bg}`}
            >
              <div
                className={`mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-black/10 ${style.icon}`}
              >
                <Icon className="h-4 w-4" strokeWidth={1.8} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-2">
                  <h3 className={`text-[10px] font-semibold ${style.icon}`}>{alertTitle(alert)}</h3>
                  <span className={`shrink-0 text-[9px] font-semibold ${style.value}`}>
                    {alertValue(alert)}
                  </span>
                </div>
                <p className="mt-1 truncate text-[9px] text-slate-500">
                  {alert.equipment_id} · {alert.channel_id} · {alert.metric}
                </p>
                <p className="mt-1.5 flex items-center gap-1 text-[8px] text-slate-600">
                  <Timer className="h-2.5 w-2.5" />
                  {alertTime(alert)} · {alert.state}
                </p>
              </div>
            </Link>
          );
        })}
      </div>
    );
  }

  return (
    <div className="space-y-2 p-3 sm:p-4">
      {alarms.map((alarm) => {
        const style = severityStyles[alarm.severity];
        const Icon = style.component;
        return (
          <button
            key={`${alarm.title}-${alarm.time}`}
            className={`flex w-full items-start gap-3 rounded-xl border p-3 text-left transition hover:translate-x-0.5 ${style.border} ${style.bg}`}
          >
            <div
              className={`mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-black/10 ${style.icon}`}
            >
              <Icon className="h-4 w-4" strokeWidth={1.8} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-start justify-between gap-2">
                <h3 className={`text-[10px] font-semibold ${style.icon}`}>{alarm.title}</h3>
                <span className={`shrink-0 text-[9px] font-semibold ${style.value}`}>{alarm.value}</span>
              </div>
              <p className="mt-1 truncate text-[9px] text-slate-500">{alarm.source}</p>
              <p className="mt-1.5 flex items-center gap-1 text-[8px] text-slate-600">
                <Timer className="h-2.5 w-2.5" />
                {alarm.time}
              </p>
            </div>
          </button>
        );
      })}
    </div>
  );
}
