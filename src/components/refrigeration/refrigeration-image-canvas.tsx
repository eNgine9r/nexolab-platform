"use client";

import type {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
  RefObject,
  SyntheticEvent,
} from "react";
import Image from "next/image";
import { useId, useState } from "react";
import { clsx } from "clsx";
import { ImageIcon, Minus, Plus, Scan } from "lucide-react";

import type { EquipmentImageMetadata, RefrigerationSensor } from "@/data/refrigeration";
import type { LayoutPlacement, SnapMode } from "@/features/refrigeration/layout-editor";

type RefrigerationImageCanvasProps = {
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
  onMarkerKeyDown: (event: ReactKeyboardEvent<HTMLButtonElement>, sensorId: string) => void;
  onMarkerPointerDown: (event: ReactPointerEvent<HTMLButtonElement>, sensorId: string) => void;
  onMarkerPointerMove: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onMarkerPointerUp: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onImageDimensions: (widthPx: number, heightPx: number) => void;
};

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

const MIN_SCALE_PERCENT = 60;
const MAX_SCALE_PERCENT = 160;
const SCALE_STEP_PERCENT = 10;
const DEFAULT_SCALE_PERCENT = 80;

export function RefrigerationImageCanvas({
  equipmentId,
  equipmentName,
  image,
  visibleSensors,
  placementBySensorId,
  selectedId,
  mode,
  snapMode,
  stageRef,
  onSelect,
  onMarkerKeyDown,
  onMarkerPointerDown,
  onMarkerPointerMove,
  onMarkerPointerUp,
  onImageDimensions,
}: RefrigerationImageCanvasProps) {
  const sliderId = useId();
  const [scalePercent, setScalePercent] = useState(() => readStoredScale(equipmentId));

  const updateScale = (nextValue: number) => {
    const nextScale = clampScale(nextValue);
    setScalePercent(nextScale);
    storeScale(equipmentId, nextScale);
  };

  const aspectRatio =
    image && image.widthPx > 0 && image.heightPx > 0
      ? `${image.widthPx} / ${image.heightPx}`
      : "16 / 10";

  const handleImageLoad = (event: SyntheticEvent<HTMLImageElement>) => {
    onImageDimensions(event.currentTarget.naturalWidth, event.currentTarget.naturalHeight);
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[10px] leading-4 text-slate-500">
          Масштаб змінює фото та координатний canvas разом, тому точки датчиків не зміщуються.
        </p>
        <div
          className="flex items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.035] px-2.5 py-2"
          role="group"
          aria-label="Керування масштабом фото"
        >
          <Scan className="h-3.5 w-3.5 text-cyan-300" aria-hidden="true" />
          <label htmlFor={sliderId} className="text-[10px] font-medium text-slate-300">
            Масштаб фото
          </label>
          <button
            type="button"
            aria-label="Зменшити масштаб фото"
            title="Зменшити масштаб фото"
            disabled={scalePercent <= MIN_SCALE_PERCENT}
            onClick={() => updateScale(scalePercent - SCALE_STEP_PERCENT)}
            className="grid h-7 w-7 place-items-center rounded-lg border border-white/[0.08] text-slate-400 enabled:hover:bg-white/[0.06] enabled:hover:text-white disabled:cursor-not-allowed disabled:opacity-35"
          >
            <Minus className="h-3.5 w-3.5" />
          </button>
          <input
            id={sliderId}
            type="range"
            min={MIN_SCALE_PERCENT}
            max={MAX_SCALE_PERCENT}
            step={SCALE_STEP_PERCENT}
            value={scalePercent}
            aria-label="Масштаб фото"
            aria-valuetext={`${scalePercent} відсотків`}
            onChange={(event) => updateScale(Number(event.target.value))}
            className="h-1.5 w-28 cursor-pointer accent-cyan-400 sm:w-36"
          />
          <output
            htmlFor={sliderId}
            className="min-w-10 text-right text-[10px] font-semibold tabular-nums text-cyan-200"
            aria-live="polite"
          >
            {scalePercent}%
          </output>
          <button
            type="button"
            aria-label="Збільшити масштаб фото"
            title="Збільшити масштаб фото"
            disabled={scalePercent >= MAX_SCALE_PERCENT}
            onClick={() => updateScale(scalePercent + SCALE_STEP_PERCENT)}
            className="grid h-7 w-7 place-items-center rounded-lg border border-white/[0.08] text-slate-400 enabled:hover:bg-white/[0.06] enabled:hover:text-white disabled:cursor-not-allowed disabled:opacity-35"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() => updateScale(DEFAULT_SCALE_PERCENT)}
            className="rounded-lg border border-cyan-400/15 bg-cyan-500/[0.06] px-2 py-1 text-[9px] font-medium text-cyan-200 hover:bg-cyan-500/10"
          >
            Вмістити
          </button>
        </div>
      </div>

      <div
        data-testid="equipment-image-viewport"
        className={clsx(
          "relative h-[clamp(420px,68vh,760px)] overflow-auto overscroll-contain rounded-xl border border-cyan-300/[0.1] bg-[radial-gradient(circle_at_50%_10%,rgba(34,211,238,.12),transparent_42%),linear-gradient(160deg,#0a1f37,#030b15)]",
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
            <div
              data-testid="equipment-image-media-layer"
              className="absolute inset-0 z-0 overflow-hidden rounded-lg"
            >
              {image?.sourceUrl ? (
                <Image
                  src={image.sourceUrl}
                  alt={image.alt}
                  fill
                  unoptimized
                  draggable={false}
                  sizes="(min-width: 1536px) 1100px, 90vw"
                  className="object-contain select-none"
                  onLoad={handleImageLoad}
                />
              ) : (
                <PhotoPlaceholder equipmentName={equipmentName} />
              )}
            </div>

            <div className="pointer-events-none absolute inset-0 z-10 rounded-lg bg-[linear-gradient(180deg,rgba(2,8,23,.04),rgba(2,8,23,.18))]" />
            {mode === "edit" && snapMode === "grid" ? (
              <div className="pointer-events-none absolute inset-0 z-20 rounded-lg bg-[linear-gradient(rgba(56,189,248,.12)_1px,transparent_1px),linear-gradient(90deg,rgba(56,189,248,.12)_1px,transparent_1px)] bg-[size:2.5%_2.5%]" />
            ) : null}

            <div
              data-testid="sensor-marker-layer"
              className="pointer-events-none absolute inset-0 z-40"
            >
              {visibleSensors.map((sensor) => {
                const placement = placementBySensorId.get(sensor.id);
                if (!placement) return null;

                return (
                  <button
                    key={sensor.id}
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
                      "pointer-events-auto absolute z-0 min-w-10 -translate-x-1/2 -translate-y-1/2 rounded-md border px-1.5 py-1 text-center text-[8px] leading-tight font-bold backdrop-blur-md transition-[transform,box-shadow] focus:z-20 focus:ring-2 focus:ring-cyan-200 focus:outline-none",
                      markerTone[sensor.status],
                      sensor.id === selectedId && "z-20 scale-110 ring-2 ring-white/90",
                      mode === "edit"
                        ? "cursor-grab touch-none hover:z-20 hover:scale-110 active:cursor-grabbing"
                        : "cursor-pointer hover:z-20 hover:scale-110",
                    )}
                    style={{ left: `${placement.x * 100}%`, top: `${placement.y * 100}%` }}
                  >
                    <span className="block">{sensor.label}</span>
                    <span className="block font-semibold">{formatTemperature(sensor.temperatureC)}</span>
                  </button>
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
            ? "Перетягніть маркер або використовуйте стрілки"
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
          {equipmentName}: JPEG, PNG або WebP до 15 МБ. Розміщення датчиків збережеться при заміні
          зображення.
        </p>
      </div>
    </div>
  );
}

function clampScale(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_SCALE_PERCENT;
  return Math.min(
    MAX_SCALE_PERCENT,
    Math.max(
      MIN_SCALE_PERCENT,
      Math.round(value / SCALE_STEP_PERCENT) * SCALE_STEP_PERCENT,
    ),
  );
}

function readStoredScale(equipmentId: string): number {
  try {
    const storedValue = window.localStorage.getItem(scaleStorageKey(equipmentId));
    return storedValue === null ? DEFAULT_SCALE_PERCENT : clampScale(Number(storedValue));
  } catch {
    return DEFAULT_SCALE_PERCENT;
  }
}

function storeScale(equipmentId: string, scalePercent: number): void {
  try {
    window.localStorage.setItem(scaleStorageKey(equipmentId), String(scalePercent));
  } catch {
    // View preferences must not block the operational layout editor.
  }
}

function scaleStorageKey(equipmentId: string): string {
  return `nexolab:refrigeration:image-scale:${equipmentId}`;
}

function formatTemperature(temperatureC: number | null): string {
  return temperatureC === null ? "—" : `${temperatureC.toFixed(1)}°`;
}

function formatFileSize(sizeBytes: number): string {
  if (sizeBytes <= 0) return "локальне фото";
  if (sizeBytes < 1024 * 1024) return `${Math.round(sizeBytes / 1024)} КБ`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} МБ`;
}
