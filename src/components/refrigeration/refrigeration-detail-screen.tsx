"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { clsx } from "clsx";
import {
  ArrowLeft,
  CircleDot,
  Edit3,
  Filter,
  Thermometer,
  Wifi,
  type LucideIcon,
} from "lucide-react";

import { Sidebar } from "@/components/dashboard/sidebar";
import { Topbar } from "@/components/dashboard/topbar";
import type { LayoutEditorMode } from "@/components/refrigeration/refrigeration-layout-editor";
import { RefrigerationLayoutWorkspace } from "@/components/refrigeration/refrigeration-layout-workspace";
import type {
  EquipmentStatus,
  RefrigerationEquipment,
  SensorSide,
} from "@/data/refrigeration";

const equipmentStatusTone: Record<EquipmentStatus, string> = {
  normal: "border-emerald-400/20 bg-emerald-400/10 text-emerald-300",
  warning: "border-amber-400/20 bg-amber-400/10 text-amber-300",
  alarm: "border-rose-400/20 bg-rose-400/10 text-rose-300",
  offline: "border-slate-400/20 bg-slate-400/10 text-slate-300",
};

const equipmentStatusLabel: Record<EquipmentStatus, string> = {
  normal: "Норма",
  warning: "Увага",
  alarm: "Тривога",
  offline: "Offline",
};

const sideOptions: ReadonlyArray<{
  value: "all" | SensorSide;
  label: string;
}> = [
  { value: "all", label: "Усі" },
  { value: "front", label: "Передній фронт" },
  { value: "rear", label: "Задній фронт" },
];

const shelves = [1, 2, 3, 4] as const;

export function RefrigerationDetailScreen({
  equipment,
}: {
  equipment: RefrigerationEquipment;
}) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [side, setSide] = useState<"all" | SensorSide>("all");
  const [shelf, setShelf] = useState<number | "all">("all");
  const [selectedId, setSelectedId] = useState(
    equipment.sensors[0]?.id ?? null,
  );
  const [layoutMode, setLayoutMode] = useState<LayoutEditorMode>("view");

  const visibleSensors = useMemo(
    () =>
      equipment.sensors.filter(
        (sensor) =>
          (side === "all" || sensor.side === side) &&
          (shelf === "all" || sensor.shelf === shelf),
      ),
    [equipment.sensors, shelf, side],
  );

  const activeSelectedId = visibleSensors.some(
    (sensor) => sensor.id === selectedId,
  )
    ? selectedId
    : (visibleSensors[0]?.id ?? null);
  const selected =
    visibleSensors.find((sensor) => sensor.id === activeSelectedId) ?? null;

  return (
    <div className="min-h-screen bg-[#06142a] text-slate-100">
      <Sidebar
        open={sidebarOpen}
        activeItem="Холодильне обладнання"
        onClose={() => setSidebarOpen(false)}
        onSelect={() => undefined}
      />
      <div className="min-h-screen lg:pl-[264px]">
        <Topbar
          title={equipment.name}
          onMenuOpen={() => setSidebarOpen(true)}
        />
        <main className="p-3 sm:p-4 xl:p-5">
          <div className="mx-auto max-w-[1900px]">
            <header className="mb-3 rounded-2xl border border-white/[0.07] bg-[#091a31]/85 p-4">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <div className="flex items-start gap-3">
                  <Link
                    href="/refrigeration"
                    aria-label="Назад до обладнання"
                    className="mt-0.5 grid h-9 w-9 place-items-center rounded-xl border border-white/10 bg-white/[0.035] text-slate-400 hover:text-white"
                  >
                    <ArrowLeft className="h-4 w-4" />
                  </Link>
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h1 className="text-xl font-semibold text-white">
                        {equipment.name}
                      </h1>
                      <span
                        className={clsx(
                          "rounded-full border px-2.5 py-1 text-[10px]",
                          equipmentStatusTone[equipment.status],
                        )}
                      >
                        {equipmentStatusLabel[equipment.status]}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-slate-500">
                      {equipment.location} · {equipment.model} ·{" "}
                      {equipment.serialNumber}
                    </p>
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.035] px-3 py-2 text-xs text-slate-300"
                  >
                    <Filter className="h-3.5 w-3.5" />
                    Експорт
                  </button>
                  <button
                    type="button"
                    onClick={() => setLayoutMode("edit")}
                    disabled={layoutMode === "edit"}
                    className="inline-flex items-center gap-2 rounded-xl border border-blue-400/25 bg-blue-500/15 px-3 py-2 text-xs font-medium text-blue-200 enabled:hover:bg-blue-500/20 disabled:cursor-default disabled:opacity-60"
                  >
                    <Edit3 className="h-3.5 w-3.5" />
                    {layoutMode === "edit"
                      ? "Редагування активне"
                      : "Редагувати схему"}
                  </button>
                </div>
              </div>
            </header>

            <div className="grid gap-3 2xl:grid-cols-[260px_minmax(0,1fr)_370px]">
              <aside className="space-y-3">
                <Panel title="Інформація">
                  <Info label="Тип" value={equipment.type} />
                  <Info
                    label="Модель"
                    value={`${equipment.manufacturer} ${equipment.model}`}
                  />
                  <Info
                    label="Серійний номер"
                    value={equipment.serialNumber}
                  />
                  <Info
                    label="Температурний клас"
                    value={equipment.temperatureClass}
                  />
                  <Info label="Встановлено" value={equipment.installedAt} />
                  <Info
                    label="Обслуговування"
                    value={equipment.servicedAt}
                  />
                </Panel>

                <Panel title="Поточний стан">
                  <State label="Компресор" value="Увімкнено" />
                  <State label="Вентилятори" value="Увімкнено" />
                  <State label="Відтаювання" value="Неактивне" />
                  <State label="Двері" value="Зачинені" />
                  <State label="Живлення" value="Норма" />
                </Panel>

                <Panel title="Фото обладнання">
                  <Info
                    label="Стан"
                    value={
                      equipment.image
                        ? "Фото прив’язане"
                        : "Очікує завантаження"
                    }
                  />
                  <Info label="Формати" value="JPEG, PNG, WebP · до 15 МБ" />
                  <Info label="Координати" value="Нормалізовані 0..1" />
                </Panel>
              </aside>

              <section className="min-w-0 space-y-3">
                <div className="rounded-2xl border border-white/[0.08] bg-[#08182e]/90 p-3">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <h2 className="text-sm font-semibold text-white">
                        Фільтри датчиків
                      </h2>
                      <p className="mt-1 text-[11px] text-slate-500">
                        {equipment.totalSensors} датчиків · передній і задній
                        фронт · 4 полиці
                      </p>
                    </div>

                    <div className="flex flex-wrap gap-2">
                      {sideOptions.map((option) => (
                        <button
                          key={option.value}
                          type="button"
                          aria-pressed={side === option.value}
                          onClick={() => setSide(option.value)}
                          className={clsx(
                            "rounded-lg border px-2.5 py-1.5 text-[10px]",
                            side === option.value
                              ? "border-blue-400/35 bg-blue-500/15 text-blue-200"
                              : "border-white/[0.07] bg-white/[0.025] text-slate-500",
                          )}
                        >
                          {option.label}
                        </button>
                      ))}

                      <label className="sr-only" htmlFor="shelf-filter">
                        Фільтр за полицею
                      </label>
                      <select
                        id="shelf-filter"
                        value={shelf}
                        onChange={(event) =>
                          setShelf(
                            event.target.value === "all"
                              ? "all"
                              : Number(event.target.value),
                          )
                        }
                        className="rounded-lg border border-white/[0.07] bg-[#0b1e38] px-2.5 py-1.5 text-[10px] text-slate-400 outline-none"
                      >
                        <option value="all">Усі полиці</option>
                        {shelves.map((value) => (
                          <option key={value} value={value}>
                            Полиця {value}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                </div>

                <RefrigerationLayoutWorkspace
                  equipment={equipment}
                  visibleSensors={visibleSensors}
                  selectedId={activeSelectedId}
                  mode={layoutMode}
                  onModeChange={setLayoutMode}
                  onSelect={setSelectedId}
                />

                <div className="grid gap-3 md:grid-cols-4">
                  <Metric
                    label="Середня температура"
                    value={`${equipment.averageTemperatureC} °C`}
                    icon={Thermometer}
                  />
                  <Metric
                    label="Мінімальна"
                    value={`${equipment.minTemperatureC} °C`}
                    icon={Thermometer}
                  />
                  <Metric
                    label="Максимальна"
                    value={`${equipment.maxTemperatureC} °C`}
                    icon={Thermometer}
                  />
                  <Metric
                    label="Online датчики"
                    value={`${equipment.onlineSensors}/${equipment.totalSensors}`}
                    icon={Wifi}
                  />
                </div>
              </section>

              <aside className="min-w-0 rounded-2xl border border-white/[0.08] bg-[#08182e]/90 p-3">
                <div className="mb-3 flex items-center justify-between">
                  <div>
                    <h2 className="text-sm font-semibold text-white">
                      Датчики в реальному часі
                    </h2>
                    <p className="mt-1 text-[10px] text-slate-600">
                      Показано {visibleSensors.length} із {equipment.totalSensors}
                    </p>
                  </div>
                  <CircleDot className="h-4 w-4 text-emerald-400" />
                </div>

                {selected ? (
                  <div
                    className="mb-3 rounded-xl border border-blue-400/20 bg-blue-500/[0.07] p-3"
                    aria-live="polite"
                  >
                    <p className="text-[9px] tracking-wider text-blue-300 uppercase">
                      Вибраний датчик
                    </p>
                    <div className="mt-2 flex items-end justify-between gap-3">
                      <div>
                        <p className="font-semibold text-white">
                          {selected.label} · {selected.name}
                        </p>
                        <p className="mt-1 text-[10px] text-slate-500">
                          Полиця {selected.shelf} · позиція {selected.position}
                        </p>
                      </div>
                      <p className="text-xl font-semibold text-white">
                        {formatTemperature(selected.temperatureC)}
                      </p>
                    </div>
                  </div>
                ) : (
                  <div className="mb-3 rounded-xl border border-dashed border-white/[0.08] p-4 text-center text-xs text-slate-500">
                    Для вибраних фільтрів датчиків немає.
                  </div>
                )}

                <div className="max-h-[660px] space-y-1.5 overflow-y-auto pr-1">
                  {visibleSensors.map((sensor) => (
                    <button
                      key={sensor.id}
                      type="button"
                      aria-label={`Вибрати датчик ${sensor.label} зі списку`}
                      aria-pressed={sensor.id === activeSelectedId}
                      onClick={() => setSelectedId(sensor.id)}
                      className={clsx(
                        "flex w-full items-center gap-2 rounded-xl border p-2 text-left transition",
                        sensor.id === activeSelectedId
                          ? "border-blue-400/30 bg-blue-500/10"
                          : "border-white/[0.05] bg-white/[0.02] hover:bg-white/[0.04]",
                      )}
                    >
                      <span
                        className={clsx(
                          "grid h-7 min-w-7 place-items-center rounded-lg text-[9px] font-bold",
                          sensor.side === "front"
                            ? "bg-emerald-400/10 text-emerald-300"
                            : "bg-blue-400/10 text-blue-300",
                        )}
                      >
                        {sensor.label}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[11px] text-slate-300">
                          {sensor.name}
                        </span>
                        <span className="text-[9px] text-slate-600">
                          Полиця {sensor.shelf}
                        </span>
                      </span>
                      <span className="text-xs font-semibold text-white">
                        {formatTemperature(sensor.temperatureC, false)}
                      </span>
                      <Sparkline values={sensor.trend} />
                    </button>
                  ))}
                </div>
              </aside>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-white/[0.08] bg-[#08182e]/90 p-4">
      <h2 className="mb-3 text-xs font-semibold text-white">{title}</h2>
      <div className="space-y-2.5">{children}</div>
    </section>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[9px] tracking-wider text-slate-600 uppercase">
        {label}
      </p>
      <p className="mt-1 text-[11px] text-slate-300">{value}</p>
    </div>
  );
}

function State({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between text-[11px]">
      <span className="text-slate-500">{label}</span>
      <span className="text-emerald-300">{value}</span>
    </div>
  );
}

function Metric({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon: LucideIcon;
}) {
  return (
    <div className="rounded-xl border border-white/[0.07] bg-[#091a31]/85 p-3">
      <Icon className="h-4 w-4 text-cyan-300" />
      <p className="mt-2 text-[9px] tracking-wider text-slate-600 uppercase">
        {label}
      </p>
      <p className="mt-1 text-sm font-semibold text-white">{value}</p>
    </div>
  );
}

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) {
    return null;
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(0.1, max - min);
  const points = values
    .map(
      (value, index) =>
        `${(index / (values.length - 1)) * 46},${14 - ((value - min) / range) * 11}`,
    )
    .join(" ");

  return (
    <svg
      width="46"
      height="16"
      viewBox="0 0 46 16"
      aria-hidden="true"
      className="text-cyan-400"
    >
      <polyline
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        points={points}
      />
    </svg>
  );
}

function formatTemperature(
  temperatureC: number | null,
  includeUnit = true,
): string {
  if (temperatureC === null) {
    return "—";
  }

  return `${temperatureC.toFixed(1)}°${includeUnit ? " C" : ""}`;
}
