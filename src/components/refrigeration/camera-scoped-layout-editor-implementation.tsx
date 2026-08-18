"use client";

import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Check, Grid3X3, LoaderCircle, Pencil, Save, X } from "lucide-react";

import { CameraScopedImageCanvas } from "@/components/refrigeration/camera-scoped-image-canvas";
import { RefrigerationIconButton } from "@/components/refrigeration/refrigeration-icon-button";
import { SensorPlacementManager } from "@/components/refrigeration/sensor-placement-manager";
import type { RefrigerationEquipment, RefrigerationSensor } from "@/data/refrigeration";
import type {
  AvailableSensor,
  EquipmentLifecycleRepository,
  SensorBinding,
} from "@/features/refrigeration/equipment-lifecycle-repository";
import {
  applySnap,
  type LayoutPlacement,
  type NormalizedPoint,
  type SnapMode,
} from "@/features/refrigeration/layout-editor";
import type {
  RefrigerationLayoutDraft,
  RefrigerationLayoutRepository,
} from "@/features/refrigeration/layout-repository";
import {
  buildStagedSensorConfiguration,
  configurationPayload,
  configurationsEqual,
  moveConfiguredSensor,
  type StagedSensorConfiguration,
} from "@/features/refrigeration/sensor-configuration";

export type CameraScopedLayoutEditorProps = {
  equipment: RefrigerationEquipment;
  organizationId: string | null;
  visibleSensors: RefrigerationSensor[];
  selectedId: string | null;
  mode: "view" | "edit";
  onModeChange: (mode: "view" | "edit") => void;
  onSelect: (sensorId: string) => void;
  repository: RefrigerationLayoutRepository;
  lifecycleRepository: EquipmentLifecycleRepository;
  channels: readonly AvailableSensor[];
  bindings: readonly SensorBinding[];
  onEquipmentChange: (equipment: RefrigerationEquipment) => void;
  onDraftChange: (draft: RefrigerationLayoutDraft) => void;
};

type DragState = {
  sensorId: string;
  pointerId: number;
  offset: NormalizedPoint;
};

export function CameraScopedLayoutEditor({
  equipment,
  organizationId,
  visibleSensors,
  selectedId,
  mode,
  onModeChange,
  onSelect,
  repository,
  lifecycleRepository,
  channels,
  bindings,
  onEquipmentChange,
  onDraftChange,
}: CameraScopedLayoutEditorProps) {
  const [draft, setDraft] = useState<RefrigerationLayoutDraft | null>(null);
  const [persisted, setPersisted] = useState<StagedSensorConfiguration[]>([]);
  const [configuration, setConfiguration] = useState<StagedSensorConfiguration[]>([]);
  const [editingSensorId, setEditingSensorId] = useState<string | null>(null);
  const [snapMode, setSnapMode] = useState<SnapMode>("none");
  const [state, setState] = useState<"loading" | "ready" | "saving">("loading");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<DragState | null>(null);

  useEffect(() => {
    let cancelled = false;
    void repository.getDraft(equipment.id).then((result) => {
      if (cancelled) return;
      if (!result.ok) {
        setError("Не вдалося завантажити чернетку схеми.");
        setState("ready");
        return;
      }
      const next = buildStagedSensorConfiguration(bindings, channels, result.value.placements);
      setDraft(result.value);
      setPersisted(next);
      setConfiguration(next);
      setState("ready");
    });
    return () => {
      cancelled = true;
    };
  }, [bindings, channels, equipment.id, repository]);

  const dirty = !configurationsEqual(configuration, persisted);
  const placementBySensorId = useMemo<ReadonlyMap<string, LayoutPlacement>>(
    () =>
      new Map(configuration.map((sensor) => [sensor.id, { sensorId: sensor.id, x: sensor.x, y: sensor.y }])),
    [configuration],
  );
  const snapSlots = useMemo(() => configuration.map(({ x, y }) => ({ x, y })), [configuration]);
  const viewSensorIds = useMemo(() => new Set(visibleSensors.map((sensor) => sensor.id)), [visibleSensors]);
  const canvasSensors = useMemo(
    () => (mode === "edit" ? configuration : configuration.filter((sensor) => viewSensorIds.has(sensor.id))),
    [configuration, mode, viewSensorIds],
  );

  useEffect(() => {
    if (!dirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [dirty]);

  const updateConfiguration = (next: StagedSensorConfiguration[]) => {
    setConfiguration(next);
    setError(null);
    setNotice(null);
    if (editingSensorId && !next.some((sensor) => sensor.id === editingSensorId)) {
      setEditingSensorId(null);
    }
  };

  const save = async () => {
    if (!draft || state === "saving") return;
    if (configuration.some((sensor) => !sensor.label.trim())) {
      setError("Кожен датчик повинен мати непорожній підпис маркера.");
      return;
    }
    setState("saving");
    setError(null);
    setNotice(null);
    try {
      const result = await lifecycleRepository.replaceSensorConfiguration(
        equipment.id,
        equipment.version,
        draft.version,
        configurationPayload(configuration),
      );
      const next = buildStagedSensorConfiguration(result.bindings, channels, result.draft.placements);
      setDraft(result.draft);
      setPersisted(next);
      setConfiguration(next);
      setEditingSensorId(null);
      onEquipmentChange(result.equipment);
      onDraftChange(result.draft);
      onModeChange("view");
      setNotice(`Конфігурацію ${next.length} датчиків збережено.`);
    } catch (cause) {
      const typed = cause as Error & { code?: string; actualVersion?: number };
      if (typed.code === "equipment_version_conflict" || typed.code === "layout_version_conflict") {
        setError(
          `Конфігурацію змінив інший оператор${
            typed.actualVersion ? ` · актуальна версія ${typed.actualVersion}` : ""
          }. Оновіть сторінку та повторіть дію.`,
        );
      } else {
        setError(cause instanceof Error ? cause.message : "Конфігурацію датчиків не збережено.");
      }
    } finally {
      setState("ready");
    }
  };

  const cancel = () => {
    setConfiguration(persisted.map((sensor) => ({ ...sensor, trend: [...sensor.trend] })));
    setEditingSensorId(null);
    setError(null);
    setNotice(null);
    onModeChange("view");
  };

  const editSensor = (sensorId: string) => {
    onSelect(sensorId);
    setEditingSensorId(sensorId);
  };

  const applyMovement = (sensorId: string, point: NormalizedPoint) => {
    const snapped = applySnap(point, snapMode, {
      gridDivisions: 40,
      slots: snapSlots,
    });
    updateConfiguration(moveConfiguredSensor(configuration, sensorId, snapped.x, snapped.y));
  };

  const markerKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>, sensorId: string) => {
    if (mode !== "edit") return;
    const sensor = configuration.find((candidate) => candidate.id === sensorId);
    if (!sensor) return;
    const step = event.shiftKey ? 0.02 : 0.005;
    const delta = arrowDelta(event.key, step);
    if (!delta) return;
    event.preventDefault();
    applyMovement(sensorId, {
      x: sensor.x + delta.x,
      y: sensor.y + delta.y,
    });
  };

  const markerPointerDown = (event: ReactPointerEvent<HTMLButtonElement>, sensorId: string) => {
    onSelect(sensorId);
    if (mode !== "edit") return;
    const sensor = configuration.find((candidate) => candidate.id === sensorId);
    const point = pointFromPointer(event.clientX, event.clientY, stageRef.current);
    if (!sensor || !point) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = {
      sensorId,
      pointerId: event.pointerId,
      offset: { x: point.x - sensor.x, y: point.y - sensor.y },
    };
  };

  const markerPointerMove = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId || mode !== "edit") return;
    const point = pointFromPointer(event.clientX, event.clientY, stageRef.current);
    if (!point) return;
    event.preventDefault();
    applyMovement(drag.sensorId, {
      x: point.x - drag.offset.x,
      y: point.y - drag.offset.y,
    });
  };

  const markerPointerUp = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture?.(event.pointerId);
    }
    dragRef.current = null;
  };

  if (state === "loading" || !draft) {
    return (
      <div className="rounded-2xl border border-cyan-400/15 bg-[#08182e]/90 p-6 text-sm text-cyan-200">
        <LoaderCircle className="mr-2 inline h-4 w-4 animate-spin" />
        Завантаження схеми…
      </div>
    );
  }

  return (
    <div id="layout-editor">
      <div className="rounded-2xl border border-white/[0.08] bg-[#08182e]/90 p-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <h2 className="text-xs font-semibold text-white sm:text-sm">Фото та схема розміщення</h2>
            <span className="rounded-full border border-cyan-400/20 bg-cyan-500/10 px-2 py-0.5 text-[8px] text-cyan-200">
              Чернетка v{draft.version}
            </span>
            {dirty ? (
              <span
                className="h-2 w-2 rounded-full bg-amber-400"
                title="Незбережені зміни"
                role="status"
                aria-label="Незбережені зміни"
              >
                <span className="sr-only">Незбережені зміни</span>
              </span>
            ) : null}
          </div>

          {mode === "view" ? (
            <RefrigerationIconButton
              label="Редагувати схему та датчики"
              onClick={() => onModeChange("edit")}
              tone="info"
              size="lg"
            >
              <Pencil className="h-4 w-4" />
            </RefrigerationIconButton>
          ) : (
            <div className="flex flex-wrap items-center gap-1.5">
              <label className="flex h-9 items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-2 text-slate-400">
                <Grid3X3 className="h-3.5 w-3.5" />
                <span className="sr-only">Режим прив’язки</span>
                <select
                  aria-label="Режим прив’язки"
                  value={snapMode}
                  onChange={(event) => setSnapMode(event.target.value as SnapMode)}
                  className="max-w-32 bg-transparent text-[10px] text-slate-300 outline-none"
                >
                  <option value="none">Без прив’язки</option>
                  <option value="grid">Сітка 40 × 40</option>
                  <option value="slots">Позиції датчиків</option>
                </select>
              </label>
              <RefrigerationIconButton
                label="Зберегти всі зміни"
                onClick={() => void save()}
                disabled={!dirty || state === "saving"}
                tone="success"
                size="lg"
              >
                {state === "saving" ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <Save className="h-4 w-4" />
                )}
              </RefrigerationIconButton>
              <RefrigerationIconButton label="Скасувати редагування" onClick={cancel} size="lg">
                <X className="h-4 w-4" />
              </RefrigerationIconButton>
            </div>
          )}
        </div>

        {mode === "edit" ? (
          <SensorPlacementManager
            equipment={equipment}
            organizationId={organizationId}
            totalSlots={equipment.totalSensors}
            channels={channels}
            configuration={configuration}
            editingSensorId={editingSensorId}
            onEditingSensorIdChange={setEditingSensorId}
            onConfigurationChange={updateConfiguration}
            onSelect={onSelect}
          />
        ) : null}

        {error ? (
          <p
            role="alert"
            className="mb-2 flex items-start gap-2 rounded-xl border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-200"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            {error}
          </p>
        ) : null}

        {notice ? (
          <p
            role="status"
            className="mb-2 flex items-center gap-2 rounded-xl border border-emerald-400/20 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200"
          >
            <Check className="h-4 w-4" />
            {notice}
          </p>
        ) : null}

        <CameraScopedImageCanvas
          equipmentId={equipment.id}
          equipmentName={equipment.name}
          image={draft.image ?? equipment.image}
          visibleSensors={canvasSensors}
          placementBySensorId={placementBySensorId}
          selectedId={selectedId}
          mode={mode}
          snapMode={snapMode}
          stageRef={stageRef}
          onSelect={onSelect}
          onEditSensor={editSensor}
          onMarkerKeyDown={markerKeyDown}
          onMarkerPointerDown={markerPointerDown}
          onMarkerPointerMove={markerPointerMove}
          onMarkerPointerUp={markerPointerUp}
          onImageDimensions={() => undefined}
        />
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
