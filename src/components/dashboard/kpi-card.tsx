import { Activity, AlertTriangle, Bolt, Network, Radio, Thermometer } from "lucide-react";

const icons = {
  network: Network,
  signal: Radio,
  session: Activity,
  alarm: AlertTriangle,
  energy: Bolt,
  temperature: Thermometer,
};

const toneStyles = {
  blue: { icon: "text-blue-400", bg: "bg-blue-500/10", line: "#0077ff" },
  cyan: { icon: "text-cyan-300", bg: "bg-cyan-400/10", line: "#00c6e0" },
  green: { icon: "text-emerald-400", bg: "bg-emerald-400/10", line: "#22c55e" },
  red: { icon: "text-red-400", bg: "bg-red-500/10", line: "#ff4d4f" },
  amber: { icon: "text-amber-300", bg: "bg-amber-400/10", line: "#f5b301" },
} as const;

const badgeStyles = {
  demo: "border-blue-300/10 bg-blue-400/[0.045] text-blue-300",
  live: "border-emerald-300/10 bg-emerald-400/[0.045] text-emerald-300",
  stale: "border-amber-300/10 bg-amber-400/[0.045] text-amber-300",
  offline: "border-slate-300/10 bg-slate-400/[0.045] text-slate-400",
  error: "border-red-300/10 bg-red-400/[0.045] text-red-300",
} as const;

export interface KpiCardItem {
  label: string;
  value: string;
  detail: string;
  trend: string;
  tone: keyof typeof toneStyles;
  icon: keyof typeof icons;
  badge?: string;
  badgeTone?: keyof typeof badgeStyles;
}

interface KpiCardProps {
  item: KpiCardItem;
  variant?: "default" | "overview";
}

export function KpiCard({ item, variant = "default" }: KpiCardProps) {
  const Icon = icons[item.icon];
  const tone = toneStyles[item.tone];
  const badgeTone = item.badgeTone ?? "demo";

  if (variant === "overview") {
    const showQualityBadge = badgeTone !== "live" && badgeTone !== "demo";
    return (
      <article className="group relative flex min-w-0 flex-col rounded-[18px] border border-white/[0.075] bg-[#0d2037]/85 px-3.5 py-3.5 shadow-[0_10px_28px_rgba(0,0,0,0.10)] transition-colors duration-200 hover:border-cyan-300/25 sm:px-4">
        <div className="flex min-w-0 items-start justify-between gap-2">
          <p className="min-w-0 pt-0.5 text-xs leading-[1.35rem] font-medium text-slate-400">{item.label}</p>
          <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-[10px] ${tone.bg}`}>
            <Icon className={`h-4 w-4 ${tone.icon}`} strokeWidth={1.8} aria-hidden="true" />
          </span>
        </div>
        <p className="mt-2.5 text-[1.55rem] leading-none font-semibold tracking-[-0.045em] break-words text-white tabular-nums sm:text-[1.7rem]">
          {item.value}
        </p>
        <div className="mt-2 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5">
          {item.detail ? (
            <p className="min-w-0 text-[11px] leading-4 break-words text-slate-400" title={item.detail}>
              {item.detail}
            </p>
          ) : null}
          {showQualityBadge ? (
            <span
              className={`inline-flex shrink-0 rounded-md border px-1.5 py-0.5 text-[10px] font-semibold ${badgeStyles[badgeTone]}`}
            >
              {item.badge ?? badgeTone}
            </span>
          ) : null}
        </div>
        {item.trend ? (
          <p className="mt-auto pt-1.5 text-[11px] leading-4 text-slate-500" title={item.trend}>
            {item.trend}
          </p>
        ) : null}
      </article>
    );
  }

  const isLiveBadge = badgeTone === "live";

  return (
    <article className="group relative min-w-0 overflow-hidden rounded-xl border border-white/[0.06] bg-[linear-gradient(145deg,rgba(16,39,76,.88),rgba(8,24,49,.92))] px-3 py-3 transition hover:border-cyan-300/18">
      <div className="flex min-w-0 items-start gap-2.5">
        <div className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg ${tone.bg}`}>
          <Icon className={`h-3.5 w-3.5 ${tone.icon}`} strokeWidth={1.9} aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-start justify-between gap-x-2 gap-y-1">
            <p className="min-w-0 text-[11px] leading-4 font-medium break-words text-slate-300">
              {item.label}
            </p>
            {isLiveBadge ? (
              <span
                className="inline-flex shrink-0 items-center gap-1 text-[10px] leading-4 font-medium text-emerald-300"
                aria-label="Live"
                title="Live"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" aria-hidden="true" />
                <span>LIVE</span>
              </span>
            ) : (
              <span
                className={`shrink-0 rounded-full border px-1.5 py-0.5 text-[10px] leading-4 font-medium uppercase ${badgeStyles[badgeTone]}`}
              >
                {item.badge ?? "demo"}
              </span>
            )}
          </div>
          <p className="mt-1 text-lg leading-6 font-semibold tracking-tight break-words text-slate-50 tabular-nums xl:text-xl">
            {item.value}
          </p>
          {item.detail ? (
            <p className={`mt-0.5 text-[11px] leading-4 font-medium break-words ${tone.icon}`}>
              {item.detail}
            </p>
          ) : null}
          {item.trend ? (
            <p className="mt-1 text-[11px] leading-4 break-words text-slate-400">{item.trend}</p>
          ) : null}
        </div>
      </div>
    </article>
  );
}
