import { Clock3 } from "lucide-react";
import { sessions } from "@/data/dashboard";

const accents = {
  cyan: "bg-cyan-400 shadow-[0_0_12px_rgba(0,198,224,.22)]",
  green: "bg-emerald-400 shadow-[0_0_12px_rgba(34,197,94,.22)]",
  amber: "bg-amber-400 shadow-[0_0_12px_rgba(245,179,1,.22)]",
  violet: "bg-violet-500 shadow-[0_0_12px_rgba(168,85,247,.22)]",
};

export function SessionsPanel() {
  return (
    <div className="divide-y divide-white/[0.045] px-4 py-1 sm:px-5">
      {sessions.map((session) => (
        <button key={session.name} className="group w-full py-3 text-left">
          <div className="flex items-center justify-between gap-3">
            <h3 className="truncate text-[10px] font-medium text-slate-100 transition group-hover:text-cyan-200">
              {session.name}
            </h3>
            <span className="text-[9px] font-semibold text-slate-300">{session.progress}%</span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/[0.055]">
            <div
              className={`h-full rounded-full ${accents[session.accent]}`}
              style={{ width: `${session.progress}%` }}
            />
          </div>
          <div className="mt-2 flex items-center justify-between text-[8px] text-slate-600">
            <span>{session.stage}</span>
            <span className="flex items-center gap-1">
              <Clock3 className="h-2.5 w-2.5" />
              До завершення: {session.remaining}
            </span>
          </div>
        </button>
      ))}
    </div>
  );
}
