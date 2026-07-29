"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Plus, RefreshCw, Replace, Trash2 } from "lucide-react";

import { RefrigerationIconButton } from "@/components/refrigeration/refrigeration-icon-button";
import type { LayoutEditorMode } from "@/components/refrigeration/refrigeration-layout-editor";
import type { RefrigerationEquipment } from "@/data/refrigeration";
import type {
  RefrigerationLayoutDraft,
  RefrigerationLayoutRepository,
} from "@/features/refrigeration/layout-repository";
import {
  applySensorPlacementChange,
  availableSensors,
  replacementSensors,
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
  const [selectedCandidateId, setSelectedCandidateId] = useState("");
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
  const candidates = useMemo(
    () => replacementSensors(equipment.sensors, selectedAssignedId),
    [equipment.sensors, selectedAssignedId],
  );
  const candidateIsAvailable = unassigned.some(({ id }) => id === selectedCandidateId);

  const syncSelections = (nextDraft: RefrigerationLayoutDraft, preferredAssignedId?: string) => {
    const nextAssignedIds = new Set(nextDraft.placements.map(({ sensorId }) => sensorId));
    const nextAssignedId =
      preferredAssignedId && nextAssignedIds.has(preferredAssignedId)
        ? preferredAssignedId
        : (nextDraft.placements[0]?.sensorId ?? "");
    const nextCandidates = replacementSensors(equipment.sensors, nextAssignedId);

    setSelectedAssignedId(nextAssignedId);
    setSelectedCandidateId(nextCandidates[0]?.id ?? "");
    if (nextAssignedId) onSelect(nextAssignedId);
  };

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
    syncSelections(result.value, selectedAssignedId);
    setOperation("idle");
  };

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timeoutId);
    // Repository identity is stable for the workspace lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [equipment.id, repository]);

  const save = async (
    nextPlacements: RefrigerationLayoutDraft["placements"],
    message: string,
    selectedSensorId: string,
  ): Promise<boolean> => {
    if (!draft) return false;
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
      return false;
    }
    setDraft(result.value);
    syncSelections(result.value, selectedSensorId);
    setNotice(message);
    onAssignmentsChanged();
    setOperation("idle");
    return true;
  };

  const canMutate = canEdit && mode !== "edit" && operation === "idle" && Boolean(draft);

  const handleAdd = () => {
    if (!draft || !selectedCandidateId || !candidateIsAvailable) return;
    try {
      const next = applySensorPlacementChange(draft.placements, equipment.sensors, {
        type: "add",
        sensorId: selectedCandidateId,
      });
      const sensor = equipment.sensors.find(({ id }) => id === selectedCandidateId);
      void save(
        next,
        `Датчик ${sensor?.label ?? selectedCandidateId} додано на підкладку.`,
        selectedCandidateId,
      ).then((saved) => {
        if (saved) onModeChange("edit");
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не вдалося додати датчик.");
    }
  };

  const handleReplace = () => {
    if (!draft || !selectedAssignedId || !selectedCandidateId) return;
    const candidateWasAssigned = assignedIds.has(selectedCandidateId);
    try {
      const next = applySensorPlacementChange(draft.placements, equipment.sensors, {
        type: "replace",
        sensorId: selectedAssignedId,
        replacementSensorId: selectedCandidateId,
      });
      const replacement = equipment.sensors.find(({ id }) => id === selectedCandidateId);
      void save(
        next,
        candidateWasAssigned
          ? `Датчики ${replacement?.label ?? selectedCandidateId} та вибраної позиції поміняно місцями.`
          : `Датчик у вибраній позиції замінено на ${replacement?.label ?? selectedCandidateId}.`,
        selectedCandidateId,
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
      void save(
        next,
        `Датчик ${sensor?.label ?? selectedAssignedId} видалено з підкладки.`,
        nextSelectedId,
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не вдалося видалити датчик.");
    }
  };

  return (
    <section
      className="rounded-2xl border border-white/[0.08] bg-[#08182e]/90 p-4"
      aria-label="Керування датчиками на підкладці"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold text-white">Датчики на підкладці</p>
          <p className="mt-1 text-[10px] leading-4 text-slate-500">
            {assignedSensors.length} встановлено · {unassigned.length} доступно. Заміна на вже
            встановлений датчик міняє дві позиції місцями без втрати координат.
          </p>
        </div>
        <RefrigerationIconButton
          label="Оновити склад датчиків"
          onClick={() => void load()}
          disabled={operation !== "idle"}
          size="sm"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${operation === "loading" ? "animate-spin" : ""}`} />
        </RefrigerationIconButton>
      </div>

      {mode === "edit" ? (
        <p className="mt-3 rounded-xl border border-amber-400/20 bg-amber-500/10 px-3 py-2 text-[10px] text-amber-200">
          Спочатку збережіть або скасуйте переміщення маркерів. Зміна складу датчиків виконується
          атомарно на актуальній версії чернетки.
        </p>
      ) : null}
      {!canEdit ? (
        <p className="mt-3 rounded-xl border border-white/[0.07] bg-white/[0.025] px-3 py-2 text-[10px] text-slate-500">
          Поточна роль має доступ лише для перегляду.
        </p>
      ) : null}
      {error ? (
        <p
          className="mt-3 flex items-start gap-2 rounded-xl border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-[10px] text-rose-200"
          role="alert"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {error}
        </p>
      ) : null}
      {notice ? (
        <p
          className="mt-3 rounded-xl border border-emerald-400/20 bg-emerald-500/10 px-3 py-2 text-[10px] text-emerald-200"
          role="status"
        >
          {notice}
        </p>
      ) : null}

      <div className="mt-4 grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
        <label className="space-y-1.5">
          <span className="text-[9px] font-semibold tracking-wider text-slate-600 uppercase">
            Позиція на підкладці
          </span>
          <select
            aria-label="Встановлений датчик"
            value={selectedAssignedId}
            onChange={(event) => {
              const nextId = event.target.value;
              setSelectedAssignedId(nextId);
              setSelectedCandidateId(replacementSensors(equipment.sensors, nextId)[0]?.id ?? "");
              onSelect(nextId);
            }}
            className="w-full rounded-xl border border-white/[0.08] bg-[#0b1e38] px-3 py-2.5 text-xs text-slate-300 outline-none"
          >
            {assignedSensors.map((sensor) => (
              <option key={sensor.id} value={sensor.id}>
                Позиція: {sensor.label} · {sensor.name}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1.5">
          <span className="text-[9px] font-semibold tracking-wider text-slate-600 uppercase">
            Датчик зі списку
          </span>
          <select
            aria-label="Датчик зі списку"
            value={selectedCandidateId}
            disabled={candidates.length === 0}
            onChange={(event) => setSelectedCandidateId(event.target.value)}
            className="w-full rounded-xl border border-white/[0.08] bg-[#0b1e38] px-3 py-2.5 text-xs text-slate-300 outline-none disabled:opacity-40"
          >
            {candidates.map((sensor) => (
              <option key={sensor.id} value={sensor.id}>
                {assignedIds.has(sensor.id) ? "Встановлено" : "Доступно"}: {sensor.label} · {sensor.name}
              </option>
            ))}
          </select>
        </label>

        <div className="flex items-end gap-2" aria-label="Операції з датчиками">
          <RefrigerationIconButton
            label="Додати вибраний датчик на підкладку"
            onClick={handleAdd}
            disabled={!canMutate || !selectedCandidateId || !candidateIsAvailable}
            tone="success"
          >
            <Plus className="h-3.5 w-3.5" />
          </RefrigerationIconButton>
          <RefrigerationIconButton
            label="Замінити датчик у вибраній позиції"
            onClick={handleReplace}
            disabled={!canMutate || !selectedAssignedId || !selectedCandidateId}
            tone="info"
          >
            <Replace className="h-3.5 w-3.5" />
          </RefrigerationIconButton>
          <RefrigerationIconButton
            label="Видалити датчик із вибраної позиції"
            onClick={handleRemove}
            disabled={!canMutate || assignedSensors.length <= 1 || !selectedAssignedId}
            tone="danger"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </RefrigerationIconButton>
        </div>
      </div>
    </section>
  );
}
