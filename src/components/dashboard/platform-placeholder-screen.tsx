"use client";

import { useState, type ReactNode } from "react";
import { Construction, Layers3 } from "lucide-react";

import { Sidebar } from "@/components/dashboard/sidebar";
import { Topbar } from "@/components/dashboard/topbar";

export function PlatformPlaceholderScreen({
  title,
  eyebrow,
  description,
  icon,
}: {
  title: string;
  eyebrow: string;
  description: string;
  icon?: ReactNode;
}) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="min-h-screen bg-[#06142a] text-slate-100">
      <Sidebar
        open={sidebarOpen}
        activeItem={title}
        onClose={() => setSidebarOpen(false)}
        onSelect={() => undefined}
      />
      <div className="min-h-screen lg:pl-[264px]">
        <Topbar title={title} onMenuOpen={() => setSidebarOpen(true)} />
        <main className="relative overflow-hidden p-4 xl:p-6">
          <div className="pointer-events-none absolute -top-40 -right-24 h-[420px] w-[420px] rounded-full bg-blue-500/[0.07] blur-3xl" />
          <div className="relative mx-auto max-w-[1800px]">
            <section className="grid min-h-[calc(100vh-150px)] place-items-center rounded-3xl border border-white/[0.08] bg-[#08182e]/80 p-6 text-center shadow-[0_24px_80px_rgba(0,0,0,.22)]">
              <div className="max-w-xl">
                <div className="mx-auto grid h-16 w-16 place-items-center rounded-2xl border border-cyan-300/15 bg-cyan-400/[0.06] text-cyan-300">
                  {icon ?? <Layers3 className="h-7 w-7" />}
                </div>
                <p className="mt-5 text-[10px] font-semibold tracking-[0.2em] text-cyan-300 uppercase">
                  {eyebrow}
                </p>
                <h1 className="mt-2 text-2xl font-semibold text-white">{title}</h1>
                <p className="mt-3 text-sm leading-6 text-slate-400">{description}</p>
                <div className="mt-6 inline-flex items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.035] px-4 py-2.5 text-xs text-slate-300">
                  <Construction className="h-4 w-4 text-amber-300" />
                  Модуль відкрито в основному shell; функціональний scope готується окремим Gate.
                </div>
              </div>
            </section>
          </div>
        </main>
      </div>
    </div>
  );
}
