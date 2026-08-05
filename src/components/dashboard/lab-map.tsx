"use client";

import Link from "next/link";
import {
  AlertTriangle,
  Box,
  Camera,
  CircleDashed,
  Cpu,
  ImageOff,
  LoaderCircle,
  RefreshCcw,
  Snowflake,
} from "lucide-react";

import type { LayoutCatalogItem, LayoutCatalogState } from "@/features/equipment-layouts/layout-catalog";
import { useEquipmentLayoutsCatalog } from "@/hooks/use-equipment-layouts-catalog";

const demoZones = [
  { label: "Кліматична камера", value: "4.2 °C", x: "11%", y: "18%", icon: Snowflake, tone: "green" },
  { label: "Холодильні вітрини", value: "2.1 °C", x: "66%", y: "13%", icon: Snowflake, tone: "green" },
  { label: "Центральний вузол", value: "Pi-06", x: "48%", y: "47%", icon: Cpu, tone: "blue" },
  { label: "Зона поштоматів", value: "5.1 °C", x: "9%", y: "70%", icon: Box, tone: "green" },
  { label: "Зона камер", value: "22.4 °C", x: "67%", y: "70%", icon: Camera, tone: "amber" },
] as const;

const layoutStateMeta: Record<LayoutCatalogState, { label: string; className: string }> = {
  "published-current": {
    label: "Опубліковано",
    className: "border-emerald-300/15 bg-emerald-400/[0.06] text-emerald-300",
  },
  "published-with-draft": {
    label: "Є зміни",
    className: "border-amber-300/15 bg-amber-400/[0.06] text-amber-300",
  },
  "draft-only": {
    label: "Чернетка",
    className: "border-blue-300/15 bg-blue-400/[0.06] text-blue-300",
  },
  "no-image": {
    label: "Без зображення",
    className: "border-slate-300/15 bg-slate-400/[0.06] text-slate-300",
  },
  empty: {
    label: "Не налаштовано",
    className: "border-slate-300/15 bg-slate-400/[0.06] text-slate-300",
  },
  failed: {
    label: "Недоступно",
    className: "border-red-300/15 bg-red-400/[0.06] text-red-300",
  },
};

type LabMapProps = {
  mode: "demo" | "live";
  enabled: boolean;
  organizationId: string | null;
};

export function LabMap({ mode, enabled, organizationId }: LabMapProps) {
  const catalog = useEquipmentLayoutsCatalog({
    enabled: mode === "live" && enabled && Boolean(organizationId),
    organizationId,
  });

  if (mode === "demo") return <DemoLabMap />;

  if (!organizationId) {
    return (
      <LayoutState
        icon={CircleDashed}
        title="Організацію не вибрано"
        message="Схеми обладнання не запитувалися. Виберіть активну організацію у верхній панелі."
      />
    );
  }

  if (catalog.state === "idle" || catalog.state === "loading") {
    return (
      <LayoutState
        icon={LoaderCircle}
        iconClassName="animate-spin text-cyan-300"
        title="Завантаження схем"
        message="Отримуємо збережені чернетки та опубліковані ревізії без запуску опитування обладнання."
      />
    );
  }

  if (catalog.state === "error" && catalog.items.length === 0) {
    return (
      <LayoutState
        icon={AlertTriangle}
        iconClassName="text-red-300"
        title="Каталог схем недоступний"
        message={catalog.error ?? "Не вдалося отримати локальний каталог схем обладнання."}
        retry={catalog.retry}
      />
    );
  }

  if (catalog.items.length === 0) {
    return (
      <LayoutState
        icon={ImageOff}
        title="Схеми ще не налаштовані"
        message="У локальному каталозі немає холодильного обладнання зі схемою або чернеткою."
      />
    );
  }

  return <LayoutSummary items={catalog.items} refreshing={catalog.state === "refreshing"} />;
}

function LayoutSummary({ items, refreshing }: { items: LayoutCatalogItem[]; refreshing: boolean }) {
  const published = items.filter(
    (item) => item.layoutState === "published-current" || item.layoutState === "published-with-draft",
  ).length;
  const drafts = items.filter(
    (item) => item.layoutState === "draft-only" || item.layoutState === "published-with-draft",
  ).length;
  const unconfigured = items.filter(
    (item) => item.layoutState === "empty" || item.layoutState === "no-image",
  ).length;
  const failed = items.filter((item) => item.layoutState === "failed").length;

  return (
    <div className="p-3 sm:p-4" aria-live="polite">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label="Стан схем обладнання">
        <SummaryMetric label="Усього" value={items.length} />
        <SummaryMetric label="Опубліковано" value={published} />
        <SummaryMetric label="Чернетки" value={drafts} />
        <SummaryMetric label="Не готові" value={unconfigured + failed} />
      </div>

      <div className="mt-3 space-y-2" aria-label="Останні схеми обладнання">
        {items.slice(0, 4).map((item) => {
          const meta = layoutStateMeta[item.layoutState];
          return (
            <article
              key={item.equipment.id}
              className="flex min-w-0 items-center justify-between gap-3 rounded-xl border border-white/[0.06] bg-white/[0.025] px-3 py-2.5"
            >
              <div className="min-w-0">
                <p className="truncate text-[9px] font-semibold tracking-[0.14em] text-cyan-300 uppercase">
                  {item.equipment.code}
                </p>
                <p className="truncate text-[11px] font-medium text-slate-100">{item.equipment.name}</p>
                <p className="truncate text-[9px] text-slate-500">
                  {item.equipment.location || "Розташування не вказано"}
                </p>
              </div>
              <span
                className={`shrink-0 rounded-full border px-2 py-1 text-[8px] font-semibold ${meta.className}`}
              >
                {meta.label}
              </span>
            </article>
          );
        })}
      </div>

      <div className="mt-3 flex items-center justify-between gap-3 text-[9px] text-slate-500">
        <span className="inline-flex items-center gap-1.5">
          {refreshing ? <LoaderCircle className="h-3 w-3 animate-spin text-cyan-300" /> : null}
          {refreshing ? "Оновлення локального каталогу…" : "Дані зі сховища схем, без Modbus-операцій"}
        </span>
        <OverviewLayoutsLink />
      </div>
    </div>
  );
}

function SummaryMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-white/[0.06] bg-[#061831] px-3 py-2">
      <p className="text-[8px] tracking-[0.12em] text-slate-500 uppercase">{label}</p>
      <p className="mt-1 text-lg font-semibold text-white">{value}</p>
    </div>
  );
}

function LayoutState({
  icon: Icon,
  iconClassName = "text-slate-400",
  title,
  message,
  retry,
}: {
  icon: typeof CircleDashed;
  iconClassName?: string;
  title: string;
  message: string;
  retry?: () => void;
}) {
  return (
    <div className="grid min-h-[238px] place-items-center p-4 text-center" role="status">
      <div className="max-w-sm">
        <Icon className={`mx-auto h-7 w-7 ${iconClassName}`} />
        <h3 className="mt-3 text-sm font-semibold text-slate-100">{title}</h3>
        <p className="mt-2 text-[10px] leading-5 text-slate-500">{message}</p>
        <div className="mt-4 flex items-center justify-center gap-2">
          {retry ? (
            <button
              type="button"
              onClick={retry}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.08] px-2.5 py-1.5 text-[9px] text-slate-300 hover:border-cyan-300/25 hover:text-white"
            >
              <RefreshCcw className="h-3 w-3" />
              Повторити
            </button>
          ) : null}
          <OverviewLayoutsLink />
        </div>
      </div>
    </div>
  );
}

function OverviewLayoutsLink() {
  return (
    <Link href="/equipment-layouts" className="text-[9px] font-medium text-cyan-300 hover:text-cyan-200">
      Відкрити каталог
    </Link>
  );
}

function DemoLabMap() {
  return (
    <div className="p-3 sm:p-4">
      <div className="mb-2 flex items-center justify-between gap-3 text-[8px] text-blue-200">
        <span className="rounded-full border border-blue-300/15 bg-blue-400/[0.06] px-2 py-1 font-semibold tracking-[0.12em] uppercase">
          Demo mode
        </span>
        <span>Ілюстративна схема, не лабораторні дані</span>
      </div>
      <div
        className="relative min-h-[238px] overflow-hidden rounded-xl border border-blue-400/10 bg-[#061831]"
        aria-label="Демонстраційна схема лабораторії"
      >
        <div className="lab-grid absolute inset-0 opacity-70" />
        <svg viewBox="0 0 640 290" className="absolute inset-0 h-full w-full opacity-45" aria-hidden="true">
          <g fill="none" stroke="#0077ff" strokeWidth="1.2">
            <path d="M28 28H248V112H315V31H606V142H545V261H329V213H187V263H28Z" />
            <path d="M98 28v84m80-84v84m137-81v111m94-111v84m83-84v111M28 142h159m0-30v101m142-71h216M98 213h89m142 0h216" />
            <path
              d="M210 112h105m-39 0v30m133-30h136m-53 30v71M187 178h142m-82-36v71"
              strokeDasharray="4 4"
            />
          </g>
        </svg>
        {demoZones.map((zone) => {
          const Icon = zone.icon;
          return (
            <div
              key={zone.label}
              className="absolute z-10 min-w-[122px] rounded-xl border border-blue-300/15 bg-[#0b2445]/90 p-2.5 text-left shadow-[0_8px_26px_rgba(0,0,0,.22)] backdrop-blur-sm"
              style={{ left: zone.x, top: zone.y }}
            >
              <div className="flex items-center gap-1.5 text-[8px] text-slate-400">
                <Icon className="h-3 w-3 text-cyan-300" />
                {zone.label}
              </div>
              <div className="mt-1 flex items-center gap-1.5 text-[11px] font-semibold text-slate-100">
                <span
                  className={`h-2 w-2 rounded-full ${
                    zone.tone === "amber"
                      ? "bg-amber-400"
                      : zone.tone === "blue"
                        ? "bg-blue-400"
                        : "bg-emerald-400"
                  }`}
                />
                {zone.value}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
