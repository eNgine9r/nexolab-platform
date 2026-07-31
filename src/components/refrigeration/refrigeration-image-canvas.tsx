"use client";

import type {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
  RefObject,
  SyntheticEvent,
} from "react";
import Image from "next/image";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { clsx } from "clsx";
import {
  Expand,
  ImageIcon,
  Maximize2,
  Minimize2,
  Minus,
  Plus,
  Scan,
  Shrink,
} from "lucide-react";

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
  onMarkerKeyDown: (
    event: ReactKeyboardEvent<HTMLButtonElement>,
    sensorId: string,
  ) => void;
  onMarkerPointerDown: (
    event: ReactPointerEvent<HTMLButtonElement>,
    sensorId: string,
  ) => void;
  onMarkerPointerMove: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onMarkerPointerUp: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onImageDimensions: (widthPx: number, heightPx: number) => void;
};

const MIN_SCALE_PERCENT = 60;
const MAX_SCALE_PERCENT = 180;
const SCALE_STEP_PERCENT = 10;
const DEFAULT_SCALE_PERCENT = 100;
const SCALE_CHANGE_EVENT = "nexolab:refrigeration:image-scale-change";
const scaleMemory = new Map<string, number>();
const volatileScaleKeys = new Set<string>();

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
  const workspaceRef = useRef<HTMLDivElement>(null);
  const [fitContour, setFitContour] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);

  const subscribeToScale = useCallback(
    (onStoreChange: () => void) =>
      subscribeToStoredScale(equipmentId, onStoreChange),
    [equipmentId],
  );
  const getScaleSnapshot = useCallback(
    () => readStoredScale(equipmentId),
    [equipmentId],
  );
  const scalePercent = useSyncExternalStore(
    subscribeToScale,
    getScaleSnapshot,
    getDefaultScaleSnapshot,
  );

  useEffect(() => {
    const handleFullscreenChange = () => {
      setFullscreen(document.fullscreenElement === workspaceRef.current);
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () =>
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  useEffect(() => {
    if (!fullscreen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [fullscreen]);

  const updateScale = (nextValue: number) => {
    setFitContour(false);
    storeScale(equipmentId, clampScale(nextValue));
  };

  const toggleFullscreen = async () => {
    const workspace = workspaceRef.current;
    if (!workspace) return;

    if (document.fullscreenElement === workspace) {
      await document.exitFullscreen?.();
      return;
    }

    try {
      if (!workspace.requestFullscreen) {
        throw new Error("Fullscreen API is unavailable");
      }
      await workspace.requestFullscreen();
    } catch {
      setExpanded(true);
      workspace.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  const aspectRatio =
    image && image.widthPx > 0 && image.heightPx > 0
      ? `${image.widthPx} / ${image.heightPx}`
      : "16 / 10";

  const handleImageLoad = (event: SyntheticEvent<HTMLImageElement>) => {
    onImageDimensions(
      event.currentTarget.naturalWidth,
      event.currentTarget.naturalHeight,
    );
  };

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
            disabled={!fitContour && scalePercent <= MIN_SCALE_PERCENT}
            onClick={() => updateScale(scalePercent - SCALE_STEP_PERCENT)}
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
            min={MIN_SCALE_PERCENT}
            max={MAX_SCALE_PERCENT}
            step={SCALE_STEP_PERCENT}
            value={scalePercent}
            aria-label="Масштаб фото"
            aria-valuetext={`${scalePercent} відсотків`}
            onChange={(event) => updateScale(Number(event.target.value))}
            className="h-1.5 w-20 cursor-pointer accent-cyan-400 sm:w-28"
          />
          <output
            htmlFor={sliderId}
            className="min-w-8 text-right text-[9px] font-semibold tabular-nums text-cyan-200"
            aria-live="polite"
          >
            {scalePercent}%
          </output>

          <button
            type="button"
            aria-label="Збільшити масштаб фото"
            title="Збільшити"
            disabled={!fitContour && scalePercent >= MAX_SCALE_PERCENT}
            onClick={() => updateScale(scalePercent + SCALE_STEP_PERCENT)}
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
              fitContour &&
                "border-cyan-300/25 bg-cyan-400/15 text-cyan-100",
            )}
          >
            <Scan className="h-3.5 w-3.5" />
          </button>
        </div>

        <button
          type="button"
          aria-label={
            expanded ? "Звичайний розмір підкладки" : "Збільшити підкладку"
          }
          title={expanded ? "Звичайний розмір" : "Розгорнути"}
          aria-pressed={expanded}
          onClick={() => setExpanded((current) => !current)}
          className={toolbarButtonClass}
        >
          {expanded ? (
            <Shrink className="h-3.5 w-3.5" />
          ) : (
            <Expand className="h-3.5 w-3.5" />
          )}
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
              ? "h-[clamp(720px,84vh,1120px)]"
              : "h-[clamp(560px,76vh,920px)]",
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
                ? { width: "100%", height: "100%", margin: 0 }
                : {
                    width: `${scalePercent}%`,
                    aspectRatio,
                    marginInline: scalePercent <= 100 ? "auto" : "0",
                  }
            }
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
                  sizes="(min-width: 1536px) 1700px, 98vw"
                  className={clsx(
                    "select-none",
                    fitContour ? "object-fill" : "object-contain",
                  )}
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
                    onPointerDown={(event) =>
                      onMarkerPointerDown(event, sensor.id)
                    }
                    onPointerMove={onMarkerPointerMove}
                    onPointerUp={onMarkerPointerUp}
                    onPointerCancel={onMarkerPointerUp}
                    className={clsx(
                      "pointer-events-auto absolute z-0 min-w-10 -translate-x-1/2 -translate-y-1/2 rounded-md border px-1.5 py-1 text-center text-[8px] leading-tight font-bold backdrop-blur-md transition-[transform,box-shadow] focus:z-20 focus:ring-2 focus:ring-cyan-200 focus:outline-none",
                      markerTone[sensor.status],
                      sensor.id === selectedId &&
                        "z-20 scale-110 ring-2 ring-white/90",
                      mode === "edit"
                        ? "cursor-grab touch-none hover:z-20 hover:scale-110 active:cursor-grabbing"
                        : "cursor-pointer hover:z-20 hover:scale-110",
                    )}
                    style={{
                      left: `${placement.x * 100}%`,
                      top: `${placement.y * 100}%`,
                    }}
                  >
                    <span className="block">{sensor.label}</span>
                    <span className="block font-semibold">
                      {formatTemperature(sensor.temperatureC)}
                    </span>
                  </button>
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

function getDefaultScaleSnapshot(): number {
  return DEFAULT_SCALE_PERCENT;
}

function subscribeToStoredScale(
  equipmentId: string,
  onStoreChange: () => void,
): () => void {
  const key = scaleStorageKey(equipmentId);

  const handleStorage = (event: StorageEvent) => {
    if (event.key !== key) return;
    volatileScaleKeys.delete(key);
    if (event.newValue === null) {
      scaleMemory.delete(key);
    } else {
      scaleMemory.set(key, clampScale(Number(event.newValue)));
    }
    onStoreChange();
  };

  const handleLocalChange = (event: Event) => {
    if (event instanceof CustomEvent && event.detail === key) {
      onStoreChange();
    }
  };

  window.addEventListener("storage", handleStorage);
  window.addEventListener(SCALE_CHANGE_EVENT, handleLocalChange);
  return () => {
    window.removeEventListener("storage", handleStorage);
    window.removeEventListener(SCALE_CHANGE_EVENT, handleLocalChange);
  };
}

function readStoredScale(equipmentId: string): number {
  const key = scaleStorageKey(equipmentId);
  if (volatileScaleKeys.has(key)) {
    return scaleMemory.get(key) ?? DEFAULT_SCALE_PERCENT;
  }

  try {
    const storedValue = window.localStorage.getItem(key);
    if (storedValue === null) {
      scaleMemory.delete(key);
      return DEFAULT_SCALE_PERCENT;
    }
    const scale = clampScale(Number(storedValue));
    scaleMemory.set(key, scale);
    return scale;
  } catch {
    return scaleMemory.get(key) ?? DEFAULT_SCALE_PERCENT;
  }
}

function storeScale(equipmentId: string, scalePercent: number): void {
  const key = scaleStorageKey(equipmentId);
  scaleMemory.set(key, scalePercent);
  try {
    window.localStorage.setItem(key, String(scalePercent));
    volatileScaleKeys.delete(key);
  } catch {
    volatileScaleKeys.add(key);
  }
  window.dispatchEvent(new CustomEvent(SCALE_CHANGE_EVENT, { detail: key }));
}

function scaleStorageKey(equipmentId: string): string {
  return `nexolab:refrigeration:image-scale:${equipmentId}`;
}

function formatTemperature(temperatureC: number | null): string {
  return temperatureC === null ? "—" : `${temperatureC.toFixed(1)}°`;
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
  "grid h-9 w-9 place-items-center rounded-xl border border-white/[0.08] bg-white/[0.035] text-slate-300 hover:bg-white/[0.06] hover:text-white";
