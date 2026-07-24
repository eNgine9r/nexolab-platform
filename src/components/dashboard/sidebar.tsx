"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  AlertTriangle,
  Boxes,
  Camera,
  ChartNoAxesCombined,
  ChevronRight,
  ClipboardCheck,
  Cpu,
  FileText,
  Home,
  LockKeyhole,
  Network,
  Settings,
  Snowflake,
  X,
  Zap,
} from "lucide-react";
import { clsx } from "clsx";
import { BrandLogo } from "./brand-logo";

const navItems = [
  { label: "Огляд", icon: Home, href: "/" },
  { label: "Вузли", icon: Network },
  { label: "Сесії випробувань", icon: ClipboardCheck, href: "/sessions" },
  { label: "Live дані", icon: ChartNoAxesCombined },
  { label: "Схеми обладнання", icon: Boxes },
  { label: "Поштомати", icon: LockKeyhole },
  { label: "Холодильне обладнання", icon: Snowflake, href: "/refrigeration" },
  { label: "Тривоги", icon: AlertTriangle, badge: "12" },
  { label: "Камери", icon: Camera },
  { label: "Енергомоніторинг", icon: Zap },
  { label: "Звіти", icon: FileText },
  { label: "Обладнання", icon: Cpu },
  { label: "Налаштування", icon: Settings },
];

interface SidebarProps {
  open: boolean;
  activeItem: string;
  onClose: () => void;
  onSelect: (item: string) => void;
}

export function Sidebar({ open, activeItem, onClose, onSelect }: SidebarProps) {
  const pathname = usePathname();

  return (
    <>
      <button
        aria-label="Закрити меню"
        className={clsx(
          "fixed inset-0 z-40 bg-slate-950/75 backdrop-blur-sm transition lg:hidden",
          open ? "opacity-100" : "pointer-events-none opacity-0",
        )}
        onClick={onClose}
      />
      <aside
        className={clsx(
          "fixed inset-y-0 left-0 z-50 flex w-[264px] flex-col border-r border-cyan-300/[0.08] bg-[linear-gradient(180deg,#07182f_0%,#06142a_58%,#061329_100%)] shadow-[20px_0_60px_rgba(0,0,0,.24)] transition-transform duration-300 lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-[78px] items-center justify-between border-b border-white/[0.055] px-5">
          <BrandLogo />
          <button className="icon-button inline-grid lg:hidden" onClick={onClose} aria-label="Закрити меню">
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 scrollbar-thin overflow-y-auto px-3 py-4" aria-label="Головна навігація">
          <p className="mb-2 px-3 text-[9px] font-semibold tracking-[0.18em] text-slate-600 uppercase">
            Платформа
          </p>
          <div className="space-y-1">
            {navItems.map(({ label, icon: Icon, badge, href }) => {
              const routeActive = href === "/" ? pathname === "/" : href ? pathname.startsWith(href) : false;
              const active = routeActive || (!href && activeItem === label);
              const classes = clsx(
                "group flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left text-[12px] font-medium transition",
                active
                  ? "border-blue-400/45 bg-blue-500/12 text-white shadow-[inset_0_0_22px_rgba(0,119,255,.07)]"
                  : "border-transparent text-slate-400 hover:border-white/[0.055] hover:bg-white/[0.035] hover:text-slate-100",
              );
              const content = (
                <>
                  <Icon
                    className={clsx(
                      "h-[17px] w-[17px]",
                      active ? "text-cyan-300" : "text-slate-500 group-hover:text-slate-300",
                    )}
                    strokeWidth={1.8}
                  />
                  <span className="min-w-0 flex-1 truncate">{label}</span>
                  {badge ? (
                    <span className="grid min-w-5 place-items-center rounded-full bg-red-500 px-1.5 py-0.5 text-[9px] font-semibold text-white">
                      {badge}
                    </span>
                  ) : (
                    <ChevronRight
                      className={clsx(
                        "h-3.5 w-3.5 transition",
                        active ? "text-blue-400" : "text-slate-700 opacity-0 group-hover:opacity-100",
                      )}
                    />
                  )}
                </>
              );

              return href ? (
                <Link key={label} href={href} className={classes} onClick={onClose}>
                  {content}
                </Link>
              ) : (
                <button
                  key={label}
                  onClick={() => {
                    onSelect(label);
                    onClose();
                  }}
                  className={classes}
                >
                  {content}
                </button>
              );
            })}
          </div>
        </nav>

        <div className="px-4 pb-4">
          <div className="rounded-2xl border border-emerald-300/[0.09] bg-emerald-400/[0.035] p-4">
            <div className="flex items-center gap-2.5">
              <div className="grid h-8 w-8 place-items-center rounded-xl bg-emerald-400/10 text-emerald-400">
                <Activity className="h-4 w-4" />
              </div>
              <div>
                <p className="text-[11px] font-semibold text-slate-100">Система</p>
                <p className="text-[9px] text-emerald-400">Усі сервіси в нормі</p>
              </div>
            </div>
            <div className="mt-3 space-y-2 border-t border-white/[0.055] pt-3 text-[10px] text-slate-400">
              <div className="flex items-center justify-between">
                <span>Локальна мережа</span>
                <span className="text-emerald-400">Online</span>
              </div>
              <div className="flex items-center justify-between">
                <span>Хмарна синхронізація</span>
                <span className="text-emerald-400">Synced</span>
              </div>
            </div>
          </div>
          <div className="mt-3 flex items-center justify-between px-1 text-[9px] text-slate-700">
            <span>© 2026 NEXOLAB</span>
            <span>v0.1.0</span>
          </div>
        </div>
      </aside>
    </>
  );
}
