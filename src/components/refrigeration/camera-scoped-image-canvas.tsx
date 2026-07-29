"use client";

import type {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
  RefObject,
  SyntheticEvent,
} from "react";
import Image from "next/image";
import { useEffect, useId, useRef, useState } from "react";
import { clsx } from "clsx";
import {
  Expand,
  ImageIcon,
  Maximize2,
  Minimize2,
  Minus,
  Pencil,
  Plus,
  Scan,
  Shrink,
} from "lucide-react";

import type { EquipmentImageMetadata, RefrigerationSensor } from "@/data/refrigeration";
import type { LayoutPlacement, SnapMode } from "@/features/refrigeration/layout-editor";

export function CameraScopedImageCanvas({
  equipmentName,
  image,
  visibleSensors,
  placementBySensorId,
  selectedId,
  mode,
  snapMode,
  stageRef,
  onSelect,
  onEditSensor,
  onMarkerKeyDown,
  onMarkerPointerDown,
  onMarkerPointerMove,
  onMarkerPointerUp,
  onImageDimensions,
}: {
  equipmentId: string;
  equipmentName: string;
  image: EquipmentImageMetadata | null;
  visibleSensors: RefrigerationSensor[];
  placementBySensorId: ReadonlyMap<string, LayoutPlacement>;
  selectedId: string | null;
  mode: "view" | "edit";
  snapMode: SnapMode;
  stageRef: RefObject<HTMLDivElement | null>;
  onSelect: (sensorId: string) => void;
  onEditSensor: (sensorId: string) => void;
  onMarkerKeyDown: (event: ReactKeyboardEvent<HTMLButtonElement>, sensorId: string) => void;
  onMarkerPointerDown: (event: ReactPointerEvent<HTMLButtonElement>, sensorId: string) => void;
  onMarkerPointerMove: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onMarkerPointerUp: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onImageDimensions: (widthPx: number, heightPx: number) => void;
}) {
  const sliderId = useId();
  const workspaceRef = useRef<HTMLDivElement>(null);
  const [scalePercent, setScalePercent] = useState(100);
  const [expanded, setExpanded] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    const handleFullscreenChange = () => {
      setFullscreen(document.fullscreenElement === workspaceRef.current);
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  const updateScale = (value: number) => setScalePercent(Math.min(180, Math.max(60, value)));
  const toggleFullscreen = async () => {
    const workspace = workspaceRef.current;
    if (!workspace) return;
    if (document.fullscreenElement === workspace) {
      await document.exitFullscreen?.();
      return;
    }
    try {
      await workspace.requestFullscreen?.();
    } catch {
      setExpanded(true);
      workspace.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };
  const aspectRatio =
    image && image.widthPx > 0 && image.heightPx > 0
      ? `${image.widthPx} / ${image.heightPx}`
      : "16 / 10";

  return (
    <div
      ref={workspaceRef}
      data-testid="equipment-image-workspace"
      data-expanded={expanded}
      data-fullscreen={fullscreen}
      className={clsx(
        "space-y-2",
        fullscreen && "h-screen overflow-auto bg-[#06142a] p-4 text-slate-100",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[10px] leading-4 text-slate-500">
          Фото та координатний canvas масштабуються разом — розміщення датчиків не зміщується.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <div
            className="flex items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.035] px-2.5 py-2"
            role="group"
            aria-label="Керування масштабом фото"
          >
            <Scan className="h-3.5 w-3.5 text-cyan-300" aria-hidden="true" />
            <label htmlFor={sliderId} className="text-[10px] font-medium text-slate-300">
              Масштаб
            </label>
            <button
              type="button"
              aria-label="Зменшити масштаб фото"
              disabled={scalePercent <= 60}
              onClick={() => updateScale(scalePercent - 10)}
              className={smallButtonClass}
            >
              <Minus className="h-3.5 w-3.5" />
            </button>
            <input
              id={sliderId}
              type="range"
              min={60}
              max={180}
              step={10}
              value={scalePercent}
              aria-label="Масштаб фото"
              aria-valuetext={`${scalePercent} відсотків`}
              onChange={(event) => updateScale(Number(event.target.value))}
              className="h-1.5 w-28 cursor-pointer accent-cyan-400 sm:w-36"
            />
            <output className="min-w-10 text-right text-[10px] font-semibold tabular-nums text-cyan-200">
              {scalePercent}%
            </output>
            <button
              type="button"
              aria-label="Збільшити масштаб фото"
              disabled={scalePercent >= 180}
              onClick={() => updateScale(scalePercent + 10)}
              className={smallButtonClass}
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              aria-label="Вмістити фото"
              onClick={() => updateScale(100)}
              className="rounded-lg border border-cyan-400/15 bg-cyan-500/[0.06] px-2 py-1 text-[9px] font-medium text-cyan-200 hover:bg-cyan-500/10"
            >
              Вмістити
            </button>
          </div>
          <button
            type="button"
            aria-label={expanded ? "Звичайний розмір підкладки" : "Збільшити підкладку"}
            aria-pressed={expanded}
            onClick={() => setExpanded((current) => !current)}
            className={toolbarButtonClass}
          >
            {expanded ? <Shrink className="h-3.5 w-3.5" /> : <Expand className="h-3.5 w-3.5" />}
            <span className="hidden sm:inline">{expanded ? "Звичайний" : "Розгорнути"}</span>
          </button>
          <button
            type="button"
            aria-label={fullscreen ? "Вийти з повноекранного режиму" : "Відкрити підкладку на повний екран"}
            onClick={() => void toggleFullscreen()}
            className={toolbarButtonClass}
          >
            {fullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
            <span className="hidden sm:inline">{fullscreen ? "Вийти" : "Повний екран"}</span>
          </button>
        </div>
      </div>

      <div
        data-testid="equipment-image-viewport"
        className={clsx(
          "relative overflow-auto overscroll-contain rounded-xl border border-cyan-300/[0.1] bg-[radial-gradient(circle_at_50%_10%,rgba(34,211,238,.12),transparent_42%),linear-gradient(160deg,#0a1f37,#030b15)] transition-[height] duration-300",
          fullscreen
            ? "h-[calc(100vh-116px)]"
            : expanded
              ? "h-[clamp(760px,86vh,1180px)]"
              : "h-[clamp(620px,80vh,980px)]",
          mode === "edit" && "ring-1 ring-blue-400/30",
        )}
      >
        <div className="relative min-h-full min-w-full p-3">
          <div
            ref={stageRef}
            data-testid="equipment-image-stage"
            data-scale-percent={scalePercent}
            className="relative isolate overflow-visible rounded-lg border border-white/[0.06] bg-slate-950/60 shadow-[0_18px_48px_rgba(0,0,0,.28)]"
            style={{
              width: `${scalePercent}%`,
              aspectRatio,
              marginInline: scalePercent <= 100 ? "auto" : "0",
            }}
          >
            <div className="absolute inset-0 z-0 overflow-hidden rounded-lg">
              {image?.sourceUrl ? (
                <Image
                  src={image.sourceUrl}
                  alt={image.alt}
                  fill
                  unoptimized
                  draggable={false}
                  sizes="(min-width: 1536px) 1700px, 98vw"
                  className="object-contain select-none"
                  onLoad={(event: SyntheticEvent<HTMLImageElement>) =>
                    onImageDimensions(
                      event.currentTarget.naturalWidth,
                      event.currentTarget.naturalHeight,
                    )
                  }
                />
              ) : (
                <PhotoPlaceholder equipmentName={equipmentName} />
              )}
            </div>
            <div className="pointer-events-none absolute inset-0 z-10 rounded-lg bg-[linear-gradient(180deg,rgba(2,8,23,.04),rgba(2,8,23,.18))]" />
            {mode === "edit" && snapMode === "grid" ? (
              <div className="pointer-events-none absolute inset-0 z-20 rounded-lg bg-[linear-gradient(rgba(56,189,248,.12)_1px,transparent_1px),linear-gradient(90deg,rgba(56,189,248,.12)_1px,transparent_1px)] bg-[size:2.5%_2.5%]" />
            ) : null}

            <div data-testid="sensor-marker-layer" className="pointer-events-none absolute inset-0 z-40">
              {visibleSensors.map((sensor) => {
                const placement = placementBySensorId.get(sensor.id);
                if (!placement) return null;
                return (
                  <div
                    key={sensor.id}
                    className={clsx(
                      "pointer-events-none absolute z-0 -translate-x-1/2 -translate-y-1/2",
                      sensor.id === selectedId && "z-20",
                    )}
                    style={{ left: `${placement.x * 100}%`, top: `${placement.y * 100}%` }}
                  >
                    {mode === "edit" ? (
                      <button
                        type="button"
                        aria-label={`Редагувати датчик ${sensor.label}`}
                        title={`Редагувати ${sensor.label}`}
                        onPointerDown={(event) => event.stopPropagation()}
                        onClick={(event) => {
                          event.stopPropagation();
                          onEditSensor(sensor.id);
                        }}
                        className="pointer-events-auto absolute -top-6 left-1/2 z-30 grid h-5 w-5 -translate-x-1/2 place-items-center rounded-full border border-blue-200/70 bg-blue-950/95 text-blue-100 shadow-lg transition hover:scale-110 hover:bg-blue-800 focus:ring-2 focus:ring-cyan-200 focus:outline-none"
                      >
                        <Pencil className="h-2.5 w-2.5" />
                      </button>
                    ) : null}
                    <button
                      type="button"
                      aria-label={`Вибрати датчик ${sensor.label} на схемі`}
                      aria-pressed={sensor.id === selectedId}
                      data-x={placement.x.toFixed(4)}
                      data-y={placement.y.toFixed(4)}
                      onClick={() => onSelect(sensor.id)}
                      onKeyDown={(event) => onMarkerKeyDown(event, sensor.id)}
                      onPointerDown={(event) => onMarkerPointerDown(event, sensor.id)}
                      onPointerMove={onMarkerPointerMove}
                      onPointerUp={onMarkerPointerUp}
                      onPointerCancel={onMarkerPointerUp}
                      className={clsx(
                        "pointer-events-auto relative min-w-10 rounded-md border px-1.5 py-1 text-center text-[8px] leading-tight font-bold backdrop-blur-md transition-[transform,box-shadow] focus:z-20 focus:ring-2 focus:ring-cyan-200 focus:outline-none",
                        markerTone[sensor.status],
                        sensor.id === selectedId && "scale-110 ring-2 ring-white/90",
                        mode === "edit"
                          ? "cursor-grab touch-none hover:scale-110 active:cursor-grabbing"
                          : "cursor-pointer hover:scale-110",
                      )}
                    >
                      <span className="block">{sensor.label}</span>
                      <span className="block font-semibold">{formatTemperature(sensor.temperatureC)}</span>
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-white/[0.07] bg-slate-950/55 px-3 py-2 text-[9px] text-slate-400">
        <span>
          {image
            ? `${image.fileName} · ${formatFileSize(image.sizeBytes)}${image.widthPx > 0 ? ` · ${image.widthPx}×${image.heightPx}` : ""}`
            : "Фото ще не завантажено"}
        </span>
        <span>
          {mode === "edit"
            ? "Перетягніть маркер; олівець відкриває параметри"
            : "Клікніть маркер для вибору"}
        </span>
      </div>
    </div>
  );
}

function PhotoPlaceholder({ equipmentName }: { equipmentName: string }) {
  return (
    <div className="absolute inset-0 grid place-items-center p-8 text-center">
      <div>
        <div className="mx-auto grid h-16 w-16 place-items-center rounded-2xl border border-cyan-300/15 bg-cyan-400/[0.06] text-cyan-300">
          <ImageIcon className="h-7 w-7" />
        </div>
        <p className="mt-4 text-sm font-medium text-slate-200">Завантажте реальне фото вітрини</p>
        <p className="mt-2 max-w-md text-xs leading-5 text-slate-500">
          {equipmentName}: JPEG, PNG або WebP до 1,5 МБ. Розміщення датчиків збережеться при заміні
          зображення.
        </p>
      </div>
    </div>
  );
}

function formatTemperature(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(1)}°`;
}

function formatFileSize(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

const markerTone = {
  normal:
    "border-emerald-200/90 bg-emerald-950/90 text-emerald-50 shadow-[0_2px_14px_rgba(2,6,23,.72),0_0_16px_rgba(16,185,129,.38)]",
  warning:
    "border-amber-200/90 bg-amber-950/90 text-amber-50 shadow-[0_2px_14px_rgba(2,6,23,.72),0_0_18px_rgba(245,158,11,.42)]",
  alarm:
    "border-rose-200/95 bg-rose-950/90 text-rose-50 shadow-[0_2px_14px_rgba(2,6,23,.72),0_0_20px_rgba(244,63,94,.48)]",
  "no-data":
    "border-slate-300/80 bg-slate-950/90 text-slate-100 shadow-[0_2px_14px_rgba(2,6,23,.72)]",
};
const smallButtonClass =
  "grid h-7 w-7 place-items-center rounded-lg border border-white/[0.08] text-slate-400 enabled:hover:bg-white/[0.06] enabled:hover:text-white disabled:cursor-not-allowed disabled:opacity-35";
const toolbarButtonClass =
  "inline-flex items-center gap-2 rounded-xl border border-cyan-400/20 bg-cyan-500/[0.08] px-3 py-2 text-[10px] font-medium text-cyan-200 hover:bg-cyan-500/15";
