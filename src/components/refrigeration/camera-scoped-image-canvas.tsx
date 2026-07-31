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
  const [fitContour, setFitContour] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    const handleFullscreenChange = () => {
      setFullscreen(document.fullscreenElement === workspaceRef.current);
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  const updateScale = (value: number) => {
    setFitContour(false);
    setScalePercent(Math.min(180, Math.max(60, value)));
  };

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
      data-fit-contour={fitContour}
      className={clsx(
        "space-y-2",
        fullscreen && "h-screen overflow-hidden bg-[#06142a] p-3 text-slate-100",
      )}
    >
      <div className="flex items-center justify-end gap-1.5">
        <div
          className="flex items-center gap-1 rounded-xl border border-white/[0.07] bg-white/[0.025] p-1"
          role="group"
          aria-label="Керування зображенням"
        >
          <button
            type="button"
            aria-label="Зменшити масштаб фото"
            title="Зменшити"
            disabled={!fitContour && scalePercent <= 60}
            onClick={() => updateScale(scalePercent - 10)}
            className={smallButtonClass}
          >
            <Minus className="h-3.5 w-3.5" />
          </button>
          <label htmlFor={sliderId} className="sr-only">
            Масштаб фото
          </label>
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
            className="h-1.5 w-20 cursor-pointer accent-cyan-400 sm:w-28"
          />
          <output className="min-w-8 text-right text-[9px] font-semibold tabular-nums text-cyan-200">
            {scalePercent}%
          </output>
          <button
            type="button"
            aria-label="Збільшити масштаб фото"
            title="Збільшити"
            disabled={!fitContour && scalePercent >= 180}
            onClick={() => updateScale(scalePercent + 10)}
            className={smallButtonClass}
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            aria-label="Заповнити контур без прокручування"
            title="Заповнити контур"
            aria-pressed={fitContour}
            onClick={() => setFitContour((current) => !current)}
            className={clsx(
              smallButtonClass,
              fitContour && "border-cyan-300/25 bg-cyan-400/15 text-cyan-100",
            )}
          >
            <Scan className="h-3.5 w-3.5" />
          </button>
        </div>

        <button
          type="button"
          aria-label={expanded ? "Звичайний розмір підкладки" : "Збільшити підкладку"}
          title={expanded ? "Звичайний розмір" : "Розгорнути"}
          aria-pressed={expanded}
          onClick={() => setExpanded((current) => !current)}
          className={toolbarButtonClass}
        >
          {expanded ? <Shrink className="h-3.5 w-3.5" /> : <Expand className="h-3.5 w-3.5" />}
        </button>

        <button
          type="button"
          aria-label={
            fullscreen
              ? "Вийти з повноекранного режиму"
              : "Відкрити підкладку на повний екран"
          }
          title={fullscreen ? "Вийти з повного екрана" : "Повний екран"}
          onClick={() => void toggleFullscreen()}
          className={toolbarButtonClass}
        >
          {fullscreen ? (
            <Minimize2 className="h-3.5 w-3.5" />
          ) : (
            <Maximize2 className="h-3.5 w-3.5" />
          )}
        </button>
      </div>

      <div
        data-testid="equipment-image-viewport"
        className={clsx(
          "relative overscroll-contain rounded-xl border border-cyan-300/[0.1] bg-[radial-gradient(circle_at_50%_10%,rgba(34,211,238,.12),transparent_42%),linear-gradient(160deg,#0a1f37,#030b15)] transition-[height] duration-300",
          fitContour ? "overflow-hidden" : "overflow-auto",
          fullscreen
            ? "h-[calc(100vh-64px)]"
            : expanded
              ? "h-[clamp(760px,86vh,1180px)]"
              : "h-[clamp(640px,80vh,980px)]",
          mode === "edit" && "ring-1 ring-blue-400/30",
        )}
      >
        <div
          className={clsx(
            "relative",
            fitContour ? "h-full w-full" : "min-h-full min-w-full p-3",
          )}
        >
          <div
            ref={stageRef}
            data-testid="equipment-image-stage"
            data-scale-percent={scalePercent}
            data-fit-contour={fitContour}
            className="relative isolate overflow-hidden rounded-lg border border-white/[0.06] bg-slate-950/60 shadow-[0_18px_48px_rgba(0,0,0,.28)]"
            style={
              fitContour
                ? {
                    width: "100%",
                    height: "100%",
                    margin: 0,
                  }
                : {
                    width: `${scalePercent}%`,
                    aspectRatio,
                    marginInline: scalePercent <= 100 ? "auto" : "0",
                  }
            }
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
                  className={clsx(
                    "select-none",
                    fitContour ? "object-fill" : "object-contain",
                  )}
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

            <div
              data-testid="sensor-marker-layer"
              className="pointer-events-none absolute inset-0 z-40"
            >
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
                    style={{
                      left: `${placement.x * 100}%`,
                      top: `${placement.y * 100}%`,
                    }}
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
                      <span className="block font-semibold">
                        {formatTemperature(sensor.temperatureC)}
                      </span>
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function PhotoPlaceholder({ equipmentName }: { equipmentName: string }) {
  return (
    <div className="absolute inset-0 grid place-items-center p-8 text-center">
      <div>
        <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl border border-cyan-300/15 bg-cyan-400/[0.06] text-cyan-300">
          <ImageIcon className="h-6 w-6" />
        </div>
        <p className="mt-3 text-xs font-medium text-slate-300">
          Фото {equipmentName} не завантажено
        </p>
      </div>
    </div>
  );
}

function formatTemperature(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(1)}°`;
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
  "grid h-9 w-9 place-items-center rounded-xl border border-cyan-400/20 bg-cyan-500/[0.08] text-cyan-200 hover:bg-cyan-500/15";
