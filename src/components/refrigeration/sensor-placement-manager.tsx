"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Pencil, Plus, Replace, Trash2, X } from "lucide-react";

import { RefrigerationIconButton } from "@/components/refrigeration/refrigeration-icon-button";
import { TelemetryPointSelector } from "@/components/telemetry-selection/telemetry-point-selector";
import type { RefrigerationEquipment, SensorSide } from "@/data/refrigeration";
import type { AvailableSensor } from "@/features/refrigeration/equipment-lifecycle-repository";
import {
  channelPlacementConflict,
  channelTelemetryLabel,
  removeConfiguredSensor,
  replaceConfiguredChannel,
  selectableReplacementChannels,
  sensorSlotCapacity,
  type StagedSensorConfiguration,
  unusedClimateChamberChannels,
  updateConfiguredSensor,
} from "@/features/refrigeration/sensor-configuration";
import {
  buildSensorTelemetrySelectionModel,
  selectedSensorChannelId,
  type SensorTelemetrySelectionModel,
} from "@/features/refrigeration/sensor-telemetry-selection";

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
  pendingChannelId,
  onEditingSensorIdChange,
  onPendingChannelChange,
  onConfigurationChange,
  onSelect,
}: {
  equipment: RefrigerationEquipment;
  organizationId: string | null;
  totalSlots: number;
  channels: readonly AvailableSensor[];
  configuration: readonly StagedSensorConfiguration[];
  editingSensorId: string | null;
  pendingChannelId: string | null;
  onEditingSensorIdChange: (sensorId: string | null) => void;
  onPendingChannelChange: (channelId: string | null) => void;
  onConfigurationChange: (configuration: StagedSensorConfiguration[]) => void;
  onSelect: (sensorId: string) => void;
}) {
  const effectiveTotalSlots = sensorSlotCapacity(totalSlots);
  const recoveredZeroCapacity = totalSlots <= 0;
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
  const [search, setSearch] = useState("");
  const [freshnessNow, setFreshnessNow] = useState(() => Date.now());
  const [error, setError] = useState<string | null>(null);
  const [renamingSensorId, setRenamingSensorId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [renameOriginalLabel, setRenameOriginalLabel] = useState("");
  const ignoreNextRenameBlurRef = useRef(false);
  useEffect(() => {
    if (picker?.kind !== "add") return;
    const refreshFreshness = () => setFreshnessNow(Date.now());
    refreshFreshness();
    const timer = window.setInterval(refreshFreshness, 1000);
    return () => window.clearInterval(timer);
  }, [picker?.kind]);

  const selectedSensor = configuration.find((sensor) => sensor.id === editingSensorId) ?? null;
  const pendingChannel = assignable.find((channel) => channel.channelId === pendingChannelId) ?? null;
  const filteredAssignable = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("uk-UA");
    if (!query) return assignable;
    return assignable.filter((channel) =>
      [channel.inventoryNumber, channel.channelId, channel.metric]
        .filter(Boolean)
        .some((value) => String(value).toLocaleLowerCase("uk-UA").includes(query)),
    );
  }, [assignable, search]);
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
  const replacementSelection = useMemo(
    () => buildSelectionModel(equipment, replacementEligible, organizationId),
    [organizationId, equipment, replacementEligible],
  );
  const selectForPlacement = (channel: AvailableSensor) => {
    setError(null);
    setSearch("");
    onPendingChannelChange(channel.channelId);
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

  const closeRename = () => {
    setRenamingSensorId(null);
    setRenameDraft("");
    setRenameOriginalLabel("");
  };
  const startRename = () => {
    if (!selectedSensor) return;
    ignoreNextRenameBlurRef.current = false;
    setRenameDraft(selectedSensor.label);
    setRenameOriginalLabel(selectedSensor.label);
    setRenamingSensorId(selectedSensor.id);
  };
  const stageRename = (label: string) => {
    setRenameDraft(label);
    update({ label });
  };
  const cancelRename = () => {
    ignoreNextRenameBlurRef.current = true;
    if (selectedSensor && renamingSensorId === selectedSensor.id) {
      update({ label: renameOriginalLabel });
    }
    closeRename();
  };
  const commitRename = (): boolean => {
    if (!selectedSensor || renamingSensorId !== selectedSensor.id) return true;
    const label = renameDraft.trim();
    if (!label) {
      setError("Назва маркера не може бути порожньою.");
      return false;
    }
    if (label !== selectedSensor.label) update({ label });
    closeRename();
    return true;
  };

  const replacementPickerOpen =
    picker?.kind === "replace" && selectedSensor !== null && picker.sensorId === selectedSensor.id;

  return (
    <section
      className="mb-3 rounded-2xl border border-cyan-400/15 bg-cyan-500/[0.045] p-3"
      aria-label="Редагування складу датчиків кліматичної камери"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="text-xs font-semibold text-white">Датчики на схемі</p>
            <span className="rounded-full border border-cyan-300/15 bg-cyan-400/[0.07] px-2 py-1 text-[9px] text-cyan-200">
              {configuration.length}/{effectiveTotalSlots}
            </span>
          </div>
          <p className="mt-1 text-[10px] leading-4 text-slate-500">
            Додайте канал і відразу натисніть потрібне місце на фото. Після розміщення можна обирати наступний
            канал.
          </p>
        </div>{" "}
        <button
          type="button"
          aria-label="Додати датчик"
          disabled={assignable.length === 0 || configuration.length >= effectiveTotalSlots}
          onClick={() => {
            setPicker({ kind: "add" });
            setSearch("");
            onPendingChannelChange(null);
            setError(null);
          }}
          className="inline-flex min-h-10 shrink-0 items-center justify-center gap-2 rounded-xl border border-emerald-300/20 bg-emerald-400/10 px-3 text-xs font-semibold text-emerald-100 hover:bg-emerald-400/15 focus-visible:ring-2 focus-visible:ring-emerald-300 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Plus className="h-4 w-4" />
          Датчик
          <span className="rounded-full bg-white/[0.07] px-2 py-0.5 text-[9px]">{assignable.length}</span>
        </button>
      </div>
      {picker?.kind === "add" ? (
        <div
          className="mt-3 rounded-xl border border-cyan-300/15 bg-[#07182f]/95 p-3"
          data-testid="equipment-map-quick-sensor-picker"
        >
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <input
              type="search"
              autoFocus
              aria-label="Пошук датчика"
              placeholder="Канал або № датчика"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              className={`${inputClass} min-w-0 flex-1`}
            />
            <button
              type="button"
              onClick={() => {
                setPicker(null);
                onPendingChannelChange(null);
              }}
              className="min-h-10 rounded-xl border border-white/[0.08] px-3 text-xs text-slate-400 hover:text-white"
            >
              Закрити
            </button>
          </div>
          <div className="mt-2 max-h-52 overflow-y-auto pr-1" role="group" aria-label="Доступні датчики">
            {filteredAssignable.length === 0 ? (
              <p className="px-2 py-5 text-center text-[10px] text-slate-500">
                Доступних датчиків не знайдено.
              </p>
            ) : null}{" "}
            <div className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-3">
              {filteredAssignable.map((channel) => {
                const label = quickChannelLabel(channel);
                const selected = channel.channelId === pendingChannelId;
                return (
                  <button
                    key={channel.channelId}
                    type="button"
                    aria-label={`Обрати датчик ${label}, канал ${channel.channelId}`}
                    aria-pressed={selected}
                    onClick={() => selectForPlacement(channel)}
                    className={`min-w-0 rounded-xl border px-3 py-2 text-left transition ${
                      selected
                        ? "border-cyan-300/45 bg-cyan-400/15 text-cyan-50"
                        : "border-white/[0.07] bg-white/[0.025] text-slate-300 hover:border-cyan-300/20 hover:bg-white/[0.045]"
                    }`}
                  >
                    <span className="block truncate text-xs font-semibold">{label}</span>
                    <span className="mt-0.5 block truncate text-[9px] text-slate-500">
                      {channel.channelId} · {channelTelemetryLabel(channel, freshnessNow)}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      ) : null}{" "}
      {pendingChannel ? (
        <p
          role="status"
          className="mt-3 flex items-center gap-2 rounded-xl border border-cyan-300/25 bg-cyan-400/10 px-3 py-2 text-[10px] text-cyan-100"
        >
          <span className="h-2 w-2 shrink-0 rounded-full bg-cyan-300" aria-hidden="true" />
          {quickChannelLabel(pendingChannel)} · {pendingChannel.channelId}: натисніть потрібну точку на фото.
        </p>
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
          Усі нерозміщені канали вже мають активну прив’язку до іншого обладнання.
        </p>
      ) : null}{" "}
      {conflictedUnused.length > 0 ? (
        <p className="mt-3 rounded-xl border border-slate-400/10 bg-slate-500/[0.04] px-3 py-2 text-[10px] text-slate-400">
          Недоступні через активну прив’язку:{" "}
          {conflictedUnused.map((channel) => channel.channelId).join(", ")}.
        </p>
      ) : null}
      {selectedSensor ? (
        <div className="mt-3 rounded-xl border border-blue-400/20 bg-blue-500/[0.07] p-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              {renamingSensorId === selectedSensor.id ? (
                <input
                  autoFocus
                  aria-label="Нова назва маркера"
                  value={renameDraft}
                  maxLength={128}
                  onChange={(event) => stageRename(event.target.value)}
                  onBlur={() => {
                    if (ignoreNextRenameBlurRef.current) {
                      ignoreNextRenameBlurRef.current = false;
                      return;
                    }
                    commitRename();
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      ignoreNextRenameBlurRef.current = true;
                      commitRename();
                    }
                    if (event.key === "Escape") {
                      event.preventDefault();
                      cancelRename();
                    }
                  }}
                  className={`${inputClass} max-w-md`}
                />
              ) : (
                <div className="flex min-w-0 items-center gap-2">
                  <p className="truncate text-xs font-semibold text-blue-100">{selectedSensor.label}</p>
                  <button
                    type="button"
                    aria-label={`Перейменувати маркер ${selectedSensor.label}`}
                    onClick={startRename}
                    className="grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-blue-300/15 text-blue-300 hover:bg-blue-400/10"
                  >
                    {" "}
                    <Pencil className="h-3 w-3" />
                  </button>
                </div>
              )}
              <p className="mt-1 truncate text-[9px] text-blue-200/55">
                Канал {selectedSensor.id} · {selectedSensor.metric} · {selectedSensor.unit}
              </p>
            </div>
            <RefrigerationIconButton
              label="Закрити налаштування датчика"
              onClick={() => {
                if (!commitRename()) return;
                setPicker(null);
                onEditingSensorIdChange(null);
              }}
              size="sm"
            >
              <X className="h-3.5 w-3.5" />
            </RefrigerationIconButton>
          </div>
          <details className="mt-3 rounded-xl border border-white/[0.07] bg-black/10">
            <summary className="cursor-pointer list-none px-3 py-2 text-[10px] font-semibold text-slate-300 [&::-webkit-details-marker]:hidden">
              Додаткові параметри
            </summary>
            <div className="grid gap-3 border-t border-white/[0.06] p-3 sm:grid-cols-2 xl:grid-cols-[minmax(0,1.5fr)_140px_120px_120px_auto]">
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
                  <span className="min-w-0 truncate">{selectedSensor.id}</span>
                  <Replace className="h-3.5 w-3.5 shrink-0 text-cyan-300" />
                </button>
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
                  {" "}
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
          </details>{" "}
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
      ) : null}{" "}
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

function quickChannelLabel(channel: AvailableSensor): string {
  return channel.inventoryNumber?.trim() ? `№ ${channel.inventoryNumber.trim()}` : channel.channelId;
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
