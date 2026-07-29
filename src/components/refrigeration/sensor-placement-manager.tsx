"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Plus, RefreshCw, Replace, Trash2 } from "lucide-react";

import type { LayoutEditorMode } from "@/components/refrigeration/refrigeration-layout-editor";
import type { RefrigerationEquipment } from "@/data/refrigeration";
import type {
  RefrigerationLayoutDraft,
  RefrigerationLayoutRepository,
} from "@/features/refrigeration/layout-repository";
import {
  applySensorPlacementChange,
  availableSensors,
} from "@/features/refrigeration/sensor-placement-management";

type SensorPlacementManagerProps = {
  equipment: RefrigerationEquipment;
  repository: RefrigerationLayoutRepository;
  canEdit: boolean;
  mode: LayoutEditorMode;
  onModeChange: (mode: LayoutEditorMode) => void;
  onSelect: (sensorId: string) => void;
  onAssignmentsChanged: () => void;
};

type Operation = "loading" | "idle" | "saving";

export function SensorPlacementManager({
  equipment,
  repository,
  canEdit,
  mode,
  onModeChange,
  onSelect,
  onAssignmentsChanged,
}: SensorPlacementManagerProps) {
  const [draft, setDraft] = useState<RefrigerationLayoutDraft | null>(null);
  const [operation, setOperation] = useState<Operation>("loading");
  const [selectedAssignedId, setSelectedAssignedId] = useState("");
  const [selectedAvailableId, setSelectedAvailableId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const assignedIds = useMemo(
    () => new Set(draft?.placements.map(({ sensorId }) => sensorId) ?? []),
    [draft?.placements],
  );
  const unassigned = useMemo(
    () => availableSensors(equipment.sensors, draft?.placements ?? []),
    [draft?.placements, equipment.sensors],
  );
  const assignedSensors = useMemo(
    () => equipment.sensors.filter(({ id }) => assignedIds.has(id)),
    [assignedIds, equipment.sensors],
  );

  const load = async () => {
    setOperation("loading");
    setError(null);
    const result = await repository.getDraft(equipment.id);
    if (!result.ok) {
      setError("Не вдалося завантажити актуальний склад датчиків на підкладці.");
      setOperation("idle");
      return;
    }
    setDraft(result.value);
    setSelectedAssignedId((current) =>
      result.value.placements.some(({ sensorId }) => sensorId === current)
        ? current
        : (result.value.placements[0]?.sensorId ?? ""),
    );
    const nextAvailable = availableSensors(equipment.sensors, result.value.placements);
    setSelectedAvailableId((current) =>
      nextAvailable.some(({ id }) => id === current) ? current : (nextAvailable[0]?.id ?? ""),
    );
    setOperation("idle");
  };

  useEffect(() => {
    void load();
    // Repository identity is stable for the workspace lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [equipment.id, repository]);

  const save = async (
    nextPlacements: RefrigerationLayoutDraft["placements"],
    message: string,
    selectedSensorId: string,
  ) => {
    if (!draft) return;
    setOperation("saving");
    setError(null);
    setNotice(null);
    const result = await repository.saveDraft({
      equipmentId: equipment.id,
      expectedVersion: draft.version,
      imageId: draft.imageId,
      placements: nextPlacements,
    });
    if (!result.ok) {
      setError(
        result.error.code === "LAYOUT_VERSION_CONFLICT"
          ? "Склад датчиків змінився в іншій сесії. Оновіть чернетку та повторіть дію."
          : "Не вдалося зберегти склад датчиків на підкладці.",
      );
      setOperation("idle");
      return;
    }
    setDraft(result.value);
    setNotice(message);
    setSelectedAssignedId(selectedSensorId);
    onSelect(selectedSensorId);
    onAssignmentsChanged();
    setOperation("idle");
  };

  const canMutate = canEdit && mode !== "edit" && operation === "idle" && Boolean(draft);

  const handleAdd = () => {
    if (!draft || !selectedAvailableId) return;
    try {
      const next = applySensorPlacementChange(draft.placements, equipment.sensors, {
        type: "add",
        sensorId: selectedAvailableId,
      });
      const sensor = equipment.sensors.find(({ id }) => id === selectedAvailableId);
      void save(next, `Датчик ${sensor?.label ?? selectedAvailableId} додано на підкладку.`, selectedAvailableId).then(
        () => onModeChange("edit"),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не вдалося додати датчик.");
    }
  };

  const handleReplace = () => {
    if (!draft || !selectedAssignedId || !selectedAvailableId) return;
    try {
      const next = applySensorPlacementChange(draft.placements, equipment.sensors, {
        type: "replace",
        sensorId: selectedAssignedId,
        replacementSensorId: selectedAvailableId,
      });
      const replacement = equipment.sensors.find(({ id }) => id === selectedAvailableId);
      void save(
        next,
        `Датчик у вибраній позиції замінено на ${replacement?.label ?? selectedAvailableId}.`,
        selectedAvailableId,
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не вдалося замінити датчик.");
    }
  };

  const handleRemove = () => {
    if (!draft || !selectedAssignedId) return;
    const sensor = equipment.sensors.find(({ id }) => id === selectedAssignedId);
    if (!window.confirm(`Видалити датчик ${sensor?.label ?? selectedAssignedId} з підкладки?`)) {
      return;
    }
    try {
      const next = applySensorPlacementChange(draft.placements, equipment.sensors, {
        type: "remove",
        sensorId: selectedAssignedId,
      });
      const nextSelectedId = next[0]?.sensorId ?? "";
      void save(next, `Датчик ${sensor?.label ?? selectedAssignedId} видалено з підкладки.`, nextSelectedId);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не вдалося видалити датчик.");
    }
  };

  return (
    <section className="rounded-2xl border border-white/[0.08] bg-[#08182e]/90 p-4" aria-label="Керування датчиками на підкладці">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <p className="text-xs font-semibold text-white">Датчики на підкладці</p>
          <p className="mt-1 text-[10px] leading-4 text-slate-500">
            {assignedSensors.length} встановлено · {unassigned.length} доступно. Заміна зберігає координати позиції.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={operation !== "idle"}
          className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.035] px-3 py-2 text-[10px] text-slate-300 disabled:opacity-40"
        >
          <RefreshCw className={operation === "loading" ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />
          Оновити
        </button>
      </div>

      {mode === "edit" ? (
        <p className="mt-3 rounded-xl border border-amber-400/20 bg-amber-500/10 px-3 py-2 text-[10px] text-amber-200">
          Спочатку збережіть або скасуйте переміщення маркерів. Зміна складу датчиків виконується атомарно на актуальній версії чернетки.
        </p>
      ) : null}
      {!canEdit ? (
        <p className="mt-3 rounded-xl border border-white/[0.07] bg-white/[0.025] px-3 py-2 text-[10px] text-slate-500">
          Поточна роль має доступ лише для перегляду.
        </p>
      ) : null}
      {error ? (
        <p className="mt-3 flex items-start gap-2 rounded-xl border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-[10px] text-rose-200" role="alert">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="mt-3 rounded-xl border border-emerald-400/20 bg-emerald-500/10 px-3 py-2 text-[10px] text-emerald-200" role="status">
          {notice}
        </p>
      ) : null}

      <div className="mt-4 grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
        <label className="space-y-1.5">
          <span className="text-[9px] font-semibold tracking-wider text-slate-600 uppercase">Встановлена позиція</span>
          <select
            aria-label="Встановлений датчик"
            value={selectedAssignedId}
            onChange={(event) => {
              setSelectedAssignedId(event.target.value);
              onSelect(event.target.value);
            }}
            className="w-full rounded-xl border border-white/[0.08] bg-[#0b1e38] px-3 py-2.5 text-xs text-slate-300 outline-none"
          >
            {assignedSensors.map((sensor) => (
              <option key={sensor.id} value={sensor.id}>
                {sensor.label} · {sensor.name}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1.5">
          <span className="text-[9px] font-semibold tracking-wider text-slate-600 uppercase">Доступний датчик</span>
          <select
            aria-label="Доступний датчик"
            value={selectedAvailableId}
            disabled={unassigned.length === 0}
            onChange={(event) => setSelectedAvailableId(event.target.value)}
            className="w-full rounded-xl border border-white/[0.08] bg-[#0b1e38] px-3 py-2.5 text-xs text-slate-300 outline-none disabled:opacity-40"
          >
            {unassigned.length === 0 ? <option value="">Усі датчики встановлено</option> : null}
            {unassigned.map((sensor) => (
              <option key={sensor.id} value={sensor.id}>
                {sensor.label} · {sensor.name}
              </option>
            ))}
          </select>
        </label>

        <div className="flex flex-wrap items-end gap-2">
          <button
            type="button"
            onClick={handleAdd}
            disabled={!canMutate || !selectedAvailableId}
            className="inline-flex items-center gap-2 rounded-xl border border-emerald-400/25 bg-emerald-500/15 px-3 py-2.5 text-[10px] font-medium text-emerald-200 disabled:opacity-35"
          >
            <Plus className="h-3.5 w-3.5" />
            Додати
          </button>
          <button
            type="button"
            onClick={handleReplace}
            disabled={!canMutate || !selectedAssignedId || !selectedAvailableId}
            className="inline-flex items-center gap-2 rounded-xl border border-blue-400/25 bg-blue-500/15 px-3 py-2.5 text-[10px] font-medium text-blue-200 disabled:opacity-35"
          >
            <Replace className="h-3.5 w-3.5" />
            Замінити
          </button>
          <button
            type="button"
            onClick={handleRemove}
            disabled={!canMutate || assignedSensors.length <= 1 || !selectedAssignedId}
            className="inline-flex items-center gap-2 rounded-xl border border-rose-400/25 bg-rose-500/10 px-3 py-2.5 text-[10px] font-medium text-rose-200 disabled:opacity-35"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Видалити
          </button>
        </div>
      </div>
    </section>
  );
}
