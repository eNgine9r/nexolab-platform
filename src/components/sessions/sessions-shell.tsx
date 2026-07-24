"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { ArrowLeft, Menu, Plus } from "lucide-react";

import { Sidebar } from "@/components/dashboard/sidebar";

interface SessionsShellProps {
  children: ReactNode;
}

export function SessionsShell({ children }: SessionsShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="min-h-screen bg-[#06142a] text-slate-100">
      <Sidebar
        open={sidebarOpen}
        activeItem="Сесії випробувань"
        onClose={() => setSidebarOpen(false)}
        onSelect={() => undefined}
      />
      <div className="min-h-screen lg:pl-[264px]">
        <header className="sticky top-0 z-30 flex min-h-[78px] items-center gap-3 border-b border-white/[0.055] bg-[#07172e]/90 px-4 backdrop-blur-xl sm:px-5 xl:px-6">
          <button
            className="icon-button inline-grid lg:hidden"
            onClick={() => setSidebarOpen(true)}
            aria-label="Відкрити меню"
          >
            <Menu className="h-5 w-5" />
          </button>
          <Link
            href="/"
            className="hidden items-center gap-2 text-[11px] text-slate-500 transition hover:text-cyan-200 sm:flex"
          >
            <ArrowLeft className="h-4 w-4" />
            Огляд
          </Link>
          <div className="min-w-0">
            <p className="text-[9px] font-semibold tracking-[0.18em] text-cyan-300 uppercase">
              Laboratory workflow
            </p>
            <p className="truncate text-sm font-semibold text-white">Сесії випробувань</p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden rounded-full border border-emerald-300/10 bg-emerald-400/[0.04] px-3 py-1.5 text-[9px] text-emerald-300 md:inline-flex">
              API-only · без demo fallback
            </span>
            <Link href="/sessions/new" className="primary-button gap-2">
              <Plus className="h-4 w-4" />
              Нова сесія
            </Link>
          </div>
        </header>
        <main className="relative overflow-hidden p-3 sm:p-4 xl:p-5 2xl:p-6">
          <div className="pointer-events-none absolute -top-40 -right-24 h-[420px] w-[420px] rounded-full bg-blue-500/[0.07] blur-3xl" />
          <div className="relative mx-auto max-w-[1800px]">{children}</div>
        </main>
      </div>
    </div>
  );
}
