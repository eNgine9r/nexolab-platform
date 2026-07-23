import {
  AlertCircle,
  CheckCircle2,
  CircleDot,
  Clock3,
  RefreshCw,
  WifiOff,
} from "lucide-react";

import type { DashboardTelemetryStatus } from "@/lib/telemetry/dashboard-state";

interface TelemetryStatusBarProps {
  mode: "demo" | "live";
  status: DashboardTelemetryStatus;
  lastCapturedAt: string | null;
  ageMs: number | null;
  rejectedFutureSamples: number;
  error: Error | null;
  onRetry: () => void;
}

const statusCopy: Record<
  DashboardTelemetryStatus,
  {
    title: string;
    detail: string;
    icon: typeof CheckCircle2;
    classes: string;
  }
> = {
  demo: {
    title: "Demo mode",
    detail: "Показано ізольовані демонстраційні дані",
    icon: CircleDot,
    classes: "border-blue-300/15 bg-blue-400/[0.055] text-blue-200",
  },
  connecting: {
    title: "Connecting",
    detail: "Завантаження latest snapshot і WebSocket connection",
    icon: RefreshCw,
    classes: "border-cyan-300/15 bg-cyan-400/[0.055] text-cyan-200",
  },
  live: {
    title: "Live",
    detail: "REST snapshot синхронізовано, WebSocket активний",
    icon: CheckCircle2,
    classes: "border-emerald-300/15 bg-emerald-400/[0.055] text-emerald-200",
  },
  reconnecting: {
    title: "Reconnecting",
    detail: "Показано останні свіжі значення; канал відновлюється",
    icon: RefreshCw,
    classes: "border-amber-300/15 bg-amber-400/[0.055] text-amber-200",
  },
  stale: {
    title: "Stale",
    detail: "Останні значення прострочені й не вважаються live",
    icon: Clock3,
    classes: "border-amber-300/15 bg-amber-400/[0.055] text-amber-200",
  },
  offline: {
    title: "Offline",
    detail: "Немає свіжої телеметрії від edge-01",
    icon: WifiOff,
    classes: "border-slate-300/15 bg-slate-400/[0.055] text-slate-300",
  },
  error: {
    title: "Error",
    detail: "Backend або runtime contract недоступний",
    icon: AlertCircle,
    classes: "border-red-300/15 bg-red-400/[0.055] text-red-200",
  },
};

function ageLabel(ageMs: number | null): string {
  if (ageMs === null) {
    return "даних ще немає";
  }
  if (ageMs < 1_000) {
    return "щойно";
  }
  if (ageMs < 60_000) {
    return `${Math.floor(ageMs / 1_000)} с тому`;
  }
  return `${Math.floor(ageMs / 60_000)} хв тому`;
}

function timestampLabel(value: string | null): string {
  if (value === null) {
    return "—";
  }
  return new Intl.DateTimeFormat("uk-UA", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

export function TelemetryStatusBar({
  mode,
  status,
  lastCapturedAt,
  ageMs,
  rejectedFutureSamples,
  error,
  onRetry,
}: TelemetryStatusBarProps) {
  const copy = statusCopy[status];
  const Icon = copy.icon;
  const canRetry = mode === "live" && (status === "offline" || status === "error");

  return (
    <section
      className={`mb-3 flex flex-col gap-3 rounded-2xl border px-4 py-3 sm:flex-row sm:items-center ${copy.classes}`}
      aria-live="polite"
      aria-label="Стан live telemetry"
    >
      <div className="flex min-w-0 items-center gap-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-current/15 bg-black/10">
          <Icon
            className={`h-4 w-4 ${status === "connecting" || status === "reconnecting" ? "animate-spin" : ""}`}
          />
        </span>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[11px] font-semibold text-current">{copy.title}</p>
            <span className="rounded-full border border-current/15 bg-black/10 px-2 py-0.5 text-[8px] font-semibold tracking-[0.12em] uppercase">
              {mode}
            </span>
          </div>
          <p className="mt-0.5 text-[9px] text-slate-400">{error?.message ?? copy.detail}</p>
        </div>
      </div>

      <div className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1 text-[9px] text-slate-400">
        <span>
          Останній пакет: <strong className="font-medium text-slate-200">{timestampLabel(lastCapturedAt)}</strong>
        </span>
        <span>
          Freshness: <strong className="font-medium text-slate-200">{ageLabel(ageMs)}</strong>
        </span>
        {rejectedFutureSamples > 0 && (
          <span className="text-amber-300">
            Відхилено future timestamps: {rejectedFutureSamples}
          </span>
        )}
        {canRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex items-center gap-1.5 rounded-lg border border-current/15 bg-black/10 px-2.5 py-1.5 font-medium text-current transition hover:bg-black/20"
          >
            <RefreshCw className="h-3 w-3" />
            Повторити
          </button>
        )}
      </div>
    </section>
  );
}
