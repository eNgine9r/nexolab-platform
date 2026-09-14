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
}

export function KpiCard({ item }: KpiCardProps) {
  const Icon = icons[item.icon];
  const tone = toneStyles[item.tone];
  const badgeTone = item.badgeTone ?? "demo";

  const isLiveBadge = badgeTone === "live";

  return (
    <article className="group relative min-w-0 overflow-hidden rounded-xl border border-white/[0.06] bg-[linear-gradient(145deg,rgba(16,39,76,.88),rgba(8,24,49,.92))] px-3 py-2.5 transition hover:border-cyan-300/18">
      <div className="flex min-w-0 items-center gap-2.5">
        <div className={`grid h-7 w-7 shrink-0 place-items-center rounded-lg ${tone.bg}`}>
          <Icon className={`h-3.5 w-3.5 ${tone.icon}`} strokeWidth={1.9} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center justify-between gap-2">
            <p className="truncate text-[9px] font-medium text-slate-400">{item.label}</p>
            {isLiveBadge ? (
              <span
                className="inline-flex shrink-0 items-center gap-1 text-[8px] font-medium text-emerald-300"
                aria-label="Live"
                title="Live"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" aria-hidden="true" />
                <span>LIVE</span>
              </span>
            ) : (
              <span
                className={`shrink-0 rounded-full border px-1.5 py-0.5 text-[7px] tracking-[0.1em] uppercase ${badgeStyles[badgeTone]}`}
              >
                {item.badge ?? "demo"}
              </span>
            )}
          </div>
          <div className="mt-0.5 flex min-w-0 items-baseline justify-between gap-2">
            <p className="truncate text-base font-semibold tracking-tight text-slate-50 xl:text-lg">
              {item.value}
            </p>
            <p className={`truncate text-right text-[8px] font-medium ${tone.icon}`}>{item.detail}</p>
          </div>
          <p className="mt-0.5 truncate text-[7px] text-slate-600">{item.trend}</p>
        </div>
      </div>
    </article>
  );
}
