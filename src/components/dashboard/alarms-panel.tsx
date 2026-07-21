import { AlertTriangle, BellRing, Info, Timer } from "lucide-react";
import { alarms } from "@/data/dashboard";

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

export function AlarmsPanel() {
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
