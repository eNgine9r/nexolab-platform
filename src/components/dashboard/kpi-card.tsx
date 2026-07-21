import { Activity, AlertTriangle, Bolt, Network, Radio, Thermometer } from "lucide-react";
import { Sparkline } from "./sparkline";

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

interface KpiCardProps {
  item: {
    label: string;
    value: string;
    detail: string;
    trend: string;
    tone: keyof typeof toneStyles;
    icon: keyof typeof icons;
  };
  index: number;
}

const fallbackSparks = [
  [10, 11, 10, 12, 11, 14, 13, 18, 16, 22],
  [14, 12, 16, 15, 18, 16, 19, 18, 21, 20],
  [12, 13, 13, 14, 14, 15, 16, 16, 16, 17],
  [20, 18, 19, 17, 18, 21, 19, 23, 20, 19],
  [18, 17, 16, 17, 15, 14, 16, 21, 19, 24],
  [12, 12, 13, 14, 13, 16, 17, 16, 20, 19],
];

export function KpiCard({ item, index }: KpiCardProps) {
  const Icon = icons[item.icon];
  const tone = toneStyles[item.tone];

  return (
    <article className="group relative min-w-0 overflow-hidden rounded-2xl border border-white/[0.065] bg-[linear-gradient(145deg,rgba(16,39,76,.93),rgba(8,24,49,.95))] p-3.5 shadow-[0_12px_36px_rgba(0,0,0,.16)] transition duration-300 hover:-translate-y-0.5 hover:border-cyan-300/20 hover:shadow-[0_15px_42px_rgba(0,119,255,.12)]">
      <div className="absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-cyan-300/25 to-transparent opacity-0 transition group-hover:opacity-100" />
      <div className="flex items-start justify-between gap-2">
        <div className={`grid h-9 w-9 place-items-center rounded-xl ${tone.bg}`}>
          <Icon className={`h-[18px] w-[18px] ${tone.icon}`} strokeWidth={1.9} />
        </div>
        <span className="rounded-full border border-white/[0.06] bg-white/[0.025] px-2 py-1 text-[9px] tracking-[0.12em] text-slate-500 uppercase">
          live
        </span>
      </div>
      <p className="mt-3 truncate text-[10px] font-medium text-slate-400">{item.label}</p>
      <p className="mt-1 truncate text-[22px] font-semibold tracking-tight text-slate-50 xl:text-2xl">
        {item.value}
      </p>
      <div className="mt-2 flex items-end justify-between gap-2">
        <div className="min-w-0">
          <p className={`truncate text-[9px] font-medium ${tone.icon}`}>{item.detail}</p>
          <p className="mt-1 truncate text-[8px] text-slate-600">{item.trend}</p>
        </div>
        <Sparkline points={fallbackSparks[index] ?? fallbackSparks[0]} stroke={tone.line} />
      </div>
    </article>
  );
}
