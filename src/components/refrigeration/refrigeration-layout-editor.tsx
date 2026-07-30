"use client";

import type {
  ChangeEvent,
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
} from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { clsx } from "clsx";
import {
  AlertTriangle,
  Check,
  Grid3X3,
  History,
  LoaderCircle,
  MousePointer2,
  Redo2,
  RotateCcw,
  Save,
  Undo2,
  Upload,
  X,
} from "lucide-react";

import { RefrigerationImageCanvas } from "@/components/refrigeration/refrigeration-image-canvas";
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
import {
  createLayoutDraft,
  InMemoryRefrigerationLayoutRepository,
  type LayoutRepositoryError,
  type RefrigerationLayoutRepository,
} from "@/features/refrigeration/layout-repository";

export type LayoutEditorMode = "view" | "edit";

type VersionConflict = Extract<LayoutRepositoryError, { code: "LAYOUT_VERSION_CONFLICT" }>;

type RefrigerationLayoutEditorProps = {
  equipment: RefrigerationEquipment;
  visibleSensors: RefrigerationSensor[];
  selectedId: string | null;
  mode: LayoutEditorMode;
  onModeChange: (mode: LayoutEditorMode) => void;
  onSelect: (sensorId: string) => void;
  repository?: RefrigerationLayoutRepository;
  canEdit?: boolean;
};

type DragState = {
  sensorId: string;
  pointerId: number;
  before: NormalizedPoint;
  offset: NormalizedPoint;
};

const acceptedImageTypes = new Set(["image/jpeg", "image/png", "image/webp"]);
const maxImageSizeBytes = 1536 * 1024;
const imageLimitMessage =
  "Розмір зображення перевищує допустимі 1,5 МБ. Стисніть файл або завантажте інше зображення.";

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
  repository,
  canEdit = true,
}: RefrigerationLayoutEditorProps) {
  const initialPlacements = useMemo(
    () => equipment.sensors.map(({ id, x, y }) => ({ sensorId: id, x, y })),
    [equipment.sensors],
  );
  const allowedSensorIds = useMemo(
    () => new Set(initialPlacements.map(({ sensorId }) => sensorId)),
    [initialPlacements],
  );
  const slots = useMemo(() => initialPlacements.map(({ x, y }) => ({ x, y })), [initialPlacements]);

  const repositoryRef = useRef<RefrigerationLayoutRepository | null>(null);
  if (repositoryRef.current == null) {
    repositoryRef.current =
      repository ??
      new InMemoryRefrigerationLayoutRepository({
        drafts: [
          createLayoutDraft({
            id: `draft-${equipment.id}`,
            equipmentId: equipment.id,
            imageId: equipment.image?.id ?? null,
            placements: initialPlacements,
            createdAt: new Date().toISOString(),
          }),
        ],
      });
  }

  const [persistedPlacements, setPersistedPlacements] =
    useState<LayoutPlacement[]>(initialPlacements);
  const [draftPlacements, setDraftPlacements] = useState<LayoutPlacement[]>(initialPlacements);
  const [persistedImage, setPersistedImage] = useState<EquipmentImageMetadata | null>(
    equipment.image,
  );
  const [draftImage, setDraftImage] = useState<EquipmentImageMetadata | null>(equipment.image);
  const [draftVersion, setDraftVersion] = useState(1);
  const [history, setHistory] = useState<CommandHistory>(createEmptyHistory);
  const [snapMode, setSnapMode] = useState<SnapMode>("none");
  const [imageError, setImageError] = useState<string | null>(null);
  const [repositoryError, setRepositoryError] = useState<string | null>(null);
  const [versionConflict, setVersionConflict] = useState<VersionConflict | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [repositoryState, setRepositoryState] = useState<"loading" | "ready" | "saving">(
    "loading",
  );
  const [recoveryDraft, setRecoveryDraft] = useState<LayoutDraftPayload | null>(null);

  const stageRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragRef = useRef<DragState | null>(null);
  const draftPlacementsRef = useRef(draftPlacements);
  const historyRef = useRef(history);
  const objectUrlsRef = useRef(new Set<string>());
  const recoveryStorageRef = useRef<LayoutDraftStorage | null>(null);
  const recoveryCheckedEquipmentRef = useRef<string | null>(null);

  useEffect(() => {
    draftPlacementsRef.current = draftPlacements;
  }, [draftPlacements]);

  useEffect(() => {
    let cancelled = false;
    const activeRepository = repositoryRef.current;
    if (!activeRepository) return;

    setRepositoryState("loading");
    void activeRepository.getDraft(equipment.id).then((result) => {
      if (cancelled) return;

      if (!result.ok) {
        setRepositoryError(repositoryErrorMessage(result.error));
        setRepositoryState("ready");
        return;
      }

      const loadedPlacements = result.value.placements;
      const loadedImage = resolveImageMetadata(result.value.imageId, equipment.image, draftImage);
      setDraftVersion(result.value.version);
      setPersistedPlacements(loadedPlacements);
      setDraftPlacements(loadedPlacements);
      draftPlacementsRef.current = loadedPlacements;
      setPersistedImage(loadedImage);
      setDraftImage(loadedImage);
      setRepositoryError(null);
      setRepositoryState("ready");
    });

    return () => {
      cancelled = true;
    };
    // The repository is deliberately fixed for the component lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [equipment.id]);

  const placementDirty = !placementsEqual(draftPlacements, persistedPlacements);
  const dirty = placementDirty || !imagesEqual(draftImage, persistedImage);

  useEffect(() => {
    if (repositoryState !== "ready") return;
    if (recoveryCheckedEquipmentRef.current === equipment.id) return;

    const storage =
      recoveryStorageRef.current ?? createBrowserLayoutDraftStorage(window.sessionStorage);
    recoveryStorageRef.current = storage;

    const raw = storage.load(equipment.id);
    const parsed = parseLayoutDraft(raw, equipment.id, allowedSensorIds);
    if (raw && !parsed) {
      storage.remove(equipment.id);
    }

    if (parsed && !placementsEqual(parsed.placements, persistedPlacements)) {
      setRecoveryDraft(parsed);
    } else {
      if (parsed) storage.remove(equipment.id);
      setRecoveryDraft(null);
    }

    recoveryCheckedEquipmentRef.current = equipment.id;
  }, [allowedSensorIds, equipment.id, persistedPlacements, repositoryState]);

  useEffect(() => {
    if (repositoryState !== "ready") return;
    if (recoveryCheckedEquipmentRef.current !== equipment.id) return;
    if (recoveryDraft) return;

    const storage = recoveryStorageRef.current;
    if (!storage) return;

    if (!placementDirty) {
      storage.remove(equipment.id);
      return;
    }
    if (mode !== "edit") return;

    storage.save(
      equipment.id,
      serializeLayoutDraft(createLayoutDraftPayload(equipment.id, draftPlacements)),
    );
  }, [draftPlacements, equipment.id, mode, placementDirty, recoveryDraft, repositoryState]);

  useEffect(() => {
    if (!dirty) return;

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [dirty]);

  useEffect(
    () => () => {
      for (const url of objectUrlsRef.current) {
        URL.revokeObjectURL?.(url);
      }
    },
    [],
  );

  const placementBySensorId = useMemo(
    () => new Map(draftPlacements.map((placement) => [placement.sensorId, placement])),
    [draftPlacements],
  );

  const setPlacements = (placements: LayoutPlacement[]) => {
    draftPlacementsRef.current = placements;
    setDraftPlacements(placements);
  };

  const setHistoryState = (nextHistory: CommandHistory) => {
    historyRef.current = nextHistory;
    setHistory(nextHistory);
  };

  const clearSaveFeedback = () => {
    setSaveMessage(null);
    setRepositoryError(null);
    setVersionConflict(null);
  };

  useEffect(() => {
    if (mode !== "edit") return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || isEditableTarget(event.target)) return;
      const modifier = event.metaKey || event.ctrlKey;
      if (!modifier) return;

      const key = event.key.toLowerCase();
      const shouldRedo = key === "y" || (key === "z" && event.shiftKey);
      const shouldUndo = key === "z" && !event.shiftKey;
      if (!shouldUndo && !shouldRedo) return;

      event.preventDefault();
      const result = shouldRedo
        ? redo(draftPlacementsRef.current, historyRef.current)
        : undo(draftPlacementsRef.current, historyRef.current);
      setPlacements(result.placements);
      setHistoryState(result.history);
      clearSaveFeedback();
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [mode]);

  const applyMovement = (sensorId: string, point: NormalizedPoint, before: NormalizedPoint) => {
    const after = applySnap(point, snapMode, { gridDivisions: 40, slots });
    if (pointsEqual(before, after)) return;

    setPlacements(movePlacement(draftPlacementsRef.current, sensorId, after));
    setHistoryState(
      pushHistory(historyRef.current, {
        type: "move-placement",
        sensorId,
        before,
        after,
      }),
    );
    clearSaveFeedback();
  };

  const handleMarkerKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>, sensorId: string) => {
    if (mode !== "edit") return;

    const placement = draftPlacementsRef.current.find((item) => item.sensorId === sensorId);
    if (!placement) return;

    const step = event.shiftKey ? 0.02 : 0.005;
    const delta = arrowDelta(event.key, step);
    if (!delta) return;

    event.preventDefault();
    applyMovement(
      sensorId,
      { x: placement.x + delta.x, y: placement.y + delta.y },
      { x: placement.x, y: placement.y },
    );
  };

  const handleMarkerPointerDown = (
    event: ReactPointerEvent<HTMLButtonElement>,
    sensorId: string,
  ) => {
    onSelect(sensorId);
    if (mode !== "edit") return;

    const placement = draftPlacementsRef.current.find((item) => item.sensorId === sensorId);
    const pointerPoint = pointFromPointer(event.clientX, event.clientY, stageRef.current);
    if (!placement || !pointerPoint) return;

    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = {
      sensorId,
      pointerId: event.pointerId,
      before: { x: placement.x, y: placement.y },
      offset: { x: pointerPoint.x - placement.x, y: pointerPoint.y - placement.y },
    };
  };

  const handleMarkerPointerMove = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId || mode !== "edit") return;

    const pointerPoint = pointFromPointer(event.clientX, event.clientY, stageRef.current);
    if (!pointerPoint) return;

    event.preventDefault();
    const nextPoint = applySnap(
      { x: pointerPoint.x - drag.offset.x, y: pointerPoint.y - drag.offset.y },
      snapMode,
      { gridDivisions: 40, slots },
    );
    setPlacements(movePlacement(draftPlacementsRef.current, drag.sensorId, nextPoint));
    clearSaveFeedback();
  };

  const finishPointerDrag = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;

    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture?.(event.pointerId);
    }

    const placement = draftPlacementsRef.current.find((item) => item.sensorId === drag.sensorId);
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
  };

  const handleUndo = () => {
    const result = undo(draftPlacementsRef.current, historyRef.current);
    setPlacements(result.placements);
    setHistoryState(result.history);
    clearSaveFeedback();
  };

  const handleRedo = () => {
    const result = redo(draftPlacementsRef.current, historyRef.current);
    setPlacements(result.placements);
    setHistoryState(result.history);
    clearSaveFeedback();
  };

  const handleReset = () => {
    setPlacements(initialPlacements);
    setHistoryState(createEmptyHistory());
    clearSaveFeedback();
  };

  const clearRecoveryStorage = () => {
    recoveryStorageRef.current?.remove(equipment.id);
    setRecoveryDraft(null);
  };

  const handleRestoreRecovery = () => {
    if (!canEdit || !recoveryDraft) return;
    setPlacements(recoveryDraft.placements);
    setHistoryState(createEmptyHistory());
    setRecoveryDraft(null);
    clearSaveFeedback();
    setSaveMessage("Відновлено незбережені позиції датчиків.");
    onModeChange("edit");
  };

  const handleDiscardRecovery = () => {
    clearRecoveryStorage();
    setSaveMessage("Незбережену локальну чернетку відхилено.");
  };

  const handleCancel = () => {
    setPlacements(persistedPlacements);
    setDraftImage(persistedImage);
    setHistoryState(createEmptyHistory());
    setImageError(null);
    clearRecoveryStorage();
    clearSaveFeedback();
    onModeChange("view");
  };

  const handleSave = async () => {
    if (!canEdit) return;
    const activeRepository = repositoryRef.current;
    if (!activeRepository || repositoryState === "saving") return;

    setRepositoryState("saving");
    setSaveMessage(null);
    setRepositoryError(null);
    setVersionConflict(null);

    const localPlacements = [...draftPlacementsRef.current];
    const localImage = draftImage;
    const result = await activeRepository.saveDraft({
      equipmentId: equipment.id,
      expectedVersion: draftVersion,
      imageId: localImage?.id ?? null,
      placements: localPlacements,
    });

    if (!result.ok) {
      if (result.error.code === "LAYOUT_VERSION_CONFLICT") {
        setVersionConflict(result.error);
      } else {
        setRepositoryError(repositoryErrorMessage(result.error));
      }
      setRepositoryState("ready");
      return;
    }

    setDraftVersion(result.value.version);
    setPersistedPlacements(result.value.placements);
    setPlacements(result.value.placements);
    setPersistedImage(localImage);
    setHistoryState(createEmptyHistory());
    clearRecoveryStorage();
    setSaveMessage(`Чернетку схеми збережено · версія ${result.value.version}`);
    setRepositoryState("ready");
    onModeChange("view");
  };

  const handleImageChange = (event: ChangeEvent<HTMLInputElement>) => {
    if (!canEdit) return;
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    if (!acceptedImageTypes.has(file.type)) {
      setImageError("Підтримуються лише JPEG, PNG та WebP.");
      return;
    }

    if (file.size > maxImageSizeBytes) {
      setImageError(imageLimitMessage);
      return;
    }

    if (typeof URL.createObjectURL !== "function") {
      setImageError("Браузер не підтримує локальний перегляд цього файлу.");
      return;
    }

    const sourceUrl = URL.createObjectURL(file);
    objectUrlsRef.current.add(sourceUrl);
    setDraftImage({
      id: `local-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`,
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
    clearSaveFeedback();
  };

  const handleImageDimensions = (widthPx: number, heightPx: number) => {
    setDraftImage((current) => {
      if (!current || (current.widthPx === widthPx && current.heightPx === heightPx)) {
        return current;
      }
      return { ...current, widthPx, heightPx };
    });
  };

  return (
    <div id="layout-editor" className="space-y-3">
      <div className="rounded-2xl border border-white/[0.08] bg-[#08182e]/90 p-3">
        <div className="mb-3 flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-semibold text-white">Фото та схема розміщення</h2>
              <StatusBadge mode={mode} />
              <span className="rounded-full border border-cyan-400/20 bg-cyan-500/10 px-2 py-1 text-[9px] text-cyan-200">
                Чернетка v{draftVersion}
              </span>
              {dirty ? (
                <span className="rounded-full border border-amber-400/25 bg-amber-500/10 px-2 py-1 text-[9px] text-amber-200">
                  Незбережені зміни
                </span>
              ) : null}
            </div>
            <p className="mt-1 text-[11px] text-slate-500">
              Перетягування, клавіші зі стрілками та нормалізовані координати 0..1
            </p>
          </div>

          <EditorToolbar
            mode={mode}
            dirty={dirty}
            saving={repositoryState === "saving"}
            loading={repositoryState === "loading"}
            hasImage={Boolean(draftImage)}
            snapMode={snapMode}
            canUndo={history.past.length > 0}
            canRedo={history.future.length > 0}
            fileInputRef={fileInputRef}
            onModeChange={onModeChange}
            onImageChange={handleImageChange}
            onOpenImagePicker={() => fileInputRef.current?.click()}
            onSnapModeChange={setSnapMode}
            onUndo={handleUndo}
            onRedo={handleRedo}
            onReset={handleReset}
            onSave={() => void handleSave()}
            onCancel={handleCancel}
            canEdit={canEdit}
          />
        </div>

        {repositoryState === "loading" ? (
          <p
            className="mb-3 inline-flex items-center gap-2 rounded-xl border border-cyan-400/20 bg-cyan-500/10 px-3 py-2 text-xs text-cyan-200"
            role="status"
          >
            <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
            Завантаження чернетки схеми…
          </p>
        ) : null}
        {canEdit && recoveryDraft ? (
          <RecoveryBanner
            savedAt={recoveryDraft.savedAt}
            onRestore={handleRestoreRecovery}
            onDiscard={handleDiscardRecovery}
          />
        ) : null}
        {imageError ? <Alert tone="error">{imageError}</Alert> : null}
        {repositoryError ? <Alert tone="error">{repositoryError}</Alert> : null}
        {versionConflict ? (
          <div
            className="mb-3 rounded-xl border border-amber-400/25 bg-amber-500/10 px-3 py-3 text-xs text-amber-100"
            role="alert"
          >
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="font-semibold">Конфлікт версій схеми</p>
                <p className="mt-1 leading-5 text-amber-100/80">
                  Ви редагували версію {versionConflict.expectedVersion}, але в сховищі вже є
                  версія {versionConflict.actualVersion}. Локальні позиції та фото не втрачено.
                </p>
                <button
                  type="button"
                  onClick={() => setVersionConflict(null)}
                  className="mt-2 rounded-lg border border-amber-300/25 bg-amber-300/10 px-2.5 py-1.5 text-[10px] font-medium text-amber-100 hover:bg-amber-300/15"
                >
                  Продовжити редагування
                </button>
              </div>
            </div>
          </div>
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

        <RefrigerationImageCanvas
          equipmentId={equipment.id}
          equipmentName={equipment.name}
          image={draftImage}
          visibleSensors={visibleSensors}
          placementBySensorId={placementBySensorId}
          selectedId={selectedId}
          mode={mode}
          snapMode={snapMode}
          stageRef={stageRef}
          onSelect={onSelect}
          onMarkerKeyDown={handleMarkerKeyDown}
          onMarkerPointerDown={handleMarkerPointerDown}
          onMarkerPointerMove={handleMarkerPointerMove}
          onMarkerPointerUp={finishPointerDrag}
          onImageDimensions={handleImageDimensions}
        />
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
    <div
      className="mb-3 rounded-xl border border-cyan-400/25 bg-cyan-500/10 px-3 py-3 text-xs text-cyan-100"
      role="alert"
      aria-live="polite"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-start gap-2">
          <History className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-semibold">Знайдено незбережену чернетку позицій</p>
            <p className="mt-1 leading-5 text-cyan-100/75">
              Збережено локально {formatRecoveryTimestamp(savedAt)}. Фото та серверна версія не
              змінювалися.
            </p>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <button
            type="button"
            onClick={onRestore}
            className="rounded-lg border border-cyan-300/30 bg-cyan-300/15 px-2.5 py-1.5 text-[10px] font-semibold text-cyan-50 hover:bg-cyan-300/20"
          >
            Відновити
          </button>
          <button
            type="button"
            onClick={onDiscard}
            className="rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[10px] font-medium text-slate-300 hover:bg-white/[0.07]"
          >
            Відхилити
          </button>
        </div>
      </div>
    </div>
  );
}

function EditorToolbar({
  mode,
  dirty,
  saving,
  loading,
  hasImage,
  snapMode,
  canUndo,
  canRedo,
  fileInputRef,
  onModeChange,
  onImageChange,
  onOpenImagePicker,
  onSnapModeChange,
  onUndo,
  onRedo,
  onReset,
  onSave,
  onCancel,
  canEdit,
}: {
  mode: LayoutEditorMode;
  dirty: boolean;
  saving: boolean;
  loading: boolean;
  hasImage: boolean;
  snapMode: SnapMode;
  canUndo: boolean;
  canRedo: boolean;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  onModeChange: (mode: LayoutEditorMode) => void;
  onImageChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onOpenImagePicker: () => void;
  onSnapModeChange: (mode: SnapMode) => void;
  onUndo: () => void;
  onRedo: () => void;
  onReset: () => void;
  onSave: () => void;
  onCancel: () => void;
  canEdit: boolean;
}) {
  if (mode === "view") {
    if (!canEdit) return null;
    return (
      <button
        type="button"
        onClick={() => onModeChange("edit")}
        className="inline-flex items-center gap-2 rounded-xl border border-blue-400/25 bg-blue-500/15 px-3 py-2 text-xs font-medium text-blue-200 hover:bg-blue-500/20"
      >
        <MousePointer2 className="h-3.5 w-3.5" />
        Редагувати схему
      </button>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        ref={fileInputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        className="sr-only"
        aria-label="Завантажити фото обладнання"
        onChange={onImageChange}
      />
      <button
        type="button"
        onClick={onOpenImagePicker}
        className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-slate-300 hover:bg-white/[0.07]"
      >
        <Upload className="h-3.5 w-3.5" />
        {hasImage ? "Замінити фото" : "Завантажити фото"}
      </button>

      <label className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-slate-400">
        <Grid3X3 className="h-3.5 w-3.5" />
        <span className="sr-only">Режим прив’язки</span>
        <select
          aria-label="Режим прив’язки"
          value={snapMode}
          onChange={(event) => onSnapModeChange(event.target.value as SnapMode)}
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
        disabled={!canUndo}
        onClick={onUndo}
      />
      <ToolbarButton
        label="Повторити останню дію"
        icon={Redo2}
        disabled={!canRedo}
        onClick={onRedo}
      />
      <ToolbarButton label="Скинути позиції" icon={RotateCcw} onClick={onReset} />
      <button
        type="button"
        onClick={onSave}
        disabled={!dirty || saving || loading}
        className="inline-flex items-center gap-2 rounded-xl border border-emerald-400/25 bg-emerald-500/15 px-3 py-2 text-xs font-medium text-emerald-200 enabled:hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {saving ? (
          <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Save className="h-3.5 w-3.5" />
        )}
        {saving ? "Збереження…" : "Зберегти чернетку"}
      </button>
      <button
        type="button"
        onClick={onCancel}
        className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.035] px-3 py-2 text-xs text-slate-300 hover:bg-white/[0.06]"
      >
        <X className="h-3.5 w-3.5" />
        Скасувати
      </button>
    </div>
  );
}

function StatusBadge({ mode }: { mode: LayoutEditorMode }) {
  return (
    <span
      className={clsx(
        "rounded-full border px-2 py-1 text-[9px] font-medium",
        mode === "edit"
          ? "border-blue-400/30 bg-blue-500/15 text-blue-200"
          : "border-white/[0.08] bg-white/[0.03] text-slate-400",
      )}
    >
      {mode === "edit" ? "Режим редагування" : "Режим перегляду"}
    </span>
  );
}

function Alert({ children, tone }: { children: React.ReactNode; tone: "error" }) {
  return (
    <p
      className={clsx(
        "mb-3 rounded-xl border px-3 py-2 text-xs",
        tone === "error" && "border-rose-400/20 bg-rose-500/10 text-rose-200",
      )}
      role="alert"
    >
      {children}
    </p>
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

function pointFromPointer(
  clientX: number,
  clientY: number,
  stage: HTMLDivElement | null,
): NormalizedPoint | null {
  if (!stage) return null;
  const rect = stage.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return null;
  return { x: (clientX - rect.left) / rect.width, y: (clientY - rect.top) / rect.height };
}

function arrowDelta(key: string, step: number): NormalizedPoint | null {
  if (key === "ArrowLeft") return { x: -step, y: 0 };
  if (key === "ArrowRight") return { x: step, y: 0 };
  if (key === "ArrowUp") return { x: 0, y: -step };
  if (key === "ArrowDown") return { x: 0, y: step };
  return null;
}

function pointsEqual(first: NormalizedPoint, second: NormalizedPoint): boolean {
  return Math.abs(first.x - second.x) < 0.000001 && Math.abs(first.y - second.y) < 0.000001;
}

function placementsEqual(
  first: readonly LayoutPlacement[],
  second: readonly LayoutPlacement[],
): boolean {
  if (first.length !== second.length) return false;
  const secondById = new Map(second.map((placement) => [placement.sensorId, placement]));
  return first.every((placement) => {
    const candidate = secondById.get(placement.sensorId);
    return candidate ? pointsEqual(placement, candidate) : false;
  });
}

function imagesEqual(
  first: EquipmentImageMetadata | null,
  second: EquipmentImageMetadata | null,
): boolean {
  if (first === null || second === null) return first === second;
  return first.id === second.id && first.sourceUrl === second.sourceUrl;
}

function resolveImageMetadata(
  imageId: string | null,
  equipmentImage: EquipmentImageMetadata | null,
  localImage: EquipmentImageMetadata | null,
): EquipmentImageMetadata | null {
  if (!imageId) return null;
  if (localImage?.id === imageId) return localImage;
  if (equipmentImage?.id === imageId) return equipmentImage;
  return null;
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.tagName === "SELECT"
  );
}

function formatRecoveryTimestamp(value: string): string {
  try {
    return new Intl.DateTimeFormat("uk-UA", {
      dateStyle: "short",
      timeStyle: "short",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

function repositoryErrorMessage(error: LayoutRepositoryError): string {
  if (error.code === "LAYOUT_NOT_FOUND") return "Чернетку схеми не знайдено.";
  if (error.code === "LAYOUT_VALIDATION_FAILED") {
    return `Схема не пройшла перевірку: ${error.issues.map((issue) => issue.message).join(" ")}`;
  }
  if (error.code === "LAYOUT_REVISION_NOT_FOUND") {
    return "Вибрану ревізію схеми не знайдено.";
  }
  return "Схема була змінена іншим користувачем.";
}
