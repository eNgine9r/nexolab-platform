"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, Pencil, Plus, Replace, Trash2, X } from "lucide-react";

import { RefrigerationIconButton } from "@/components/refrigeration/refrigeration-icon-button";
import { TelemetryPointSelector } from "@/components/telemetry-selection/telemetry-point-selector";
import type { RefrigerationEquipment, SensorSide } from "@/data/refrigeration";
import type { AvailableSensor } from "@/features/refrigeration/equipment-lifecycle-repository";
import {
  addChannelToConfiguration,
  channelPlacementConflict,
  removeConfiguredSensor,
  replaceConfiguredChannel,
  selectableReplacementChannels,
  type StagedSensorConfiguration,
  unusedClimateChamberChannels,
  updateConfiguredSensor,
} from "@/features/refrigeration/sensor-configuration";
import {
  buildSensorTelemetrySelectionModel,
  selectedSensorChannelId,
  type SensorTelemetrySelectionModel,
} from "@/features/refrigeration/sensor-telemetry-selection";
import { getSecurityCredentials } from "@/features/security/security-session";

const DEFAULT_SENSOR_SLOT_CAPACITY = 48;
const MAX_SENSOR_SLOT_CAPACITY = 48;
const DEMO_SELECTION_SCOPE = "demo:equipment-map";

type PickerState = { kind: "add" } | { kind: "replace"; sensorId: string } | null;
type SelectionModelResult = {
  model: SensorTelemetrySelectionModel | null;
  error: string | null;
};

export function SensorPlacementManager({
  equipment,
  organizationId,
  totalSlots,
  channels,
  configuration,
  editingSensorId,
  onEditingSensorIdChange,
  onConfigurationChange,
  onSelect,
}: {
  equipment: RefrigerationEquipment;
  organizationId?: string | null;
  totalSlots: number;
  channels: readonly AvailableSensor[];
  configuration: readonly StagedSensorConfiguration[];
  editingSensorId: string | null;
  onEditingSensorIdChange: (sensorId: string | null) => void;
  onConfigurationChange: (configuration: StagedSensorConfiguration[]) => void;
  onSelect: (sensorId: string) => void;
}) {
  const effectiveTotalSlots = sensorSlotCapacity(totalSlots);
  const recoveredZeroCapacity = totalSlots <= 0;
  const credentialOrganizationId = getSecurityCredentials().organizationId;
  const effectiveOrganizationId =
    organizationId ??
    credentialOrganizationId ??
    (process.env.NEXT_PUBLIC_NEXOLAB_DATA_MODE === "live" ? null : DEMO_SELECTION_SCOPE);
  const unused = useMemo(
    () => unusedClimateChamberChannels(channels, configuration),
    [channels, configuration],
  );
  const assignable = useMemo(
    () => unused.filter((channel) => channelPlacementConflict(channel, equipment.id) === null),
    [equipment.id, unused],
  );
  const conflictedUnused = useMemo(
    () => unused.filter((channel) => channelPlacementConflict(channel, equipment.id) !== null),
    [equipment.id, unused],
  );
  const [picker, setPicker] = useState<PickerState>(null);
  const [error, setError] = useState<string | null>(null);
  const selectedSensor = configuration.find((sensor) => sensor.id === editingSensorId) ?? null;
  const replacementChannels = useMemo(
    () => (selectedSensor ? selectableReplacementChannels(channels, configuration, selectedSensor.id) : []),
    [channels, configuration, selectedSensor],
  );
  const replacementEligible = useMemo(
    () =>
      selectedSensor
        ? replacementChannels.filter(
            (channel) =>
              channel.channelId === selectedSensor.id ||
              channelPlacementConflict(channel, equipment.id) === null,
          )
        : [],
    [equipment.id, replacementChannels, selectedSensor],
  );
  const conflictedReplacements = useMemo(
    () =>
      selectedSensor
        ? replacementChannels.filter(
            (channel) =>
              channel.channelId !== selectedSensor.id &&
              channelPlacementConflict(channel, equipment.id) !== null,
          )
        : [],
    [equipment.id, replacementChannels, selectedSensor],
  );
  const addSelection = useMemo(
    () => buildSelectionModel(equipment, assignable, effectiveOrganizationId),
    [assignable, effectiveOrganizationId, equipment],
  );
  const replacementSelection = useMemo(
    () => buildSelectionModel(equipment, replacementEligible, effectiveOrganizationId),
    [effectiveOrganizationId, equipment, replacementEligible],
  );

  const add = (pointKeys: string[]) => {
    const model = addSelection.model;
    const channelId = model ? selectedSensorChannelId(model, pointKeys) : null;
    const channel = channelId ? assignable.find((candidate) => candidate.channelId === channelId) : undefined;
    if (!channel) {
      setError("Оберіть рівно один доступний канал перед підтвердженням.");
      return;
    }
    setError(null);
    try {
      const next = addChannelToConfiguration(configuration, channel, effectiveTotalSlots, equipment.id);
      onConfigurationChange(next);
      onSelect(channel.channelId);
      onEditingSensorIdChange(channel.channelId);
      setPicker(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не вдалося додати датчик.");
    }
  };

  const replace = (pointKeys: string[]) => {
    if (!selectedSensor) return;
    const model = replacementSelection.model;
    const channelId = model ? selectedSensorChannelId(model, pointKeys) : null;
    const channel = channelId
      ? replacementEligible.find((candidate) => candidate.channelId === channelId)
      : undefined;
    if (!channel) {
      setError("Оберіть рівно один канал заміни перед підтвердженням.");
      return;
    }
    if (channel.channelId === selectedSensor.id) {
      setError(null);
      setPicker(null);
      return;
    }
    setError(null);
    try {
      const next = replaceConfiguredChannel(configuration, selectedSensor.id, channel, equipment.id);
      onConfigurationChange(next);
      onSelect(channel.channelId);
      onEditingSensorIdChange(channel.channelId);
      setPicker(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не вдалося замінити датчик.");
    }
  };

  const update = (
    patch: Partial<Pick<StagedSensorConfiguration, "label" | "side" | "shelf" | "position">>,
  ) => {
    if (!selectedSensor) return;
    setError(null);
    try {
      onConfigurationChange(updateConfiguredSensor(configuration, selectedSensor.id, patch));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не вдалося змінити параметри датчика.");
    }
  };

  const remove = () => {
    if (!selectedSensor) return;
    if (!window.confirm(`Видалити датчик ${selectedSensor.label} з підкладки?`)) return;
    onConfigurationChange(removeConfiguredSensor(configuration, selectedSensor.id));
    onEditingSensorIdChange(null);
    setPicker(null);
    setError(null);
  };

  const replacementPickerOpen =
    picker?.kind === "replace" && selectedSensor !== null && picker.sensorId === selectedSensor.id;

  return (
    <section
      className="mb-3 rounded-2xl border border-cyan-400/15 bg-cyan-500/[0.045] p-3"
      aria-label="Редагування складу датчиків кліматичної камери"
    >
      <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="text-xs font-semibold text-white">Датчики кліматичної камери</p>
            <span className="rounded-full border border-cyan-300/15 bg-cyan-400/[0.07] px-2 py-1 text-[9px] text-cyan-200">
              {configuration.length}/{effectiveTotalSlots}
            </span>
          </div>
          <p className="mt-1 text-[10px] leading-4 text-slate-500">
            У виборі залишаються всі конфігуровані канали камери: Live, Stale, Offline, без даних і
            заплановані. Телеметрія не визначає доступність каналу для проєктування схеми.
          </p>
        </div>

        <button
          type="button"
          aria-label="Вибрати датчик або прилад для додавання"
          disabled={
            assignable.length === 0 ||
            configuration.length >= effectiveTotalSlots ||
            addSelection.model === null
          }
          onClick={() => {
            setPicker({ kind: "add" });
            setError(null);
          }}
          className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-emerald-300/20 bg-emerald-400/10 px-3 text-xs font-semibold text-emerald-100 hover:bg-emerald-400/15 focus-visible:ring-2 focus-visible:ring-emerald-300 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Plus className="h-4 w-4" />
          Обрати канал
          <span className="rounded-full bg-white/[0.07] px-2 py-0.5 text-[9px]">{assignable.length}</span>
        </button>
      </div>

      {addSelection.error && channels.length > 0 ? (
        <p className="mt-3 flex items-start gap-2 rounded-xl border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-[10px] text-rose-200">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {addSelection.error}
        </p>
      ) : null}

      {picker?.kind === "add" && addSelection.model && addSelection.model.hierarchy.leafCount > 0 ? (
        <div className="mt-3" data-testid="equipment-map-add-telemetry-selector">
          <TelemetryPointSelector
            hierarchy={addSelection.model.hierarchy}
            value={[]}
            maxSelection={1}
            maxVisibleNodes={300}
            title="Додати точку на схему"
            onCancel={() => setPicker(null)}
            onConfirm={add}
          />
        </div>
      ) : null}

      {recoveredZeroCapacity ? (
        <p className="mt-3 flex items-start gap-2 rounded-xl border border-amber-400/20 bg-amber-500/10 px-3 py-2 text-[10px] text-amber-100">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />У паспорті обладнання місткість датчиків
          була задана як 0. Для робочої схеми автоматично застосовано стандартну місткість 48 слотів.
        </p>
      ) : null}

      {channels.length === 0 ? (
        <p className="mt-3 flex items-start gap-2 rounded-xl border border-amber-400/20 bg-amber-500/10 px-3 py-2 text-[10px] text-amber-200">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          Для вибраної кліматичної камери не знайдено конфігурованих каналів. Перевірте каталог організації,
          прив’язку камери до RS-485 bus і виконання climate-catalog seed.
        </p>
      ) : null}

      {channels.length > 0 && assignable.length === 0 && configuration.length < effectiveTotalSlots ? (
        <p className="mt-3 flex items-start gap-2 rounded-xl border border-slate-400/15 bg-slate-500/[0.06] px-3 py-2 text-[10px] text-slate-300">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          Усі нерозміщені канали вже мають активну прив’язку до іншого обладнання. Вони недоступні для
          подвійного розміщення.
        </p>
      ) : null}

      {conflictedUnused.length > 0 ? (
        <p className="mt-3 rounded-xl border border-slate-400/10 bg-slate-500/[0.04] px-3 py-2 text-[10px] text-slate-400">
          Недоступні через активну прив’язку:{" "}
          {conflictedUnused.map((channel) => channel.channelId).join(", ")}.
        </p>
      ) : null}

      {selectedSensor ? (
        <div className="mt-3 rounded-xl border border-blue-400/20 bg-blue-500/[0.07] p-3">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-2">
              <Pencil className="h-3.5 w-3.5 text-blue-300" />
              <div>
                <p className="text-xs font-semibold text-blue-100">
                  {selectedSensor.label} · {selectedSensor.id}
                </p>
                <p className="mt-1 text-[9px] text-blue-200/55">Незбережена конфігурація</p>
              </div>
            </div>
            <RefrigerationIconButton
              label="Закрити налаштування датчика"
              onClick={() => {
                setPicker(null);
                onEditingSensorIdChange(null);
              }}
              size="sm"
            >
              <X className="h-3.5 w-3.5" />
            </RefrigerationIconButton>
          </div>

          <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_140px_120px_120px_auto]">
            <EditorField label="Канал вимірювання">
              <button
                type="button"
                aria-label="Вибрати інший канал вимірювання"
                disabled={replacementSelection.model === null || replacementEligible.length === 0}
                onClick={() => {
                  setPicker({ kind: "replace", sensorId: selectedSensor.id });
                  setError(null);
                }}
                className={`${inputClass} flex min-h-10 items-center justify-between gap-2 text-left disabled:cursor-not-allowed disabled:opacity-40`}
              >
                <span className="min-w-0 truncate">
                  {selectedSensor.id} · {selectedSensor.metric} · {selectedSensor.unit}
                </span>
                <Replace className="h-3.5 w-3.5 shrink-0 text-cyan-300" />
              </button>
            </EditorField>
            <EditorField label="Підпис маркера">
              <input
                aria-label="Підпис датчика"
                value={selectedSensor.label}
                maxLength={128}
                onChange={(event) => update({ label: event.target.value })}
                className={inputClass}
              />
            </EditorField>
            <EditorField label="Фронт">
              <select
                aria-label="Фронт датчика"
                value={selectedSensor.side}
                onChange={(event) => update({ side: event.target.value as SensorSide })}
                className={inputClass}
              >
                <option value="front">Передній</option>
                <option value="rear">Задній</option>
              </select>
            </EditorField>
            <EditorField label="Полиця">
              <select
                aria-label="Полиця датчика"
                value={selectedSensor.shelf}
                onChange={(event) => update({ shelf: Number(event.target.value) })}
                className={inputClass}
              >
                {[1, 2, 3, 4].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </EditorField>
            <EditorField label="Позиція">
              <select
                aria-label="Позиція датчика"
                value={selectedSensor.position}
                onChange={(event) => update({ position: Number(event.target.value) })}
                className={inputClass}
              >
                {[1, 2, 3, 4, 5, 6].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </EditorField>
            <div className="flex items-end">
              <RefrigerationIconButton label="Видалити датчик з підкладки" onClick={remove} tone="danger">
                <Trash2 className="h-3.5 w-3.5" />
              </RefrigerationIconButton>
            </div>
          </div>

          {replacementSelection.error ? (
            <p className="mt-3 flex items-start gap-2 rounded-xl border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-[10px] text-rose-200">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {replacementSelection.error}
            </p>
          ) : null}

          {conflictedReplacements.length > 0 ? (
            <p className="mt-3 text-[10px] text-slate-500">
              Не можна використати через інше обладнання:{" "}
              {conflictedReplacements.map((channel) => channel.channelId).join(", ")}.
            </p>
          ) : null}

          {replacementPickerOpen && replacementSelection.model ? (
            <div className="mt-3" data-testid="equipment-map-replace-telemetry-selector">
              <TelemetryPointSelector
                hierarchy={replacementSelection.model.hierarchy}
                value={[]}
                maxSelection={1}
                maxVisibleNodes={300}
                title={`Замінити канал ${selectedSensor.id}`}
                onCancel={() => setPicker(null)}
                onConfirm={replace}
              />
            </div>
          ) : null}
        </div>
      ) : null}

      {error ? (
        <p
          role="alert"
          className="mt-3 flex items-start gap-2 rounded-xl border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-[10px] text-rose-200"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {error}
        </p>
      ) : null}
    </section>
  );
}

export function sensorSlotCapacity(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return DEFAULT_SENSOR_SLOT_CAPACITY;
  return Math.min(MAX_SENSOR_SLOT_CAPACITY, Math.max(1, Math.trunc(value)));
}

function buildSelectionModel(
  equipment: RefrigerationEquipment,
  channels: readonly AvailableSensor[],
  organizationId: string | null,
): SelectionModelResult {
  if (!organizationId?.trim()) {
    return {
      model: null,
      error: "Контекст організації недоступний. Вибір точки телеметрії заблоковано.",
    };
  }
  try {
    return {
      model: buildSensorTelemetrySelectionModel({ equipment, channels, organizationId }),
      error: null,
    };
  } catch (cause) {
    return {
      model: null,
      error: cause instanceof Error ? cause.message : "Не вдалося побудувати каталог точок телеметрії.",
    };
  }
}

function EditorField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <span className="block text-[9px] font-semibold tracking-wider text-slate-600 uppercase">{label}</span>
      {children}
    </div>
  );
}

const inputClass =
  "w-full rounded-xl border border-white/[0.08] bg-[#0b1e38] px-3 py-2.5 text-xs text-slate-200 outline-none focus:border-cyan-300/35 focus:ring-2 focus:ring-cyan-300/10";
