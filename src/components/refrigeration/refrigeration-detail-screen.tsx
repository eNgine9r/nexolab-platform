"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowLeft, CircleDot, Edit3, Filter, Menu, Snowflake, Thermometer, Wifi } from "lucide-react";
import { clsx } from "clsx";

import type { RefrigerationEquipment, RefrigerationSensor, SensorSide } from "@/data/refrigeration";
import { Sidebar } from "@/components/dashboard/sidebar";
import { Topbar } from "@/components/dashboard/topbar";

const markerTone = {
  normal: "border-emerald-300/70 bg-emerald-500/20 text-emerald-100 shadow-[0_0_16px_rgba(16,185,129,.2)]",
  warning: "border-amber-300/80 bg-amber-500/20 text-amber-100 shadow-[0_0_16px_rgba(245,158,11,.25)]",
  alarm: "border-rose-300/80 bg-rose-500/25 text-rose-100 shadow-[0_0_20px_rgba(244,63,94,.32)]",
  "no-data": "border-slate-400/60 bg-slate-600/30 text-slate-200",
};

export function RefrigerationDetailScreen({ equipment }: { equipment: RefrigerationEquipment }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [side, setSide] = useState<"all" | SensorSide>("all");
  const [shelf, setShelf] = useState<number | "all">("all");
  const [selectedId, setSelectedId] = useState(equipment.sensors[0]?.id ?? null);

  const visibleSensors = useMemo(() => equipment.sensors.filter((sensor) =>
    (side === "all" || sensor.side === side) && (shelf === "all" || sensor.shelf === shelf),
  ), [equipment.sensors, side, shelf]);

  const selected = equipment.sensors.find((sensor) => sensor.id === selectedId) ?? null;

  return (
    <div className="min-h-screen bg-[#06142a] text-slate-100">
      <Sidebar open={sidebarOpen} activeItem="Холодильне обладнання" onClose={() => setSidebarOpen(false)} onSelect={() => undefined} />
      <div className="min-h-screen lg:pl-[264px]">
        <Topbar title={equipment.name} onMenuOpen={() => setSidebarOpen(true)} />
        <main className="p-3 sm:p-4 xl:p-5">
          <div className="mx-auto max-w-[1900px]">
            <header className="mb-3 rounded-2xl border border-white/[0.07] bg-[#091a31]/85 p-4">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <div className="flex items-start gap-3">
                  <Link href="/refrigeration" aria-label="Назад до обладнання" className="mt-0.5 grid h-9 w-9 place-items-center rounded-xl border border-white/10 bg-white/[0.035] text-slate-400 hover:text-white"><ArrowLeft className="h-4 w-4" /></Link>
                  <div><div className="flex flex-wrap items-center gap-2"><h1 className="text-xl font-semibold text-white">{equipment.name}</h1><span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2.5 py-1 text-[10px] text-emerald-300">Норма</span></div><p className="mt-1 text-xs text-slate-500">{equipment.location} · {equipment.model} · {equipment.serialNumber}</p></div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.035] px-3 py-2 text-xs text-slate-300"><Filter className="h-3.5 w-3.5" /> Експорт</button>
                  <button className="inline-flex items-center gap-2 rounded-xl border border-blue-400/25 bg-blue-500/15 px-3 py-2 text-xs font-medium text-blue-200"><Edit3 className="h-3.5 w-3.5" /> Редагувати схему</button>
                </div>
              </div>
            </header>

            <div className="grid gap-3 2xl:grid-cols-[260px_minmax(0,1fr)_370px]">
              <aside className="space-y-3">
                <Panel title="Інформація">
                  <Info label="Тип" value={equipment.type} /><Info label="Модель" value={`${equipment.manufacturer} ${equipment.model}`} /><Info label="Серійний номер" value={equipment.serialNumber} /><Info label="Температурний клас" value={equipment.temperatureClass} /><Info label="Встановлено" value={equipment.installedAt} /><Info label="Обслуговування" value={equipment.servicedAt} />
                </Panel>
                <Panel title="Поточний стан">
                  <State label="Компресор" value="Увімкнено" /><State label="Вентилятори" value="Увімкнено" /><State label="Відтаювання" value="Неактивне" /><State label="Двері" value="Зачинені" /><State label="Живлення" value="Норма" />
                </Panel>
              </aside>

              <section className="min-w-0 space-y-3">
                <div className="rounded-2xl border border-white/[0.08] bg-[#08182e]/90 p-3">
                  <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div><h2 className="text-sm font-semibold text-white">Інтерактивна схема вітрини</h2><p className="mt-1 text-[11px] text-slate-500">48 датчиків · нормалізовані координати · front/rear</p></div>
                    <div className="flex flex-wrap gap-2">
                      {(["all", "front", "rear"] as const).map((value) => <button key={value} onClick={() => setSide(value)} className={clsx("rounded-lg border px-2.5 py-1.5 text-[10px]", side === value ? "border-blue-400/35 bg-blue-500/15 text-blue-200" : "border-white/[0.07] bg-white/[0.025] text-slate-500")}>{value === "all" ? "Усі" : value === "front" ? "Передній фронт" : "Задній фронт"}</button>)}
                      <select value={shelf} onChange={(event) => setShelf(event.target.value === "all" ? "all" : Number(event.target.value))} className="rounded-lg border border-white/[0.07] bg-[#0b1e38] px-2.5 py-1.5 text-[10px] text-slate-400 outline-none"><option value="all">Усі полиці</option>{[1,2,3,4].map((value) => <option key={value} value={value}>Полиця {value}</option>)}</select>
                    </div>
                  </div>

                  <div className="relative aspect-[16/10] overflow-hidden rounded-xl border border-cyan-300/[0.1] bg-[radial-gradient(circle_at_50%_10%,rgba(34,211,238,.12),transparent_42%),linear-gradient(160deg,#0a1f37,#030b15)]">
                    <div className="absolute inset-x-[8%] bottom-[3%] top-[5%] rounded-xl border border-slate-500/30 bg-[linear-gradient(90deg,#111c27_0_2.5%,#26394a_2.5%_49%,#101b25_49%_51%,#26394a_51%_97.5%,#111c27_97.5%)] shadow-[0_20px_45px_rgba(0,0,0,.38),0_0_40px_rgba(34,211,238,.05)]">
                      {[20,40,60,80].map((top, index) => <div key={top} className="absolute left-[3%] right-[3%] h-[2px] bg-gradient-to-r from-slate-500/10 via-cyan-200/35 to-slate-500/10" style={{ top: `${top}%` }}><span className="absolute -left-[9%] -top-2 text-[9px] text-slate-600">П{index + 1}</span></div>)}
                      <div className="absolute inset-[3%] bg-[repeating-linear-gradient(90deg,transparent_0_15.9%,rgba(255,255,255,.04)_16%_16.2%,transparent_16.3%_16.66%)]" />
                    </div>
                    {visibleSensors.map((sensor) => <SensorMarker key={sensor.id} sensor={sensor} selected={sensor.id === selectedId} onSelect={() => setSelectedId(sensor.id)} />)}
                    <div className="absolute bottom-3 left-3 flex gap-3 rounded-lg border border-white/[0.07] bg-slate-950/65 px-3 py-2 text-[9px] text-slate-500 backdrop-blur"><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-emerald-400" />Передній</span><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-blue-400" />Задній</span></div>
                  </div>
                </div>

                <div className="grid gap-3 md:grid-cols-4">
                  <Metric label="Середня температура" value={`${equipment.averageTemperatureC} °C`} icon={Thermometer} /><Metric label="Мінімальна" value={`${equipment.minTemperatureC} °C`} icon={Thermometer} /><Metric label="Максимальна" value={`${equipment.maxTemperatureC} °C`} icon={Thermometer} /><Metric label="Online датчики" value={`${equipment.onlineSensors}/${equipment.totalSensors}`} icon={Wifi} />
                </div>
              </section>

              <aside className="min-w-0 rounded-2xl border border-white/[0.08] bg-[#08182e]/90 p-3">
                <div className="mb-3 flex items-center justify-between"><div><h2 className="text-sm font-semibold text-white">Датчики в реальному часі</h2><p className="mt-1 text-[10px] text-slate-600">Показано {visibleSensors.length} із {equipment.totalSensors}</p></div><CircleDot className="h-4 w-4 text-emerald-400" /></div>
                {selected ? <div className="mb-3 rounded-xl border border-blue-400/20 bg-blue-500/[0.07] p-3"><p className="text-[9px] uppercase tracking-wider text-blue-300">Вибраний датчик</p><div className="mt-2 flex items-end justify-between"><div><p className="font-semibold text-white">{selected.label} · {selected.name}</p><p className="mt-1 text-[10px] text-slate-500">Полиця {selected.shelf} · позиція {selected.position}</p></div><p className="text-xl font-semibold text-white">{selected.temperatureC?.toFixed(1)} °C</p></div></div> : null}
                <div className="max-h-[660px] space-y-1.5 overflow-y-auto pr-1">
                  {visibleSensors.map((sensor) => <button key={sensor.id} onClick={() => setSelectedId(sensor.id)} className={clsx("flex w-full items-center gap-2 rounded-xl border p-2 text-left transition", sensor.id === selectedId ? "border-blue-400/30 bg-blue-500/10" : "border-white/[0.05] bg-white/[0.02] hover:bg-white/[0.04]")}><span className={clsx("grid h-7 min-w-7 place-items-center rounded-lg text-[9px] font-bold", sensor.side === "front" ? "bg-emerald-400/10 text-emerald-300" : "bg-blue-400/10 text-blue-300")}>{sensor.label}</span><span className="min-w-0 flex-1"><span className="block truncate text-[11px] text-slate-300">{sensor.name}</span><span className="text-[9px] text-slate-600">Полиця {sensor.shelf}</span></span><span className="text-xs font-semibold text-white">{sensor.temperatureC?.toFixed(1)}°</span><Sparkline values={sensor.trend} /></button>)}
                </div>
              </aside>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

function SensorMarker({ sensor, selected, onSelect }: { sensor: RefrigerationSensor; selected: boolean; onSelect: () => void }) {
  return <button onClick={onSelect} aria-label={`${sensor.label}, ${sensor.temperatureC} градусів Цельсія, ${sensor.name}`} className={clsx("absolute z-10 min-w-10 -translate-x-1/2 -translate-y-1/2 rounded-md border px-1.5 py-1 text-center text-[8px] font-bold leading-tight backdrop-blur-sm transition hover:z-20 hover:scale-110 focus:outline-none focus:ring-2 focus:ring-cyan-300", markerTone[sensor.status], selected && "z-20 scale-110 ring-2 ring-white/80")} style={{ left: `${sensor.x * 100}%`, top: `${sensor.y * 100}%` }}><span className="block">{sensor.label}</span><span className="block font-semibold">{sensor.temperatureC?.toFixed(1)}°</span></button>;
}
function Panel({ title, children }: { title: string; children: React.ReactNode }) { return <section className="rounded-2xl border border-white/[0.08] bg-[#08182e]/90 p-4"><h2 className="mb-3 text-xs font-semibold text-white">{title}</h2><div className="space-y-2.5">{children}</div></section>; }
function Info({ label, value }: { label: string; value: string }) { return <div><p className="text-[9px] uppercase tracking-wider text-slate-600">{label}</p><p className="mt-1 text-[11px] text-slate-300">{value}</p></div>; }
function State({ label, value }: { label: string; value: string }) { return <div className="flex items-center justify-between text-[11px]"><span className="text-slate-500">{label}</span><span className="text-emerald-300">{value}</span></div>; }
function Metric({ label, value, icon: Icon }: { label: string; value: string; icon: typeof Snowflake }) { return <div className="rounded-xl border border-white/[0.07] bg-[#091a31]/85 p-3"><Icon className="h-4 w-4 text-cyan-300" /><p className="mt-2 text-[9px] uppercase tracking-wider text-slate-600">{label}</p><p className="mt-1 text-sm font-semibold text-white">{value}</p></div>; }
function Sparkline({ values }: { values: number[] }) { const min = Math.min(...values); const max = Math.max(...values); const points = values.map((value, index) => `${(index / (values.length - 1)) * 46},${14 - ((value - min) / Math.max(0.1, max - min)) * 11}`).join(" "); return <svg width="46" height="16" viewBox="0 0 46 16" aria-hidden="true" className="text-cyan-400"><polyline fill="none" stroke="currentColor" strokeWidth="1.2" points={points} /></svg>; }
