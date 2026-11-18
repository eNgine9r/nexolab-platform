"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Pencil, Plus, Replace, Trash2, Undo2, X } from "lucide-react";

import { RefrigerationIconButton } from "@/components/refrigeration/refrigeration-icon-button";
import type { RefrigerationEquipment, SensorSide } from "@/data/refrigeration";
import type { AvailableSensor } from "@/features/refrigeration/equipment-lifecycle-repository";
import {
  channelPlacementConflict,
  channelTelemetryLabel,
  removeConfiguredSensor,
  restoreRemovedConfiguredSensor,
  replaceConfiguredChannel,
  selectableReplacementChannels,
  sensorSlotCapacity,
  type StagedSensorConfiguration,
  unusedClimateChamberChannels,
  updateConfiguredSensor,
} from "@/features/refrigeration/sensor-configuration";
type PickerState = { kind: "add" } | { kind: "replace"; sensorId: string } | null;

export function SensorPlacementManager(props: Parameters<typeof SensorPlacementManagerSession>[0]) {
  return (
    <SensorPlacementManagerSession
      key={JSON.stringify([props.organizationId, props.equipment.id])}
      {...props}
    />
  );
}

function SensorPlacementManagerSession({
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
  onRefreshChannels,
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
  onRefreshChannels?: () => void | Promise<void>;
}) {
  const effectiveTotalSlots = sensorSlotCapacity(totalSlots);
  const recoveredZeroCapacity = totalSlots <= 0;
  const unused = useMemo(
    () =>
      unusedClimateChamberChannels(channels, configuration).filter((channel) => channel.selectable !== false),
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
  const [removedSensor, setRemovedSensor] = useState<StagedSensorConfiguration | null>(null);
  const undoRemovalRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (removedSensor) undoRemovalRef.current?.focus();
  }, [removedSensor]);
  const [picker, setPicker] = useState<PickerState>(null);
  const [search, setSearch] = useState("");
  const [freshnessNow, setFreshnessNow] = useState(() => Date.now());
  const [error, setError] = useState<string | null>(null);
  const [renamingSensorId, setRenamingSensorId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [renameOriginalLabel, setRenameOriginalLabel] = useState("");
  const [renameOriginalAutomaticLabelSource, setRenameOriginalAutomaticLabelSource] =
    useState<StagedSensorConfiguration["automaticLabelSource"]>(undefined);
  const ignoreNextRenameBlurRef = useRef(false);
  useEffect(() => {
    if (!picker) return;
    let refreshInFlight = false;
    const refreshFreshness = () => setFreshnessNow(Date.now());
    const refreshSamples = () => {
      if (!onRefreshChannels || refreshInFlight) return;
      refreshInFlight = true;
      void Promise.resolve(onRefreshChannels())
        .catch(() => undefined)
        .finally(() => {
          refreshInFlight = false;
        });
    };
    refreshFreshness();
    refreshSamples();
    const freshnessTimer = window.setInterval(refreshFreshness, 1000);
    const sampleTimer = window.setInterval(refreshSamples, 10_000);
    return () => {
      window.clearInterval(freshnessTimer);
      window.clearInterval(sampleTimer);
    };
  }, [onRefreshChannels, picker]);

  const selectedSensor = configuration.find((sensor) => sensor.id === editingSensorId) ?? null;
  const pendingChannel = assignable.find((channel) => channel.channelId === pendingChannelId) ?? null;
  const replacementChannels = useMemo(
    () => (selectedSensor ? selectableReplacementChannels(channels, configuration, selectedSensor.id) : []),
    [channels, configuration, selectedSensor],
  );
  const replacementEligible = useMemo(
    () =>
      selectedSensor
        ? replacementChannels.filter(
            (channel) =>
              channel.selectable !== false &&
              channel.channelId !== selectedSensor.id &&
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
  const selectForPlacement = (channel: AvailableSensor) => {
    setError(null);
    setSearch("");
    onPendingChannelChange(channel.channelId);
  };

  const replace = (channel: AvailableSensor) => {
    if (!selectedSensor || !organizationId) return;
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
    patch: Partial<
      Pick<StagedSensorConfiguration, "label" | "side" | "shelf" | "position" | "automaticLabelSource">
    >,
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
    setRemovedSensor({ ...selectedSensor, trend: [...selectedSensor.trend] });
    onConfigurationChange(removeConfiguredSensor(configuration, selectedSensor.id));
    onEditingSensorIdChange(null);
    setPicker(null);
    setError(null);
  };

  const undoRemoval = () => {
    if (!removedSensor) return;
    try {
      const next = restoreRemovedConfiguredSensor(
        configuration,
        removedSensor,
        totalSlots,
        channels,
        equipment.id,
      );
      onConfigurationChange(next);
      onSelect(removedSensor.id);
      onEditingSensorIdChange(removedSensor.id);
      setRemovedSensor(null);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не вдалося відновити маркер.");
    }
  };

  const closeRename = () => {
    setRenamingSensorId(null);
    setRenameDraft("");
    setRenameOriginalLabel("");
    setRenameOriginalAutomaticLabelSource(undefined);
  };
  const startRename = () => {
    if (!selectedSensor) return;
    ignoreNextRenameBlurRef.current = false;
    setRenameDraft(selectedSensor.label);
    setRenameOriginalLabel(selectedSensor.label);
    setRenameOriginalAutomaticLabelSource(selectedSensor.automaticLabelSource);
    setRenamingSensorId(selectedSensor.id);
  };
  const stageRename = (label: string) => {
    setRenameDraft(label);
    update({ label });
  };
  const cancelRename = () => {
    ignoreNextRenameBlurRef.current = true;
    if (selectedSensor && renamingSensorId === selectedSensor.id) {
      update({
        label: renameOriginalLabel,
        automaticLabelSource: renameOriginalAutomaticLabelSource,
      });
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
            <p className="text-xs font-semibold text-white">Розміщено датчиків</p>
            <span className="rounded-full border border-cyan-300/15 bg-cyan-400/[0.07] px-2 py-1 text-[9px] text-cyan-200">
              {configuration.length}
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
          disabled={configuration.length >= effectiveTotalSlots}
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
      {removedSensor ? (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl border border-amber-300/20 bg-amber-400/[0.06] p-3">
          <p role="status" className="min-w-0 flex-1 text-[11px] text-amber-100">
            Маркер {removedSensor.label} видалено з локальної чернетки.
          </p>
          <button
            ref={undoRemovalRef}
            type="button"
            aria-label={`Скасувати видалення маркера ${removedSensor.label}`}
            onClick={undoRemoval}
            className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-amber-300/25 px-3 text-xs text-amber-100 hover:bg-amber-400/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-300"
          >
            <Undo2 className="h-3.5 w-3.5" />
            Скасувати видалення
          </button>
        </div>
      ) : null}
      {picker?.kind === "add" ? (
        <QuickSensorPicker
          testId="equipment-map-quick-sensor-picker"
          channels={assignable}
          search={search}
          onSearch={setSearch}
          now={freshnessNow}
          selectedId={pendingChannelId}
          onPick={selectForPlacement}
          onClose={() => {
            setPicker(null);
            onPendingChannelChange(null);
          }}
        />
      ) : null}
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
          <button
            type="button"
            disabled={!organizationId || replacementEligible.length === 0}
            onClick={() => {
              setSearch("");
              setPicker({ kind: "replace", sensorId: selectedSensor.id });
              setError(null);
            }}
            className="mt-3 inline-flex min-h-9 items-center gap-2 rounded-lg border border-cyan-300/25 px-3 text-xs text-cyan-100 hover:bg-cyan-400/10 disabled:opacity-40"
          >
            <Replace className="h-3.5 w-3.5" />
            Замінити датчик
          </button>
          <details className="mt-3 rounded-xl border border-white/[0.07] bg-black/10">
            <summary className="cursor-pointer list-none px-3 py-2 text-[10px] font-semibold text-slate-300 [&::-webkit-details-marker]:hidden">
              Додаткові параметри
            </summary>
            <div className="grid gap-3 border-t border-white/[0.06] p-3 sm:grid-cols-2 xl:grid-cols-[140px_120px_120px_auto]">
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
          {!organizationId ? (
            <p className="mt-3 text-xs text-rose-200">Контекст організації недоступний.</p>
          ) : null}
          {conflictedReplacements.length > 0 ? (
            <p className="mt-3 text-[10px] text-slate-500">
              Не можна використати через інше обладнання:{" "}
              {conflictedReplacements.map((channel) => channel.channelId).join(", ")}.
            </p>
          ) : null}
          {replacementPickerOpen && organizationId ? (
            <QuickSensorPicker
              testId="equipment-map-replace-telemetry-selector"
              channels={replacementEligible}
              search={search}
              onSearch={setSearch}
              now={freshnessNow}
              onPick={replace}
              onClose={() => setPicker(null)}
            />
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
  if (channel.displayName) return channel.displayName;
  if (channel.inputNumber) return `Вхід ${channel.inputNumber}`;
  return channel.inventoryNumber ? `№ ${channel.inventoryNumber}` : channel.channelId;
}

function QuickSensorPicker({
  channels,
  search,
  onSearch,
  onPick,
  onClose,
  selectedId,
  now,
  testId,
}: {
  channels: readonly AvailableSensor[];
  search: string;
  onSearch: (value: string) => void;
  onPick: (channel: AvailableSensor) => void;
  onClose: () => void;
  selectedId?: string | null;
  now: number;
  testId: string;
}) {
  const query = search.trim().toLocaleLowerCase("uk-UA");
  const groups = new Map<string, AvailableSensor[]>();
  const legacy: AvailableSensor[] = [];
  for (const channel of channels) {
    const searchable = [
      channel.controllerLabel,
      channel.displayName,
      quickChannelLabel(channel),
      channel.channelId,
      channel.metric,
    ];
    if (query && !searchable.filter(Boolean).join(" ").toLocaleLowerCase("uk-UA").includes(query)) {
      continue;
    }
    if (!channel.controllerLabel) {
      legacy.push(channel);
      continue;
    }
    const group = groups.get(channel.controllerLabel) ?? [];
    group.push(channel);
    groups.set(channel.controllerLabel, group);
  }

  const renderChannels = (items: AvailableSensor[]) => (
    <div className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-3">
      {items.map((channel) => {
        const label = quickChannelLabel(channel);
        const status = channelTelemetryLabel(channel, now);
        const description = channel.controllerLabel
          ? status === "Live"
            ? `${channel.latestValue} °C`
            : status === "Stale" || (channel.latestValue === null && status === "Немає даних")
              ? "Немає свіжих даних"
              : status
          : `${channel.channelId} · ${status}`;
        return (
          <button
            key={channel.channelId}
            type="button"
            aria-label={`Обрати датчик ${label}, канал ${channel.channelId}`}
            aria-pressed={selectedId === undefined ? undefined : selectedId === channel.channelId}
            onClick={() => onPick(channel)}
            className="min-w-0 rounded-xl border border-white/[0.07] bg-white/[0.025] px-3 py-2 text-left text-slate-300 hover:border-cyan-300/20 hover:bg-white/[0.045] aria-pressed:border-cyan-300/45 aria-pressed:bg-cyan-400/15 aria-pressed:text-cyan-50"
          >
            <span className="block truncate text-xs font-semibold">{label}</span>
            <span className="mt-0.5 block truncate text-[10px] text-slate-400">{description}</span>
          </button>
        );
      })}
    </div>
  );

  return (
    <div className="mt-3 rounded-xl border border-cyan-300/15 bg-[#07182f]/95 p-3" data-testid={testId}>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <input
          type="search"
          autoFocus
          aria-label="Пошук датчика"
          placeholder="Контролер, вхід або № датчика"
          value={search}
          onChange={(event) => onSearch(event.target.value)}
          className={`${inputClass} min-w-0 flex-1`}
        />
        <button
          type="button"
          onClick={onClose}
          className="min-h-10 rounded-xl px-3 text-xs text-slate-400 hover:text-white"
        >
          Закрити
        </button>
      </div>
      <div
        className="mt-2 max-h-60 space-y-3 overflow-y-auto pr-1"
        role="group"
        aria-label="Доступні датчики"
      >
        {[...groups]
          .sort(([a], [b]) => a.localeCompare(b, "uk", { numeric: true }))
          .map(([label, items]) => (
            <div key={label} role="group" aria-label={label} className="space-y-1.5">
              <p className="text-xs font-semibold text-cyan-200">{label}</p>
              {renderChannels(items.sort((a, b) => (a.inputNumber ?? 0) - (b.inputNumber ?? 0)))}
            </div>
          ))}
        {legacy.length > 0 &&
          (groups.size > 0 && !query ? (
            <details className="space-y-2 text-xs text-slate-400">
              <summary className="cursor-pointer">Канали каталогу ({legacy.length})</summary>
              {renderChannels(legacy)}
            </details>
          ) : (
            renderChannels(legacy)
          ))}
        {groups.size === 0 && legacy.length === 0 ? (
          <p className="px-2 py-5 text-center text-xs text-slate-400">Доступних датчиків не знайдено.</p>
        ) : null}
      </div>
    </div>
  );
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
