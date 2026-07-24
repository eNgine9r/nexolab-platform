"use client";

import type {
  ChangeEvent,
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
} from "react";
import Image from "next/image";
import { useEffect, useMemo, useRef, useState } from "react";
import { clsx } from "clsx";
import {
  Check,
  Grid3X3,
  History,
  ImageIcon,
  MousePointer2,
  Redo2,
  RotateCcw,
  Save,
  Undo2,
  Upload,
  X,
} from "lucide-react";

import type {
  EquipmentImageMetadata,
  RefrigerationEquipment,
  RefrigerationSensor,
} from "@/data/refrigeration";
import {
  createBrowserLayoutDraftStorage,
  createLayoutDraftPayload,
  parseLayoutDraft,
  serializeLayoutDraft,
  type LayoutDraftPayload,
  type LayoutDraftStorage,
} from "@/features/refrigeration/layout-draft-storage";
import {
  applySnap,
  movePlacement,
  pushHistory,
  redo,
  undo,
  type CommandHistory,
  type LayoutPlacement,
  type NormalizedPoint,
  type SnapMode,
} from "@/features/refrigeration/layout-editor";

export type LayoutEditorMode = "view" | "edit";

interface RefrigerationLayoutEditorProps {
  equipment: RefrigerationEquipment;
  visibleSensors: RefrigerationSensor[];
  selectedId: string | null;
  mode: LayoutEditorMode;
  onModeChange: (mode: LayoutEditorMode) => void;
  onSelect: (sensorId: string) => void;
}

interface DragState {
  sensorId: string;
  pointerId: number;
  before: NormalizedPoint;
  offset: NormalizedPoint;
}

const markerTone = {
  normal:
    "border-emerald-300/70 bg-emerald-500/25 text-emerald-100 shadow-[0_0_16px_rgba(16,185,129,.2)]",
  warning:
    "border-amber-300/80 bg-amber-500/25 text-amber-100 shadow-[0_0_16px_rgba(245,158,11,.25)]",
  alarm:
    "border-rose-300/80 bg-rose-500/30 text-rose-100 shadow-[0_0_20px_rgba(244,63,94,.32)]",
  "no-data": "border-slate-400/60 bg-slate-600/40 text-slate-200",
};

const acceptedImageTypes = new Set(["image/jpeg", "image/png", "image/webp"]);
const maxImageSizeBytes = 15 * 1024 * 1024;

function createEmptyHistory(): CommandHistory {
  return { past: [], future: [] };
}

export function RefrigerationLayoutEditor({
  equipment,
  visibleSensors,
  selectedId,
  mode,
  onModeChange,
  onSelect,
}: RefrigerationLayoutEditorProps) {
  const initialPlacements = useMemo(
    () =>
      equipment.sensors.map(({ id, x, y }) => ({ sensorId: id, x, y })),
    [equipment.sensors],
  );
  const slots = useMemo(
    () => initialPlacements.map(({ x, y }) => ({ x, y })),
    [initialPlacements],
  );

  const [persistedPlacements, setPersistedPlacements] =
    useState<LayoutPlacement[]>(initialPlacements);
  const [draftPlacements, setDraftPlacements] =
    useState<LayoutPlacement[]>(initialPlacements);
  const [persistedImage, setPersistedImage] =
    useState<EquipmentImageMetadata | null>(equipment.image);
  const [draftImage, setDraftImage] =
    useState<EquipmentImageMetadata | null>(equipment.image);
  const [history, setHistory] = useState<CommandHistory>(() =>
    createEmptyHistory(),
  );
  const [snapMode, setSnapMode] = useState<SnapMode>("none");
  const [imageError, setImageError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [recoveryDraft, setRecoveryDraft] =
    useState<LayoutDraftPayload | null>(null);
  const [recoveryChecked, setRecoveryChecked] = useState(false);

  const stageRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragRef = useRef<DragState | null>(null);
  const draftPlacementsRef = useRef(draftPlacements);
  const historyRef = useRef(history);
  const objectUrlsRef = useRef(new Set<string>());
  const storageRef = useRef<LayoutDraftStorage | null>(null);
  const initialPlacementsRef = useRef(initialPlacements);

  const placementDirty = !placementsEqual(
    draftPlacements,
    persistedPlacements,
  );
  const imageDirty = !imagesEqual(draftImage, persistedImage);
  const dirty = placementDirty || imageDirty;

  useEffect(() => {
    draftPlacementsRef.current = draftPlacements;
  }, [draftPlacements]);

  useEffect(() => {
    historyRef.current = history;
  }, [history]);

  useEffect(() => {
    const storage = createBrowserLayoutDraftStorage(window.sessionStorage);
    storageRef.current = storage;
    const raw = storage.load(equipment.id);
    const allowedSensorIds = new Set(
      initialPlacementsRef.current.map((placement) => placement.sensorId),
    );
    const parsed = parseLayoutDraft(raw, equipment.id, allowedSensorIds);

    if (raw && !parsed) {
      storage.remove(equipment.id);
    }

    if (parsed) {
      if (placementsEqual(parsed.placements, initialPlacementsRef.current)) {
        storage.remove(equipment.id);
      } else {
        setRecoveryDraft(parsed);
      }
    }

    setRecoveryChecked(true);
  }, [equipment.id]);

  useEffect(() => {
    if (!recoveryChecked || recoveryDraft || mode !== "edit") return;

    if (!placementDirty) {
      storageRef.current?.remove(equipment.id);
      return;
    }

    storageRef.current?.save(
      equipment.id,
      serializeLayoutDraft(
        createLayoutDraftPayload(equipment.id, draftPlacements),
      ),
    );
  }, [
    draftPlacements,
    equipment.id,
    mode,
    placementDirty,
    recoveryChecked,
    recoveryDraft,
  ]);

  useEffect(() => {
    if (!dirty) return;

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [dirty]);

  useEffect(() => {
    if (mode !== "edit") return;

    const handleShortcut = (event: globalThis.KeyboardEvent) => {
      if (
        !(event.ctrlKey || event.metaKey) ||
        event.key.toLowerCase() !== "z"
      ) {
        return;
      }

      event.preventDefault();
      const result = event.shiftKey
        ? redo(draftPlacementsRef.current, historyRef.current)
        : undo(draftPlacementsRef.current, historyRef.current);
      setPlacements(result.placements);
      setHistoryState(result.history);
      setSaveMessage(null);
    };

    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [mode]);

  useEffect(
    () => () => {
      for (const url of objectUrlsRef.current) {
        URL.revokeObjectURL?.(url);
      }
    },
    [],
  );

  const placementBySensorId = useMemo(
    () =>
      new Map(
        draftPlacements.map((placement) => [placement.sensorId, placement]),
      ),
    [draftPlacements],
  );

  function setPlacements(placements: LayoutPlacement[]) {
    draftPlacementsRef.current = placements;
    setDraftPlacements(placements);
  }

  function setHistoryState(nextHistory: CommandHistory) {
    historyRef.current = nextHistory;
    setHistory(nextHistory);
  }

  function applyMovement(
    sensorId: string,
    point: NormalizedPoint,
    before: NormalizedPoint,
  ) {
    const after = applySnap(point, snapMode, {
      gridDivisions: 40,
      slots,
    });

    if (pointsEqual(before, after)) return;

    setPlacements(
      movePlacement(draftPlacementsRef.current, sensorId, after),
    );
    setHistoryState(
      pushHistory(historyRef.current, {
        type: "move-placement",
        sensorId,
        before,
        after,
      }),
    );
    setSaveMessage(null);
  }

  function handleMarkerKeyDown(
    event: ReactKeyboardEvent<HTMLButtonElement>,
    sensorId: string,
  ) {
    if (mode !== "edit") return;

    const placement = draftPlacementsRef.current.find(
      (item) => item.sensorId === sensorId,
    );
    if (!placement) return;

    const step = event.shiftKey ? 0.02 : 0.005;
    const delta = arrowDelta(event.key, step);
    if (!delta) return;

    event.preventDefault();
    applyMovement(
      sensorId,
      {
        x: placement.x + delta.x,
        y: placement.y + delta.y,
      },
      placement,
    );
  }

  function handleMarkerPointerDown(
    event: ReactPointerEvent<HTMLButtonElement>,
    sensorId: string,
  ) {
    onSelect(sensorId);
    if (mode !== "edit") return;

    const placement = draftPlacementsRef.current.find(
      (item) => item.sensorId === sensorId,
    );
    const pointerPoint = pointFromPointer(
      event.clientX,
      event.clientY,
      stageRef.current,
    );
    if (!placement || !pointerPoint) return;

    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = {
      sensorId,
      pointerId: event.pointerId,
      before: { x: placement.x, y: placement.y },
      offset: {
        x: pointerPoint.x - placement.x,
        y: pointerPoint.y - placement.y,
      },
    };
  }

  function handleMarkerPointerMove(
    event: ReactPointerEvent<HTMLButtonElement>,
  ) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId || mode !== "edit") {
      return;
    }

    const pointerPoint = pointFromPointer(
      event.clientX,
      event.clientY,
      stageRef.current,
    );
    if (!pointerPoint) return;

    event.preventDefault();
    const nextPoint = applySnap(
      {
        x: pointerPoint.x - drag.offset.x,
        y: pointerPoint.y - drag.offset.y,
      },
      snapMode,
      {
        gridDivisions: 40,
        slots,
      },
    );
    setPlacements(
      movePlacement(
        draftPlacementsRef.current,
        drag.sensorId,
        nextPoint,
      ),
    );
    setSaveMessage(null);
  }

  function finishPointerDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;

    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture?.(event.pointerId);
    }

    const placement = draftPlacementsRef.current.find(
      (item) => item.sensorId === drag.sensorId,
    );
    dragRef.current = null;
    if (!placement || pointsEqual(drag.before, placement)) return;

    setHistoryState(
      pushHistory(historyRef.current, {
        type: "move-placement",
        sensorId: drag.sensorId,
        before: drag.before,
        after: { x: placement.x, y: placement.y },
      }),
    );
  }

  function handleUndo() {
    const result = undo(
      draftPlacementsRef.current,
      historyRef.current,
    );
    setPlacements(result.placements);
    setHistoryState(result.history);
    setSaveMessage(null);
  }

  function handleRedo() {
    const result = redo(
      draftPlacementsRef.current,
      historyRef.current,
    );
    setPlacements(result.placements);
    setHistoryState(result.history);
    setSaveMessage(null);
  }

  function handleReset() {
    setPlacements(initialPlacements);
    setHistoryState(createEmptyHistory());
    setSaveMessage(null);
  }

  function handleCancel() {
    storageRef.current?.remove(equipment.id);
    setPlacements(persistedPlacements);
    setDraftImage(persistedImage);
    setHistoryState(createEmptyHistory());
    setImageError(null);
    setSaveMessage(null);
    onModeChange("view");
  }

  function handleSave() {
    storageRef.current?.remove(equipment.id);
    const placements = draftPlacementsRef.current.map((placement) => ({
      ...placement,
    }));
    setPersistedPlacements(placements);
    setPersistedImage(draftImage);
    setHistoryState(createEmptyHistory());
    setSaveMessage("Чернетку схеми збережено локально");
    onModeChange("view");
  }

  function handleRestoreRecovery() {
    if (!recoveryDraft) return;

    setPlacements(
      recoveryDraft.placements.map((placement) => ({ ...placement })),
    );
    setHistoryState(createEmptyHistory());
    setRecoveryDraft(null);
    setSaveMessage("Відновлено незавершену чернетку");
    onModeChange("edit");
  }

  function handleDiscardRecovery() {
    storageRef.current?.remove(equipment.id);
    setRecoveryDraft(null);
  }

  function handleImageChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    if (!acceptedImageTypes.has(file.type)) {
      setImageError("Підтримуються лише JPEG, PNG та WebP.");
      return;
    }

    if (file.size > maxImageSizeBytes) {
      setImageError("Розмір фото не повинен перевищувати 15 МБ.");
      return;
    }

    if (typeof URL.createObjectURL !== "function") {
      setImageError("Браузер не підтримує локальний перегляд цього файлу.");
      return;
    }

    const sourceUrl = URL.createObjectURL(file);
    objectUrlsRef.current.add(sourceUrl);
    setDraftImage({
      id: `local-${crypto.randomUUID?.() ?? Date.now()}`,
      fileName: file.name,
      mimeType: file.type as EquipmentImageMetadata["mimeType"],
      widthPx: 0,
      heightPx: 0,
      sizeBytes: file.size,
      sourceUrl,
      alt: `Фото обладнання ${equipment.name}`,
      updatedAt: new Date().toISOString(),
    });
    setImageError(null);
    setSaveMessage(null);
  }

  function handleImageLoad(
    event: React.SyntheticEvent<HTMLImageElement>,
  ) {
    const widthPx = event.currentTarget.naturalWidth;
    const heightPx = event.currentTarget.naturalHeight;

    setDraftImage((current) => {
      if (
        !current ||
        (current.widthPx === widthPx && current.heightPx === heightPx)
      ) {
        return current;
      }
      return { ...current, widthPx, heightPx };
    });
  }

  return (
    <div id="layout-editor" className="space-y-3">
      {recoveryDraft ? (
        <RecoveryBanner
          savedAt={recoveryDraft.savedAt}
          onRestore={handleRestoreRecovery}
          onDiscard={handleDiscardRecovery}
        />
      ) : null}

      <div className="rounded-2xl border border-white/[0.08] bg-[#08182e]/90 p-3">
        <div className="mb-3 flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-semibold text-white">
                Фото та схема розміщення
              </h2>
              <span
                className={clsx(
                  "rounded-full border px-2 py-1 text-[9px] font-medium",
                  mode === "edit"
                    ? "border-blue-400/30 bg-blue-500/15 text-blue-200"
                    : "border-white/[0.08] bg-white/[0.03] text-slate-400",
                )}
              >
                {mode === "edit"
                  ? "Режим редагування"
                  : "Режим перегляду"}
              </span>
              {dirty ? (
                <span className="rounded-full border border-amber-400/25 bg-amber-500/10 px-2 py-1 text-[9px] text-amber-200">
                  Незбережені зміни
                </span>
              ) : null}
            </div>
            <p className="mt-1 text-[11px] text-slate-500">
              Перетягування, клавіші зі стрілками та нормалізовані координати
              0..1
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {mode === "view" ? (
              <button
                type="button"
                onClick={() => onModeChange("edit")}
                className="inline-flex items-center gap-2 rounded-xl border border-blue-400/25 bg-blue-500/15 px-3 py-2 text-xs font-medium text-blue-200 hover:bg-blue-500/20"
              >
                <MousePointer2 className="h-3.5 w-3.5" />
                Редагувати схему
              </button>
            ) : (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  className="sr-only"
                  aria-label="Завантажити фото обладнання"
                  onChange={handleImageChange}
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-slate-300 hover:bg-white/[0.07]"
                >
                  <Upload className="h-3.5 w-3.5" />
                  {draftImage ? "Замінити фото" : "Завантажити фото"}
                </button>

                <label className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-slate-400">
                  <Grid3X3 className="h-3.5 w-3.5" />
                  <span className="sr-only">Режим прив’язки</span>
                  <select
                    aria-label="Режим прив’язки"
                    value={snapMode}
                    onChange={(event) =>
                      setSnapMode(event.target.value as SnapMode)
                    }
                    className="bg-transparent text-xs text-slate-300 outline-none"
                  >
                    <option value="none">Без прив’язки</option>
                    <option value="grid">Сітка 40 × 40</option>
                    <option value="slots">Позиції датчиків</option>
                  </select>
                </label>

                <ToolbarButton
                  label="Скасувати останню дію"
                  icon={Undo2}
                  disabled={history.past.length === 0}
                  onClick={handleUndo}
                />
                <ToolbarButton
                  label="Повторити останню дію"
                  icon={Redo2}
                  disabled={history.future.length === 0}
                  onClick={handleRedo}
                />
                <ToolbarButton
                  label="Скинути позиції"
                  icon={RotateCcw}
                  onClick={handleReset}
                />
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={!dirty}
                  className="inline-flex items-center gap-2 rounded-xl border border-emerald-400/25 bg-emerald-500/15 px-3 py-2 text-xs font-medium text-emerald-200 enabled:hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Save className="h-3.5 w-3.5" />
                  Зберегти чернетку
                </button>
                <button
                  type="button"
                  onClick={handleCancel}
                  className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.035] px-3 py-2 text-xs text-slate-300 hover:bg-white/[0.06]"
                >
                  <X className="h-3.5 w-3.5" />
                  Скасувати
                </button>
              </>
            )}
          </div>
        </div>

        {imageError ? (
          <p
            className="mb-3 rounded-xl border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-200"
            role="alert"
          >
            {imageError}
          </p>
        ) : null}
        {saveMessage ? (
          <p
            className="mb-3 inline-flex items-center gap-2 rounded-xl border border-emerald-400/20 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200"
            role="status"
          >
            <Check className="h-3.5 w-3.5" />
            {saveMessage}
          </p>
        ) : null}

        <div
          ref={stageRef}
          data-testid="equipment-image-stage"
          className={clsx(
            "relative aspect-[16/10] overflow-hidden rounded-xl border border-cyan-300/[0.1] bg-[radial-gradient(circle_at_50%_10%,rgba(34,211,238,.12),transparent_42%),linear-gradient(160deg,#0a1f37,#030b15)]",
            mode === "edit" && "ring-1 ring-blue-400/30",
          )}
        >
          {draftImage?.sourceUrl ? (
            <Image
              src={draftImage.sourceUrl}
              alt={draftImage.alt}
              fill
              unoptimized
              draggable={false}
              sizes="(min-width: 1536px) 900px, 70vw"
              className="object-cover select-none"
              onLoad={handleImageLoad}
            />
          ) : (
            <PhotoPlaceholder equipmentName={equipment.name} />
          )}

          <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,rgba(2,8,23,.08),rgba(2,8,23,.28))]" />

          {mode === "edit" && snapMode === "grid" ? (
            <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(56,189,248,.12)_1px,transparent_1px),linear-gradient(90deg,rgba(56,189,248,.12)_1px,transparent_1px)] bg-[size:2.5%_2.5%]" />
          ) : null}

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
                onKeyDown={(event) =>
                  handleMarkerKeyDown(event, sensor.id)
                }
                onPointerDown={(event) =>
                  handleMarkerPointerDown(event, sensor.id)
                }
                onPointerMove={handleMarkerPointerMove}
                onPointerUp={finishPointerDrag}
                onPointerCancel={finishPointerDrag}
                className={clsx(
                  "absolute z-10 min-w-10 -translate-x-1/2 -translate-y-1/2 rounded-md border px-1.5 py-1 text-center text-[8px] leading-tight font-bold backdrop-blur-sm transition focus:ring-2 focus:ring-cyan-300 focus:outline-none",
                  markerTone[sensor.status],
                  sensor.id === selectedId &&
                    "z-20 scale-110 ring-2 ring-white/80",
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

          <div className="absolute right-3 bottom-3 left-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-white/[0.08] bg-slate-950/70 px-3 py-2 text-[9px] text-slate-400 backdrop-blur">
            <span>
              {draftImage
                ? `${draftImage.fileName} · ${formatFileSize(draftImage.sizeBytes)}${
                    draftImage.widthPx > 0
                      ? ` · ${draftImage.widthPx}×${draftImage.heightPx}`
                      : ""
                  }`
                : "Фото ще не завантажено"}
            </span>
            <span>
              {mode === "edit"
                ? "Перетягніть маркер або використовуйте стрілки"
                : "Клікніть маркер для вибору"}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

function RecoveryBanner({
  savedAt,
  onRestore,
  onDiscard,
}: {
  savedAt: string;
  onRestore: () => void;
  onDiscard: () => void;
}) {
  return (
    <section className="flex flex-col gap-3 rounded-2xl border border-cyan-400/20 bg-cyan-400/[0.06] p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-start gap-3">
        <History className="mt-0.5 h-4 w-4 text-cyan-300" />
        <div>
          <h2 className="text-sm font-semibold text-cyan-100">
            Знайдено відновлювану чернетку
          </h2>
          <p className="mt-1 text-xs text-cyan-100/60">
            Збережено {formatRecoveryTime(savedAt)}. Відновлення не змінить
            локально збережену схему.
          </p>
        </div>
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onDiscard}
          className="rounded-lg border border-white/10 px-3 py-2 text-xs text-slate-200"
        >
          Відкинути
        </button>
        <button
          type="button"
          onClick={onRestore}
          className="rounded-lg border border-cyan-300/25 bg-cyan-400/15 px-3 py-2 text-xs font-medium text-cyan-100"
        >
          Відновити
        </button>
      </div>
    </section>
  );
}

function ToolbarButton({
  label,
  icon: Icon,
  disabled = false,
  onClick,
}: {
  label: string;
  icon: typeof Undo2;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="grid h-9 w-9 place-items-center rounded-xl border border-white/10 bg-white/[0.04] text-slate-400 enabled:hover:bg-white/[0.07] enabled:hover:text-white disabled:cursor-not-allowed disabled:opacity-35"
    >
      <Icon className="h-3.5 w-3.5" />
    </button>
  );
}

function PhotoPlaceholder({ equipmentName }: { equipmentName: string }) {
  return (
    <div className="absolute inset-0 grid place-items-center p-8 text-center">
      <div>
        <div className="mx-auto grid h-16 w-16 place-items-center rounded-2xl border border-cyan-300/15 bg-cyan-400/[0.06] text-cyan-300">
          <ImageIcon className="h-7 w-7" />
        </div>
        <p className="mt-4 text-sm font-medium text-slate-200">
          Завантажте реальне фото вітрини
        </p>
        <p className="mt-2 max-w-md text-xs leading-5 text-slate-500">
          {equipmentName}: JPEG, PNG або WebP до 15 МБ. Розміщення датчиків
          збережеться при заміні зображення.
        </p>
      </div>
    </div>
  );
}

function pointFromPointer(
  clientX: number,
  clientY: number,
  stage: HTMLDivElement | null,
): NormalizedPoint | null {
  if (!stage) return null;

  const rect = stage.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return null;

  return {
    x: (clientX - rect.left) / rect.width,
    y: (clientY - rect.top) / rect.height,
  };
}

function arrowDelta(key: string, step: number): NormalizedPoint | null {
  if (key === "ArrowLeft") return { x: -step, y: 0 };
  if (key === "ArrowRight") return { x: step, y: 0 };
  if (key === "ArrowUp") return { x: 0, y: -step };
  if (key === "ArrowDown") return { x: 0, y: step };
  return null;
}

function pointsEqual(
  first: NormalizedPoint,
  second: NormalizedPoint,
): boolean {
  return (
    Math.abs(first.x - second.x) < 0.000001 &&
    Math.abs(first.y - second.y) < 0.000001
  );
}

function placementsEqual(
  first: readonly LayoutPlacement[],
  second: readonly LayoutPlacement[],
): boolean {
  if (first.length !== second.length) return false;

  const secondById = new Map(
    second.map((placement) => [placement.sensorId, placement]),
  );
  return first.every((placement) => {
    const candidate = secondById.get(placement.sensorId);
    return candidate ? pointsEqual(placement, candidate) : false;
  });
}

function imagesEqual(
  first: EquipmentImageMetadata | null,
  second: EquipmentImageMetadata | null,
): boolean {
  if (first === second) return true;
  if (!first || !second) return false;
  return (
    first.id === second.id &&
    first.sourceUrl === second.sourceUrl &&
    first.fileName === second.fileName
  );
}

function formatTemperature(temperatureC: number | null): string {
  return temperatureC === null ? "—" : `${temperatureC.toFixed(1)}°`;
}

function formatFileSize(sizeBytes: number): string {
  if (sizeBytes <= 0) return "розмір не визначено";
  return `${(sizeBytes / 1024 / 1024).toFixed(1)} МБ`;
}

function formatRecoveryTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("uk-UA", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}
