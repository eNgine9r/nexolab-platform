"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { clsx } from "clsx";
import { ArrowLeft, AlertTriangle, ChevronDown, RadioTower } from "lucide-react";

import { Sidebar } from "@/components/dashboard/sidebar";
import { Topbar } from "@/components/dashboard/topbar";
import { EquipmentLifecyclePanel } from "@/components/refrigeration/equipment-lifecycle-panel";
import type { LayoutEditorMode } from "@/components/refrigeration/refrigeration-layout-editor";
import { SecurityAwareRefrigerationLayoutWorkspace } from "@/components/refrigeration/security-aware-layout-workspace";
import type {
  EquipmentLifecycleStatus,
  EquipmentStatus,
  RefrigerationEquipment,
  RefrigerationSensor,
  SensorSide,
  SensorStatus,
} from "@/data/refrigeration";
import type {
  AvailableSensor,
  SensorBinding,
} from "@/features/refrigeration/equipment-lifecycle-repository";
import { createRefrigerationEquipmentRuntime } from "@/features/refrigeration/equipment-repository-runtime";
import { hasPermission } from "@/features/security/security-session";

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

const lifecycleLabel: Record<EquipmentLifecycleStatus, string> = {
  active: "Активне",
  maintenance: "Обслуговування",
  retired: "Виведене з експлуатації",
};

const lifecycleTone: Record<EquipmentLifecycleStatus, string> = {
  active: "border-emerald-400/20 bg-emerald-400/10 text-emerald-200",
  maintenance: "border-amber-400/20 bg-amber-400/10 text-amber-200",
  retired: "border-slate-400/20 bg-slate-400/10 text-slate-300",
};

const sideOptions: ReadonlyArray<{ value: "all" | SensorSide; label: string }> = [
  { value: "all", label: "Усі" },
  { value: "front", label: "Передній фронт" },
  { value: "rear", label: "Задній фронт" },
];
const shelves = [1, 2, 3, 4] as const;

export function RefrigerationDetailScreen({
  equipment: initialEquipment,
}: {
  equipment: RefrigerationEquipment;
}) {
  const runtime = useMemo(() => createRefrigerationEquipmentRuntime(), []);
  const [equipmentRecord, setEquipmentRecord] = useState(initialEquipment);
  const [bindings, setBindings] = useState<SensorBinding[]>([]);
  const [channels, setChannels] = useState<AvailableSensor[]>([]);
  const [bindingSensors, setBindingSensors] = useState<RefrigerationSensor[] | null>(null);
  const [channelError, setChannelError] = useState<string | null>(null);
  const [chamberLabel, setChamberLabel] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [side, setSide] = useState<"all" | SensorSide>("all");
  const [shelf, setShelf] = useState<number | "all">("all");
  const [selectedId, setSelectedId] = useState(initialEquipment.sensors[0]?.id ?? null);
  const [layoutMode, setLayoutMode] = useState<LayoutEditorMode>("view");
  const [canManageEquipment, setCanManageEquipment] = useState(runtime.mode === "demo");
  const [bindingEpoch, setBindingEpoch] = useState(0);

  useEffect(() => {
    setEquipmentRecord(initialEquipment);
    setBindingSensors(null);
    setBindings([]);
    setChannels([]);
  }, [initialEquipment]);

  useEffect(() => {
    const catalog = runtime.climateCatalogRepository;
    const chamberId = equipmentRecord.climateChamberId;
    if (!catalog || !chamberId) {
      setChamberLabel(chamberId ? null : "Камеру не вибрано");
      return;
    }
    let active = true;
    setChamberLabel(null);
    void catalog
      .listChambers()
      .then((items) => {
        if (!active) return;
        const chamber = items.find((item) => item.id === chamberId);
        setChamberLabel(chamber ? `${chamber.name} · ${chamber.code}` : "Кліматична камера");
      })
      .catch(() => {
        if (active) setChamberLabel("Кліматична камера");
      });
    return () => {
      active = false;
    };
  }, [equipmentRecord.climateChamberId, runtime]);

  useEffect(() => {
    if (runtime.mode === "demo") {
      setCanManageEquipment(true);
      return;
    }
    const client = runtime.sessionClient;
    if (!client) {
      setCanManageEquipment(false);
      return;
    }
    let active = true;
    void client.getSession().then((result) => {
      if (!active || !result.ok) return;
      const membership =
        result.value.memberships.find((item) => item.organizationId === runtime.organizationId) ??
        result.value.memberships[0];
      setCanManageEquipment(
        membership ? hasPermission(result.value, membership.organizationId, "equipment.manage") : false,
      );
    });
    return () => {
      active = false;
    };
  }, [runtime]);

  useEffect(() => {
    const lifecycle = runtime.lifecycleRepository;
    const chamberId = equipmentRecord.climateChamberId;
    if (!lifecycle || !chamberId) {
      setBindingSensors(runtime.mode === "demo" ? null : []);
      setBindings([]);
      setChannels([]);
      setChannelError(
        runtime.mode === "live" && !chamberId
          ? "Для обладнання не вибрано кліматичну камеру. Відредагуйте паспорт перед роботою з датчиками."
          : null,
      );
      return;
    }
    let active = true;
    setChannelError(null);
    void Promise.all([
      lifecycle.listBindings(equipmentRecord.id),
      lifecycle.listClimateChamberChannels(chamberId),
    ])
      .then(([loadedBindings, availableChannels]) => {
        if (!active) return;
        const latest = new Map(availableChannels.map((sensor) => [sensor.channelId, sensor]));
        setBindings(loadedBindings);
        setChannels(availableChannels);
        setBindingSensors(
          loadedBindings.map((binding) => {
            const telemetry = latest.get(binding.channelId);
            const [x, y] = defaultCoordinates(binding.side, binding.shelf, binding.position);
            return {
              id: binding.channelId,
              label: binding.label,
              name: `${telemetry?.metric ?? "Канал"} · ${binding.channelId}`,
              side: binding.side,
              shelf: binding.shelf,
              position: binding.position,
              x,
              y,
              temperatureC: telemetry?.latestValue ?? null,
              status: sensorStatus(telemetry?.quality),
              updatedAt: telemetry?.capturedAt ?? binding.boundAt,
              trend:
                telemetry?.latestValue === null || telemetry?.latestValue === undefined
                  ? []
                  : [telemetry.latestValue],
            };
          }),
        );
      })
      .catch((cause) => {
        if (!active) return;
        setBindings([]);
        setChannels([]);
        setBindingSensors([]);
        setChannelError(
          cause instanceof Error
            ? cause.message
            : "Не вдалося завантажити датчики вибраної кліматичної камери.",
        );
      });
    return () => {
      active = false;
    };
  }, [
    bindingEpoch,
    equipmentRecord.climateChamberId,
    equipmentRecord.id,
    equipmentRecord.version,
    runtime,
  ]);

  const equipment = useMemo(
    () => (bindingSensors === null ? equipmentRecord : { ...equipmentRecord, sensors: bindingSensors }),
    [bindingSensors, equipmentRecord],
  );
  const visibleSensors = useMemo(
    () =>
      equipment.sensors.filter(
        (sensor) =>
          (side === "all" || sensor.side === side) && (shelf === "all" || sensor.shelf === shelf),
      ),
    [equipment.sensors, shelf, side],
  );
  const activeSelectedId = visibleSensors.some((sensor) => sensor.id === selectedId)
    ? selectedId
    : (visibleSensors[0]?.id ?? null);
  const retired = equipment.lifecycleStatus === "retired";
  const visibleChamberLabel =
    chamberLabel ?? (equipment.climateChamberId ? "Кліматична камера" : "Камеру не вибрано");

  return (
    <div className="min-h-screen bg-[#06142a] text-slate-100">
      <Sidebar
        open={sidebarOpen}
        activeItem="Холодильне обладнання"
        onClose={() => setSidebarOpen(false)}
        onSelect={() => undefined}
      />
      <div className="min-h-screen lg:pl-[264px]">
        <Topbar title={equipment.name} onMenuOpen={() => setSidebarOpen(true)} />
        <main className="p-3 sm:p-4 xl:p-5">
          <div className="mx-auto max-w-[2100px]">
            <header className="mb-3 rounded-2xl border border-white/[0.07] bg-[#091a31]/85 p-4">
              <div className="flex items-start gap-3">
                <Link
                  href="/refrigeration"
                  aria-label="Назад до обладнання"
                  title="Назад"
                  className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-white/10 bg-white/[0.035] text-slate-400 hover:text-white"
                >
                  <ArrowLeft className="h-4 w-4" />
                </Link>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h1 className="truncate text-xl font-semibold text-white">{equipment.name}</h1>
                    <span
                      className={clsx(
                        "rounded-full border px-2.5 py-1 text-[10px]",
                        equipmentStatusTone[equipment.status],
                      )}
                    >
                      {equipmentStatusLabel[equipment.status]}
                    </span>
                    {equipment.climateChamberId ? (
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-cyan-400/20 bg-cyan-500/10 px-2.5 py-1 text-[10px] text-cyan-200">
                        <RadioTower className="h-3 w-3" />
                        {visibleChamberLabel}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 truncate text-xs text-slate-500">
                    {equipment.location} · {equipment.model} · {equipment.serialNumber}
                  </p>
                </div>
              </div>
            </header>

            <details className="group mb-3">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-2xl border border-white/[0.07] bg-[#08182e]/90 px-4 py-3 transition hover:border-cyan-300/15 [&::-webkit-details-marker]:hidden">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-semibold text-white">
                      Паспорт, lifecycle, фото та bindings
                    </span>
                    <span
                      className={`rounded-full border px-2 py-1 text-[9px] ${lifecycleTone[equipment.lifecycleStatus]}`}
                    >
                      {lifecycleLabel[equipment.lifecycleStatus]}
                    </span>
                  </div>
                  <p className="mt-1 truncate text-[10px] text-slate-500">
                    Паспорт v{equipment.version} · {equipment.laboratory ?? "Лабораторію не задано"}
                    {equipment.zone ? ` · ${equipment.zone}` : ""} · {visibleChamberLabel}
                  </p>
                </div>
                <ChevronDown className="h-4 w-4 shrink-0 text-slate-500 transition-transform group-open:rotate-180" />
              </summary>
              <div className="pt-3">
                <EquipmentLifecyclePanel
                  equipment={equipment}
                  repository={runtime.equipmentRepository}
                  lifecycleRepository={runtime.lifecycleRepository}
                  climateCatalogRepository={runtime.climateCatalogRepository}
                  canManage={canManageEquipment}
                  onEquipmentChange={setEquipmentRecord}
                  onBindingsChanged={() => setBindingEpoch((current) => current + 1)}
                />
              </div>
            </details>

            {retired ? (
              <div className="mb-3 flex items-start gap-2 rounded-2xl border border-slate-400/15 bg-slate-400/[0.06] p-3 text-xs text-slate-300">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                Обладнання виведено з експлуатації. Схема, фото, історія та sensor bindings
                залишаються доступними лише для перегляду й аудиту.
              </div>
            ) : null}

            {channelError ? (
              <div
                role="alert"
                className="mb-3 flex items-start gap-2 rounded-2xl border border-rose-400/20 bg-rose-400/[0.07] p-3 text-xs text-rose-200"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                {channelError}
              </div>
            ) : null}

            <section className="mb-3 flex flex-col gap-2 rounded-2xl border border-white/[0.07] bg-[#08182e]/90 p-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex flex-wrap gap-2">
                {sideOptions.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setSide(option.value)}
                    aria-pressed={side === option.value}
                    className={clsx(
                      "rounded-xl border px-3 py-2 text-[11px] transition",
                      side === option.value
                        ? "border-cyan-300/25 bg-cyan-400/15 text-cyan-100"
                        : "border-white/10 bg-white/[0.025] text-slate-500 hover:text-slate-200",
                    )}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setShelf("all")}
                  aria-pressed={shelf === "all"}
                  className={clsx(
                    "rounded-xl border px-3 py-2 text-[11px] transition",
                    shelf === "all"
                      ? "border-cyan-300/25 bg-cyan-400/15 text-cyan-100"
                      : "border-white/10 bg-white/[0.025] text-slate-500 hover:text-slate-200",
                  )}
                >
                  Усі полиці
                </button>
                {shelves.map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => setShelf(item)}
                    aria-pressed={shelf === item}
                    className={clsx(
                      "rounded-xl border px-3 py-2 text-[11px] transition",
                      shelf === item
                        ? "border-cyan-300/25 bg-cyan-400/15 text-cyan-100"
                        : "border-white/10 bg-white/[0.025] text-slate-500 hover:text-slate-200",
                    )}
                  >
                    Полиця {item}
                  </button>
                ))}
              </div>
            </section>

            <SecurityAwareRefrigerationLayoutWorkspace
              equipment={equipment}
              visibleSensors={visibleSensors}
              selectedId={activeSelectedId}
              mode={layoutMode}
              onModeChange={setLayoutMode}
              onSelect={setSelectedId}
              bindings={bindings}
              availableSensors={channels}
              sensorConfigurationRepository={runtime.sensorConfigurationRepository}
              onEquipmentChange={setEquipmentRecord}
              onConfigurationSaved={() => setBindingEpoch((current) => current + 1)}
              forceReadOnly={retired}
            />
          </div>
        </main>
      </div>
    </div>
  );
}

function defaultCoordinates(side: SensorSide, shelf: number, position: number): [number, number] {
  const x = 0.17 + (position - 1) * 0.13 + (side === "rear" ? 0.032 : -0.032);
  const y = 0.21 + (shelf - 1) * 0.205 + (side === "rear" ? 0.055 : 0);
  return [Math.min(0.94, Math.max(0.06, x)), Math.min(0.91, Math.max(0.08, y))];
}

function sensorStatus(quality: string | undefined): SensorStatus {
  if (quality === "good") return "normal";
  if (quality === "warning" || quality === "stale") return "warning";
  if (quality === "alarm" || quality === "critical") return "alarm";
  return "no-data";
}
