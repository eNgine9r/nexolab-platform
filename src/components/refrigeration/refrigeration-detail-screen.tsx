"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { clsx } from "clsx";
import { AlertTriangle, ArrowLeft, FileText, RadioTower, SlidersHorizontal, X } from "lucide-react";

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
import type { AvailableSensor, SensorBinding } from "@/features/refrigeration/equipment-lifecycle-repository";
import { createRefrigerationEquipmentRuntime } from "@/features/refrigeration/equipment-repository-runtime";
import type { RefrigerationStructuralSnapshot } from "@/features/refrigeration/structural-snapshot-repository";
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

function buildBindingSensors(
  bindings: readonly SensorBinding[],
  channels: readonly AvailableSensor[],
): RefrigerationSensor[] {
  const latest = new Map(channels.map((sensor) => [sensor.channelId, sensor]));
  return bindings.map((binding) => {
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
  });
}

export function RefrigerationDetailScreen({
  equipment: initialEquipment,
  initialSnapshot,
}: {
  equipment: RefrigerationEquipment;
  initialSnapshot?: RefrigerationStructuralSnapshot | null;
}) {
  const runtime = useMemo(() => createRefrigerationEquipmentRuntime(), []);
  const [equipmentRecord, setEquipmentRecord] = useState(initialEquipment);
  const [bindings, setBindings] = useState<SensorBinding[]>(initialSnapshot?.bindings ?? []);
  const [channels, setChannels] = useState<AvailableSensor[]>(initialSnapshot?.channels ?? []);
  const [bindingSensors, setBindingSensors] = useState<RefrigerationSensor[] | null>(() =>
    initialSnapshot ? buildBindingSensors(initialSnapshot.bindings, initialSnapshot.channels) : null,
  );
  const [channelError, setChannelError] = useState<string | null>(null);
  const [chamberLabel, setChamberLabel] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [passportOpen, setPassportOpen] = useState(false);
  const [headerToolbarTarget, setHeaderToolbarTarget] = useState<HTMLDivElement | null>(null);
  const [side, setSide] = useState<"all" | SensorSide>("all");
  const [shelf, setShelf] = useState<number | "all">("all");
  const [selectedId, setSelectedId] = useState(initialEquipment.sensors[0]?.id ?? null);
  const [layoutMode, setLayoutMode] = useState<LayoutEditorMode>("view");
  const [canManageEquipment, setCanManageEquipment] = useState(runtime.mode === "demo");
  const [bindingEpoch, setBindingEpoch] = useState(0);

  useEffect(() => {
    setEquipmentRecord(initialSnapshot?.equipment ?? initialEquipment);
    if (initialSnapshot) {
      setBindings(initialSnapshot.bindings);
      setChannels(initialSnapshot.channels);
      setBindingSensors(buildBindingSensors(initialSnapshot.bindings, initialSnapshot.channels));
    }
  }, [initialEquipment, initialSnapshot]);

  useEffect(() => {
    if (!passportOpen) return;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPassportOpen(false);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [passportOpen]);

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
    const structural = runtime.structuralSnapshotRepository;
    const lifecycle = runtime.lifecycleRepository;
    const chamberId = equipmentRecord.climateChamberId;
    if (!structural && (!lifecycle || !chamberId)) {
      setBindingSensors((current) => current ?? (runtime.mode === "demo" ? null : []));
      setChannelError(
        runtime.mode === "live" && !chamberId ? "Для обладнання не вибрано кліматичну камеру." : null,
      );
      return;
    }
    let active = true;
    setChannelError(null);
    const request = structural
      ? structural.get(equipmentRecord.id).then((snapshot) => ({
          equipment: snapshot.equipment,
          bindings: snapshot.bindings,
          channels: snapshot.channels,
        }))
      : Promise.all([
          lifecycle!.listBindings(equipmentRecord.id),
          lifecycle!.listClimateChamberChannels(chamberId!),
        ]).then(([loadedBindings, availableChannels]) => ({
          equipment: null,
          bindings: loadedBindings,
          channels: availableChannels,
        }));
    void request
      .then((loaded) => {
        if (!active) return;
        if (loaded.equipment) setEquipmentRecord(loaded.equipment);
        setBindings(loaded.bindings);
        setChannels(loaded.channels);
        setBindingSensors(buildBindingSensors(loaded.bindings, loaded.channels));
      })
      .catch((cause) => {
        if (!active) return;
        setBindingSensors((current) => current ?? []);
        setChannelError(
          cause instanceof Error ? cause.message : "Не вдалося оновити структурний snapshot обладнання.",
        );
      });
    return () => {
      active = false;
    };
  }, [bindingEpoch, equipmentRecord.climateChamberId, equipmentRecord.id, runtime]);

  const equipment = useMemo(
    () => (bindingSensors === null ? equipmentRecord : { ...equipmentRecord, sensors: bindingSensors }),
    [bindingSensors, equipmentRecord],
  );
  const visibleSensors = useMemo(
    () =>
      equipment.sensors.filter(
        (sensor) => (side === "all" || sensor.side === side) && (shelf === "all" || sensor.shelf === shelf),
      ),
    [equipment.sensors, shelf, side],
  );
  const activeSelectedId = visibleSensors.some((sensor) => sensor.id === selectedId)
    ? selectedId
    : (visibleSensors[0]?.id ?? null);
  const retired = equipment.lifecycleStatus === "retired";
  const visibleChamberLabel =
    chamberLabel ?? (equipment.climateChamberId ? "Кліматична камера" : "Камеру не вибрано");

  const filterMenu = (
    <LayoutFilterMenu
      side={side}
      shelf={shelf}
      visibleCount={visibleSensors.length}
      totalCount={equipment.sensors.length}
      onSideChange={setSide}
      onShelfChange={setShelf}
    />
  );

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
            <header className="mb-2 flex flex-wrap items-center gap-3 rounded-2xl border border-white/[0.07] bg-[#091a31]/85 p-3">
              <Link
                href="/refrigeration"
                aria-label="Назад до обладнання"
                title="Назад"
                className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-white/10 bg-white/[0.035] text-slate-400 hover:text-white"
              >
                <ArrowLeft className="h-4 w-4" />
              </Link>

              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <h1 className="truncate text-base font-semibold text-white sm:text-lg">{equipment.name}</h1>
                  <span
                    className={clsx(
                      "rounded-full border px-2 py-0.5 text-[9px]",
                      equipmentStatusTone[equipment.status],
                    )}
                  >
                    {equipmentStatusLabel[equipment.status]}
                  </span>
                  {equipment.climateChamberId ? (
                    <span className="inline-flex max-w-full items-center gap-1 rounded-full border border-cyan-400/20 bg-cyan-500/10 px-2 py-0.5 text-[9px] text-cyan-200">
                      <RadioTower className="h-3 w-3 shrink-0" />
                      <span className="truncate">{visibleChamberLabel}</span>
                    </span>
                  ) : null}
                </div>
              </div>

              <div
                className="ml-auto flex shrink-0 items-center gap-1.5"
                aria-label="Дії сторінки обладнання"
              >
                <div ref={setHeaderToolbarTarget} className="flex w-[132px] shrink-0 items-center gap-1.5" />
                <button
                  type="button"
                  aria-label="Відкрити паспорт обладнання"
                  title="Паспорт обладнання"
                  onClick={() => setPassportOpen(true)}
                  className="relative grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-cyan-300/15 bg-cyan-400/[0.06] text-cyan-200 transition hover:border-cyan-300/30 hover:bg-cyan-400/10"
                >
                  <FileText className="h-4 w-4" />
                  <span
                    aria-hidden="true"
                    className={clsx(
                      "absolute right-1.5 bottom-1.5 h-2 w-2 rounded-full border border-[#091a31]",
                      equipment.lifecycleStatus === "active"
                        ? "bg-emerald-400"
                        : equipment.lifecycleStatus === "maintenance"
                          ? "bg-amber-400"
                          : "bg-slate-400",
                    )}
                  />
                </button>
              </div>
            </header>

            {retired ? (
              <div className="mb-2 flex items-center gap-2 rounded-xl border border-slate-400/15 bg-slate-400/[0.06] px-3 py-2 text-[10px] text-slate-300">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                Лише перегляд: обладнання виведено з експлуатації.
              </div>
            ) : null}

            {channelError ? (
              <div
                role="alert"
                className="mb-2 flex items-center gap-2 rounded-xl border border-rose-400/20 bg-rose-400/[0.07] px-3 py-2 text-[10px] text-rose-200"
              >
                <AlertTriangle className="h-4 w-4 shrink-0" />
                {channelError}
              </div>
            ) : null}

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
              toolbarTools={filterMenu}
              toolbarTarget={headerToolbarTarget}
            />
          </div>
        </main>
      </div>

      {passportOpen ? (
        <div
          className="fixed inset-0 z-[90] flex justify-end bg-[#020817]/75 backdrop-blur-sm"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setPassportOpen(false);
          }}
        >
          <aside
            role="dialog"
            aria-modal="true"
            aria-labelledby="equipment-passport-title"
            className="flex h-full w-full max-w-3xl flex-col border-l border-cyan-300/15 bg-[#07182f] shadow-2xl shadow-black/50"
          >
            <header className="flex items-center gap-3 border-b border-white/[0.07] px-4 py-3">
              <div className="grid h-9 w-9 place-items-center rounded-xl border border-cyan-300/15 bg-cyan-400/[0.06] text-cyan-200">
                <FileText className="h-4 w-4" />
              </div>
              <div className="min-w-0 flex-1">
                <h2 id="equipment-passport-title" className="truncate text-sm font-semibold text-white">
                  Паспорт обладнання
                </h2>
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  <span
                    className={clsx(
                      "rounded-full border px-2 py-0.5 text-[8px]",
                      lifecycleTone[equipment.lifecycleStatus],
                    )}
                  >
                    {lifecycleLabel[equipment.lifecycleStatus]}
                  </span>
                  <span className="text-[9px] text-slate-500">v{equipment.version}</span>
                </div>
              </div>
              <button
                type="button"
                aria-label="Закрити паспорт обладнання"
                onClick={() => setPassportOpen(false)}
                className="grid h-9 w-9 place-items-center rounded-xl border border-white/[0.08] text-slate-400 hover:border-cyan-300/20 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto p-3 sm:p-4">
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
          </aside>
        </div>
      ) : null}
    </div>
  );
}

function LayoutFilterMenu({
  side,
  shelf,
  visibleCount,
  totalCount,
  onSideChange,
  onShelfChange,
}: {
  side: "all" | SensorSide;
  shelf: number | "all";
  visibleCount: number;
  totalCount: number;
  onSideChange: (value: "all" | SensorSide) => void;
  onShelfChange: (value: number | "all") => void;
}) {
  return (
    <details className="group relative">
      <summary
        aria-label="Фільтри розміщення датчиків"
        title="Фільтри датчиків"
        className="grid h-10 w-10 shrink-0 cursor-pointer list-none place-items-center rounded-xl border border-white/[0.08] bg-white/[0.035] text-slate-400 transition hover:border-cyan-300/20 hover:text-cyan-100 [&::-webkit-details-marker]:hidden"
      >
        <SlidersHorizontal className="h-4 w-4" />
      </summary>
      <div className="absolute top-12 right-0 z-[70] w-[min(92vw,420px)] rounded-2xl border border-cyan-300/15 bg-[#07182f]/98 p-3 shadow-2xl shadow-black/45 backdrop-blur-xl">
        <div className="mb-3 flex items-center justify-between gap-3">
          <span className="text-[10px] font-semibold text-white">Відображення датчиків</span>
          <span className="rounded-full border border-white/[0.07] px-2 py-0.5 text-[8px] text-slate-400">
            {visibleCount}/{totalCount}
          </span>
        </div>

        <FilterGroup label="Фронт">
          {sideOptions.map((option) => (
            <FilterButton
              key={option.value}
              active={side === option.value}
              onClick={() => onSideChange(option.value)}
            >
              {option.label}
            </FilterButton>
          ))}
        </FilterGroup>

        <FilterGroup label="Полиця">
          <FilterButton active={shelf === "all"} onClick={() => onShelfChange("all")}>
            Усі
          </FilterButton>
          {shelves.map((item) => (
            <FilterButton key={item} active={shelf === item} onClick={() => onShelfChange(item)}>
              {item}
            </FilterButton>
          ))}
        </FilterGroup>
      </div>
    </details>
  );
}

function FilterGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mt-2 first:mt-0">
      <p className="mb-1.5 text-[8px] tracking-[0.14em] text-slate-500 uppercase">{label}</p>
      <div className="flex flex-wrap gap-1.5">{children}</div>
    </div>
  );
}

function FilterButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={clsx(
        "rounded-lg border px-2.5 py-1.5 text-[9px] transition",
        active
          ? "border-cyan-300/25 bg-cyan-400/15 text-cyan-100"
          : "border-white/[0.07] bg-white/[0.02] text-slate-500 hover:text-slate-200",
      )}
    >
      {children}
    </button>
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
