import type { ReactNode } from "react";
import { clsx } from "clsx";

interface PanelProps {
  title: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Panel({ title, action, children, className }: PanelProps) {
  return (
    <section className={clsx("panel", className)}>
      <div className="flex min-h-11 items-center justify-between gap-3 border-b border-white/[0.055] px-4 py-3 sm:px-5">
        <h2 className="text-[13px] font-semibold tracking-wide text-slate-100 sm:text-sm">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}
