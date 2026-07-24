"use client";

import Image from "next/image";
import Link from "next/link";
import { useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { clsx } from "clsx";
import { ArrowLeft, Edit3, Grid3X3, ImagePlus, RotateCcw, Save, X } from "lucide-react";

import { Sidebar } from "@/components/dashboard/sidebar";
import { Topbar } from "@/components/dashboard/topbar";
import type { RefrigerationEquipment, RefrigerationSensor, SensorSide } from "@/data/refrigeration";
import { getEquipmentImage } from "@/features/refrigeration/equipment-images";
import {
  cloneSensors,
  KEYBOARD_COARSE_STEP,
  KEYBOARD_FINE_STEP,
  moveSensor,
  moveSensorByDelta,
  normalizedPointFromClient,
  placementsChanged,
} from "@/features/refrigeration/layout-editor";

const markerTone = {
  normal: "border-emerald-300/80 bg-emerald-500/25 text-emerald-50",
  warning: "border-amber-300/90 bg-amber-500/30 text-amber-50",
  alarm: "border-rose-300/90 bg-rose-500/35 text-rose-50",
  "no-data": "border-slate-300/60 bg-slate-600/50 text-slate-100",
};

const sideOptions: ReadonlyArray<{
  value: "all" | SensorSide;
  label: string;
}> = [
  { value: "all", label: "Усі" },
  { value: "front", label: "Передній" },
  { value: "rear", label: "Задній" },
];

export function RefrigerationLayoutEditorScreen({ equipment }: { equipment: RefrigerationEquipment }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [snapToGrid, setSnapToGrid] = useState(true);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [side, setSide] = useState<"all" | SensorSide>("all");
  const [shelf, setShelf] = useState<number | "all">("all");
  const [selectedId, setSelectedId] = useState(equipment.sensors[0]?.id ?? null);
  const [committedSensors, setCommittedSensors] = useState(() => cloneSensors(equipment.sensors));
  const [draftSensors, setDraftSensors] = useState(() => cloneSensors(equipment.sensors));
  const stageRef = useRef<HTMLDivElement>(null);
  const image = getEquipmentImage(equipment.id);

  const sensors = editing ? draftSensors : committedSensors;
  const dirty = editing && placementsChanged(committedSensors, draftSensors);
  const visibleSensors = useMemo(
    () =>
      sensors.filter(
        (sensor) => (side === "all" || sensor.side === side) && (shelf === "all" || sensor.shelf === shelf),
      ),
    [sensors, shelf, side],
  );
  const activeSelectedId = visibleSensors.some((sensor) => sensor.id === selectedId)
    ? selectedId
    : (visibleSensors[0]?.id ?? null);
  const selectedSensor = sensors.find((sensor) => sensor.id === activeSelectedId) ?? null;

  function beginEditing() {
    setDraftSensors(cloneSensors(committedSensors));
    setConfirmDiscard(false);
    setEditing(true);
  }

  function saveLocalDraft() {
    setCommittedSensors(cloneSensors(draftSensors));
    setConfirmDiscard(false);
    setEditing(false);
  }

  function requestExitEditing() {
    if (dirty) {
      setConfirmDiscard(true);
      return;
    }

    setEditing(false);
  }

  function discardDraft() {
    setDraftSensors(cloneSensors(committedSensors));
    setConfirmDiscard(false);
    setEditing(false);
  }

  function resetDraft() {
    setDraftSensors(cloneSensors(committedSensors));
    setConfirmDiscard(false);
  }

  function updateFromPointer(event: PointerEvent<HTMLButtonElement>, sensorId: string) {
    if (!editing || !stageRef.current) {
      return;
    }

    const point = normalizedPointFromClient(
      event.clientX,
      event.clientY,
      stageRef.current.getBoundingClientRect(),
    );
    setDraftSensors((current) => moveSensor(current, sensorId, point, { snapToGrid }));
  }

  function handlePointerDown(event: PointerEvent<HTMLButtonElement>, sensorId: string) {
    if (!editing) {
      return;
    }

    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    setSelectedId(sensorId);
    updateFromPointer(event, sensorId);
  }

  function handlePointerMove(event: PointerEvent<HTMLButtonElement>, sensorId: string) {
    if (!event.currentTarget.hasPointerCapture(event.pointerId)) {
      return;
    }

    updateFromPointer(event, sensorId);
  }

  function handlePointerEnd(event: PointerEvent<HTMLButtonElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function handleMarkerKeyDown(event: KeyboardEvent<HTMLButtonElement>, sensorId: string) {
    if (!editing || !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
      return;
    }

    event.preventDefault();
    const step = event.shiftKey ? KEYBOARD_COARSE_STEP : KEYBOARD_FINE_STEP;
    const delta = {
      x: event.key === "ArrowLeft" ? -step : event.key === "ArrowRight" ? step : 0,
      y: event.key === "ArrowUp" ? -step : event.key === "ArrowDown" ? step : 0,
    };

    setDraftSensors((current) => moveSensorByDelta(current, sensorId, delta, { snapToGrid }));
  }

  return (
    <div className="min-h-screen bg-[#06142a] text-slate-100">
      <Sidebar
        open={sidebarOpen}
        activeItem="Холодильне обладнання"
        onClose={() => setSidebarOpen(false)}
        onSelect={() => undefined}
      />
      <div className="min-h-screen lg:pl-[264px]">
        <Topbar title={`${equipment.name} · схема`} onMenuOpen={() => setSidebarOpen(true)} />
        <main className="p-3 sm:p-4 xl:p-5">
          <div className="mx-auto max-w-[1900px]">
            <header className="mb-3 flex flex-col gap-4 rounded-2xl border border-white/[0.08] bg-[#091a31]/90 p-4 xl:flex-row xl:items-center xl:justify-between">
              <div className="flex items-start gap-3">
                <Link
                  href={`/refrigeration/${equipment.id}`}
                  aria-label="Повернутися до огляду обладнання"
                  className="grid h-9 w-9 place-items-center rounded-xl border border-white/10 bg-white/[0.035] text-slate-400 transition hover:text-white"
                >
                  <ArrowLeft className="h-4 w-4" />
                </Link>
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h1 className="text-lg font-semibold text-white">Схема розміщення датчиків</h1>
                    <StatusBadge editing={editing} />
                    {dirty ? (
                      <span className="rounded-full border border-amber-400/25 bg-amber-400/10 px-2.5 py-1 text-[10px] text-amber-200">
                        Незбережені зміни
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    {equipment.name} · {equipment.code} · координати 0..1
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  title="Backend-завантаження фото буде додано наступним Gate"
                  className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.035] px-3 py-2 text-xs text-slate-300"
                >
                  <ImagePlus className="h-3.5 w-3.5" />
                  Замінити фото
                </button>
                {editing ? (
                  <EditActions
                    dirty={dirty}
                    onReset={resetDraft}
                    onExit={requestExitEditing}
                    onSave={saveLocalDraft}
                  />
                ) : (
                  <button
                    type="button"
                    onClick={beginEditing}
                    className="inline-flex items-center gap-2 rounded-xl border border-blue-400/30 bg-blue-500/15 px-3 py-2 text-xs font-medium text-blue-100"
                  >
                    <Edit3 className="h-3.5 w-3.5" />
                    Редагувати
                  </button>
                )}
              </div>
            </header>

            {confirmDiscard ? (
              <DiscardPrompt onContinue={() => setConfirmDiscard(false)} onDiscard={discardDraft} />
            ) : null}

            <div className="grid gap-3 2xl:grid-cols-[minmax(0,1fr)_360px]">
              <section className="min-w-0 rounded-2xl border border-white/[0.08] bg-[#08182e]/90 p-3">
                <div className="mb-3 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <h2 className="text-sm font-semibold text-white">Фото та маркери</h2>
                    <p className="mt-1 text-[11px] text-slate-500">
                      {visibleSensors.length} із {sensors.length} датчиків
                    </p>
                  </div>
                  <LayoutFilters
                    side={side}
                    shelf={shelf}
                    editing={editing}
                    snapToGrid={snapToGrid}
                    onSideChange={setSide}
                    onShelfChange={setShelf}
                    onSnapChange={() => setSnapToGrid((current) => !current)}
                  />
                </div>

                <div
                  ref={stageRef}
                  data-testid="equipment-layout-stage"
                  className={clsx(
                    "relative aspect-[16/10] overflow-hidden rounded-xl border bg-[#02070f]",
                    editing ? "border-blue-400/25" : "border-cyan-300/[0.1]",
                  )}
                >
                  <Image
                    src={image.src}
                    alt={image.alt}
                    fill
                    priority
                    sizes="(min-width: 1536px) 70vw, 100vw"
                    className="pointer-events-none object-contain select-none"
                  />
                  {editing && snapToGrid ? (
                    <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(34,211,238,.08)_1px,transparent_1px),linear-gradient(90deg,rgba(34,211,238,.08)_1px,transparent_1px)] bg-[size:2.5%_2.5%]" />
                  ) : null}

                  {visibleSensors.map((sensor) => (
                    <SensorMarker
                      key={sensor.id}
                      sensor={sensor}
                      editing={editing}
                      selected={sensor.id === activeSelectedId}
                      onSelect={() => setSelectedId(sensor.id)}
                      onPointerDown={(event) => handlePointerDown(event, sensor.id)}
                      onPointerMove={(event) => handlePointerMove(event, sensor.id)}
                      onPointerEnd={handlePointerEnd}
                      onKeyDown={(event) => handleMarkerKeyDown(event, sensor.id)}
                    />
                  ))}
                </div>
              </section>

              <aside className="space-y-3">
                <Inspector sensor={selectedSensor} />
                <DraftStatus
                  editing={editing}
                  dirty={dirty}
                  snapToGrid={snapToGrid}
                  sensorCount={sensors.length}
                />
              </aside>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

function StatusBadge({ editing }: { editing: boolean }) {
  return (
    <span
      className={clsx(
        "rounded-full border px-2.5 py-1 text-[10px]",
        editing
          ? "border-blue-400/30 bg-blue-500/15 text-blue-200"
          : "border-emerald-400/20 bg-emerald-400/10 text-emerald-300",
      )}
    >
      {editing ? "Режим редагування" : "Режим перегляду"}
    </span>
  );
}

function EditActions({
  dirty,
  onReset,
  onExit,
  onSave,
}: {
  dirty: boolean;
  onReset: () => void;
  onExit: () => void;
  onSave: () => void;
}) {
  return (
    <>
      <button
        type="button"
        onClick={onReset}
        disabled={!dirty}
        className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.035] px-3 py-2 text-xs text-slate-300 disabled:cursor-not-allowed disabled:opacity-40"
      >
        <RotateCcw className="h-3.5 w-3.5" />
        Скинути
      </button>
      <button
        type="button"
        onClick={onExit}
        className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.035] px-3 py-2 text-xs text-slate-300"
      >
        <X className="h-3.5 w-3.5" />
        Вийти
      </button>
      <button
        type="button"
        onClick={onSave}
        disabled={!dirty}
        className="inline-flex items-center gap-2 rounded-xl border border-blue-400/30 bg-blue-500/15 px-3 py-2 text-xs font-medium text-blue-100 disabled:cursor-not-allowed disabled:opacity-40"
      >
        <Save className="h-3.5 w-3.5" />
        Зберегти локально
      </button>
    </>
  );
}

function DiscardPrompt({ onContinue, onDiscard }: { onContinue: () => void; onDiscard: () => void }) {
  return (
    <section className="mb-3 flex flex-col gap-3 rounded-2xl border border-amber-400/20 bg-amber-400/[0.07] p-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h2 className="text-sm font-semibold text-amber-100">Відкинути незбережені зміни?</h2>
        <p className="mt-1 text-xs text-amber-100/60">
          Позиції буде повернуто до останньої локально збереженої версії.
        </p>
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onContinue}
          className="rounded-lg border border-white/10 px-3 py-2 text-xs text-slate-200"
        >
          Продовжити редагування
        </button>
        <button
          type="button"
          onClick={onDiscard}
          className="rounded-lg border border-amber-300/25 bg-amber-400/15 px-3 py-2 text-xs font-medium text-amber-100"
        >
          Відкинути
        </button>
      </div>
    </section>
  );
}

function LayoutFilters({
  side,
  shelf,
  editing,
  snapToGrid,
  onSideChange,
  onShelfChange,
  onSnapChange,
}: {
  side: "all" | SensorSide;
  shelf: number | "all";
  editing: boolean;
  snapToGrid: boolean;
  onSideChange: (value: "all" | SensorSide) => void;
  onShelfChange: (value: number | "all") => void;
  onSnapChange: () => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {sideOptions.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={side === option.value}
          onClick={() => onSideChange(option.value)}
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
      <label className="sr-only" htmlFor="layout-shelf-filter">
        Фільтр за полицею
      </label>
      <select
        id="layout-shelf-filter"
        value={shelf}
        onChange={(event) => onShelfChange(event.target.value === "all" ? "all" : Number(event.target.value))}
        className="rounded-lg border border-white/[0.07] bg-[#0b1e38] px-2.5 py-1.5 text-[10px] text-slate-400 outline-none"
      >
        <option value="all">Усі полиці</option>
        {[1, 2, 3, 4].map((value) => (
          <option key={value} value={value}>
            Полиця {value}
          </option>
        ))}
      </select>
      <button
        type="button"
        aria-pressed={snapToGrid}
        disabled={!editing}
        onClick={onSnapChange}
        className={clsx(
          "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[10px] disabled:cursor-not-allowed disabled:opacity-40",
          snapToGrid
            ? "border-cyan-400/30 bg-cyan-400/10 text-cyan-200"
            : "border-white/[0.07] bg-white/[0.025] text-slate-500",
        )}
      >
        <Grid3X3 className="h-3.5 w-3.5" />
        Прив’язка
      </button>
    </div>
  );
}

function SensorMarker({
  sensor,
  editing,
  selected,
  onSelect,
  onPointerDown,
  onPointerMove,
  onPointerEnd,
  onKeyDown,
}: {
  sensor: RefrigerationSensor;
  editing: boolean;
  selected: boolean;
  onSelect: () => void;
  onPointerDown: (event: PointerEvent<HTMLButtonElement>) => void;
  onPointerMove: (event: PointerEvent<HTMLButtonElement>) => void;
  onPointerEnd: (event: PointerEvent<HTMLButtonElement>) => void;
  onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void;
}) {
  return (
    <button
      type="button"
      aria-label={`${editing ? "Перемістити" : "Вибрати"} датчик ${sensor.label}`}
      aria-pressed={selected}
      onClick={onSelect}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerEnd}
      onPointerCancel={onPointerEnd}
      onKeyDown={onKeyDown}
      className={clsx(
        "absolute z-10 min-w-11 -translate-x-1/2 -translate-y-1/2 touch-none rounded-lg border px-1.5 py-1 text-center text-[9px] leading-tight font-bold shadow-lg backdrop-blur-sm transition focus:ring-2 focus:ring-cyan-300 focus:outline-none",
        markerTone[sensor.status],
        selected && "z-20 scale-110 ring-2 ring-white/80",
        editing ? "cursor-move hover:scale-110" : "cursor-pointer",
      )}
      style={{ left: `${sensor.x * 100}%`, top: `${sensor.y * 100}%` }}
    >
      <span className="block">{sensor.label}</span>
      <span className="block font-medium">
        {sensor.temperatureC === null ? "—" : `${sensor.temperatureC.toFixed(1)}°`}
      </span>
    </button>
  );
}

function Inspector({ sensor }: { sensor: RefrigerationSensor | null }) {
  return (
    <section className="rounded-2xl border border-white/[0.08] bg-[#08182e]/90 p-4">
      <h2 className="text-xs font-semibold text-white">Вибраний датчик</h2>
      {sensor ? (
        <div className="mt-3 space-y-2 text-[11px]">
          <p className="rounded-xl border border-blue-400/20 bg-blue-500/[0.07] p-3 text-base font-semibold text-white">
            {sensor.label}
          </p>
          <InfoRow label="Полиця" value={String(sensor.shelf)} />
          <InfoRow label="Позиція" value={String(sensor.position)} />
          <InfoRow label="Фронт" value={sensor.side === "front" ? "Передній" : "Задній"} />
          <InfoRow label="X" value={sensor.x.toFixed(3)} />
          <InfoRow label="Y" value={sensor.y.toFixed(3)} />
        </div>
      ) : (
        <p className="mt-3 text-xs text-slate-500">Датчик не вибрано.</p>
      )}
    </section>
  );
}

function DraftStatus({
  editing,
  dirty,
  snapToGrid,
  sensorCount,
}: {
  editing: boolean;
  dirty: boolean;
  snapToGrid: boolean;
  sensorCount: number;
}) {
  return (
    <section className="rounded-2xl border border-white/[0.08] bg-[#08182e]/90 p-4">
      <h2 className="text-xs font-semibold text-white">Стан чернетки</h2>
      <div className="mt-3 space-y-2 text-[11px]">
        <InfoRow label="Режим" value={editing ? "Редагування" : "Перегляд"} />
        <InfoRow label="Зміни" value={dirty ? "Є незбережені" : "Немає"} />
        <InfoRow label="Прив’язка до сітки" value={snapToGrid ? "Увімкнена" : "Вимкнена"} />
        <InfoRow label="Кількість датчиків" value={String(sensorCount)} />
      </div>
    </section>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-slate-500">{label}</span>
      <span className="text-right text-slate-200">{value}</span>
    </div>
  );
}
