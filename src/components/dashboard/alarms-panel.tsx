import { AlertTriangle, BellRing, CheckCircle2, Info, Timer } from "lucide-react";

import { alarms } from "@/data/dashboard";
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

function telemetryAlarmTitle(sample: TelemetrySample): string {
  if (sample.quality === "sensor_error") {
    return "Помилка датчика";
  }
  if (sample.quality === "communication_error") {
    return "Помилка зв’язку";
  }
  if (sample.alarm === "high") {
    return "Значення вище межі";
  }
  if (sample.alarm === "low") {
    return "Значення нижче межі";
  }
  return "Невідома quality state";
}

function telemetryValue(sample: TelemetrySample): string {
  if (sample.value === null || sample.quality !== "valid") {
    return "—";
  }
  return `${sample.value} ${sample.unit}`;
}

function telemetryTime(sample: TelemetrySample): string {
  return new Intl.DateTimeFormat("uk-UA", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(sample.captured_at));
}

export function AlarmsPanel({
  mode = "demo",
  samples = [],
}: {
  mode?: "demo" | "live";
  samples?: TelemetrySample[];
}) {
  if (mode === "live") {
    const active = samples.filter((sample) => sample.alarm !== null || sample.quality !== "valid");

    if (active.length === 0) {
      return (
        <div className="flex min-h-48 flex-col items-center justify-center p-5 text-center">
          <span className="grid h-10 w-10 place-items-center rounded-xl border border-emerald-300/10 bg-emerald-400/[0.04] text-emerald-300">
            <CheckCircle2 className="h-4 w-4" />
          </span>
          <p className="mt-3 text-[11px] font-medium text-slate-200">Telemetry alarms відсутні</p>
          <p className="mt-1 max-w-52 text-[9px] leading-5 text-slate-500">
            Перевірено latest records: alarm = null, quality = valid.
          </p>
        </div>
      );
    }

    return (
      <div className="space-y-2 p-3 sm:p-4">
        {active.map((sample) => {
          const severity = sample.alarm !== null ? "critical" : "warning";
          const style = severityStyles[severity];
          const Icon = style.component;
          return (
            <article
              key={sample.event_id}
              className={`flex w-full items-start gap-3 rounded-xl border p-3 ${style.border} ${style.bg}`}
            >
              <div
                className={`mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-black/10 ${style.icon}`}
              >
                <Icon className="h-4 w-4" strokeWidth={1.8} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-2">
                  <h3 className={`text-[10px] font-semibold ${style.icon}`}>{telemetryAlarmTitle(sample)}</h3>
                  <span className={`shrink-0 text-[9px] font-semibold ${style.value}`}>
                    {telemetryValue(sample)}
                  </span>
                </div>
                <p className="mt-1 truncate text-[9px] text-slate-500">
                  {sample.equipment_id} · {sample.channel_id} · {sample.metric}
                </p>
                <p className="mt-1.5 flex items-center gap-1 text-[8px] text-slate-600">
                  <Timer className="h-2.5 w-2.5" />
                  {telemetryTime(sample)} · {sample.quality}
                </p>
              </div>
            </article>
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
