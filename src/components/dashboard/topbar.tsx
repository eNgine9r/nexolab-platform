import Link from "next/link";
import { Bell, CalendarDays, ChevronDown, Menu, Plus, Search } from "lucide-react";

interface TopbarProps {
  title: string;
  onMenuOpen: () => void;
  onCreateSession?: () => void;
  createSessionHref?: string;
}

export function Topbar({
  title,
  onMenuOpen,
  onCreateSession,
  createSessionHref = "/sessions/new",
}: TopbarProps) {
  const createClasses =
    "ml-1 inline-flex h-10 items-center gap-2 rounded-xl bg-blue-600 px-3.5 text-[11px] font-semibold text-white shadow-[0_8px_28px_rgba(0,119,255,.22)] transition hover:bg-blue-500 sm:px-4";
  const createContent = (
    <>
      <Plus className="h-4 w-4" />
      <span className="hidden sm:inline">Нова сесія</span>
    </>
  );

  return (
    <header className="sticky top-0 z-30 flex min-h-[78px] items-center gap-3 border-b border-white/[0.055] bg-[#07172e]/90 px-4 backdrop-blur-xl sm:px-5 xl:px-6">
      <button className="icon-button inline-grid lg:hidden" onClick={onMenuOpen} aria-label="Відкрити меню">
        <Menu className="h-5 w-5" />
      </button>
      <div className="min-w-0 lg:hidden">
        <p className="truncate text-sm font-semibold text-white">{title}</p>
        <p className="text-[10px] text-slate-500">Лабораторія 1</p>
      </div>

      <label className="relative hidden max-w-[390px] min-w-0 flex-1 lg:block">
        <Search className="pointer-events-none absolute top-1/2 left-4 h-4 w-4 -translate-y-1/2 text-slate-500" />
        <input
          type="search"
          placeholder="Пошук пристроїв, сесій, датчиків…"
          className="h-10 w-full rounded-xl border border-white/[0.07] bg-white/[0.025] pr-14 pl-11 text-[12px] text-slate-100 transition outline-none placeholder:text-slate-600 focus:border-blue-400/45 focus:bg-blue-500/[0.035]"
        />
        <span className="absolute top-1/2 right-3 -translate-y-1/2 rounded-md border border-white/[0.06] bg-white/[0.035] px-1.5 py-0.5 text-[9px] text-slate-600">
          ⌘ K
        </span>
      </label>

      <div className="ml-auto flex items-center gap-2">
        <button className="topbar-control hidden sm:flex">
          <CalendarDays className="h-4 w-4 text-slate-500" />
          <span>24 липня 2026</span>
          <ChevronDown className="h-3.5 w-3.5 text-slate-600" />
        </button>
        <button className="topbar-control hidden md:flex">
          <span>Лабораторія 1</span>
          <ChevronDown className="h-3.5 w-3.5 text-slate-600" />
        </button>
        <button className="icon-button relative inline-grid" aria-label="Сповіщення">
          <Bell className="h-[18px] w-[18px]" />
          <span className="absolute -top-1 -right-1 grid h-4 min-w-4 place-items-center rounded-full bg-red-500 px-1 text-[8px] font-semibold text-white">
            12
          </span>
        </button>
        {onCreateSession ? (
          <button onClick={onCreateSession} className={createClasses}>
            {createContent}
          </button>
        ) : (
          <Link href={createSessionHref} className={createClasses}>
            {createContent}
          </Link>
        )}
        <button className="ml-1 hidden items-center gap-2 rounded-xl p-1.5 transition hover:bg-white/[0.04] xl:flex">
          <span className="grid h-8 w-8 place-items-center rounded-full border border-blue-400/45 bg-blue-500/10 text-[11px] font-semibold text-cyan-200">
            IK
          </span>
          <span className="text-left">
            <span className="block text-[10px] font-medium text-slate-100">Інженер</span>
            <span className="block text-[8px] text-slate-600">Administrator</span>
          </span>
          <ChevronDown className="h-3.5 w-3.5 text-slate-600" />
        </button>
      </div>
    </header>
  );
}
