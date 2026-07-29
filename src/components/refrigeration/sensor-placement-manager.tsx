"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, Pencil, Plus, Trash2, X } from "lucide-react";

import { RefrigerationIconButton } from "@/components/refrigeration/refrigeration-icon-button";
import type { SensorSide } from "@/data/refrigeration";
import type { AvailableSensor } from "@/features/refrigeration/equipment-lifecycle-repository";
import {
  addChannelToConfiguration,
  removeConfiguredSensor,
  replaceConfiguredChannel,
  selectableReplacementChannels,
  type StagedSensorConfiguration,
  unusedClimateChamberChannels,
  updateConfiguredSensor,
} from "@/features/refrigeration/sensor-configuration";

export function SensorPlacementManager({
  equipmentId,
  totalSlots,
  channels,
  configuration,
  editingSensorId,
  onEditingSensorIdChange,
  onConfigurationChange,
  onSelect,
}: {
  equipmentId: string;
  totalSlots: number;
  channels: readonly AvailableSensor[];
  configuration: readonly StagedSensorConfiguration[];
  editingSensorId: string | null;
  onEditingSensorIdChange: (sensorId: string | null) => void;
  onConfigurationChange: (configuration: StagedSensorConfiguration[]) => void;
  onSelect: (sensorId: string) => void;
}) {
  const unused = useMemo(
    () => unusedClimateChamberChannels(channels, configuration, equipmentId),
    [channels, configuration, equipmentId],
  );
  const [selectedChannelId, setSelectedChannelId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const effectiveSelectedChannelId = unused.some(
    (channel) => channel.channelId === selectedChannelId,
  )
    ? selectedChannelId
    : (unused[0]?.channelId ?? "");
  const selectedSensor = configuration.find((sensor) => sensor.id === editingSensorId) ?? null;
  const replacementChannels = useMemo(
    () =>
      selectedSensor
        ? selectableReplacementChannels(channels, configuration, selectedSensor.id, equipmentId)
        : [],
    [channels, configuration, equipmentId, selectedSensor],
  );

  const add = () => {
    const channel = channels.find(
      (candidate) => candidate.channelId === effectiveSelectedChannelId,
    );
    if (!channel) return;
    setError(null);
    try {
      const next = addChannelToConfiguration(configuration, channel, totalSlots);
      onConfigurationChange(next);
      onSelect(channel.channelId);
      onEditingSensorIdChange(channel.channelId);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не вдалося додати датчик.");
    }
  };

  const replace = (channelId: string) => {
    if (!selectedSensor) return;
    const channel = channels.find((candidate) => candidate.channelId === channelId);
    if (!channel) return;
    setError(null);
    try {
      const next = replaceConfiguredChannel(configuration, selectedSensor.id, channel);
      onConfigurationChange(next);
      onSelect(channel.channelId);
      onEditingSensorIdChange(channel.channelId);
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
    setError(null);
  };

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
              {configuration.length}/{totalSlots}
            </span>
          </div>
          <p className="mt-1 text-[10px] leading-4 text-slate-500">
            Додавайте й налаштовуйте кілька каналів. Сервер буде змінено лише після загального
            збереження схеми.
          </p>
        </div>

        <div className="flex min-w-0 items-end gap-2 xl:min-w-[420px]">
          <label className="min-w-0 flex-1 space-y-1.5">
            <span className="text-[9px] font-semibold tracking-wider text-slate-600 uppercase">
              Доступний датчик або прилад
            </span>
            <select
              aria-label="Доступний датчик кліматичної камери"
              value={effectiveSelectedChannelId}
              disabled={unused.length === 0 || configuration.length >= totalSlots}
              onChange={(event) => setSelectedChannelId(event.target.value)}
              className="w-full rounded-xl border border-white/[0.08] bg-[#0b1e38] px-3 py-2.5 text-xs text-slate-300 outline-none disabled:cursor-not-allowed disabled:opacity-40"
            >
              {unused.length === 0 ? <option value="">Немає доступних каналів</option> : null}
              {unused.map((channel) => (
                <option key={channel.channelId} value={channel.channelId}>
                  {channel.channelId} · {channel.metric}
                  {channel.latestValue === null
                    ? " · немає даних"
                    : ` · ${channel.latestValue} ${channel.unit}`}
                </option>
              ))}
            </select>
          </label>
          <RefrigerationIconButton
            label="Додати вибраний датчик на підкладку"
            onClick={add}
            disabled={!effectiveSelectedChannelId || configuration.length >= totalSlots}
            tone="success"
            size="lg"
          >
            <Plus className="h-4 w-4" />
          </RefrigerationIconButton>
        </div>
      </div>

      {unused.length === 0 && configuration.length === 0 ? (
        <p className="mt-3 flex items-start gap-2 rounded-xl border border-amber-400/20 bg-amber-500/10 px-3 py-2 text-[10px] text-amber-200">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          У вибраній кліматичній камері ще немає доступних telemetry channels. Перевірте, що її
          node активний і вже передав хоча б один пакет вимірювань.
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
              onClick={() => onEditingSensorIdChange(null)}
              size="sm"
            >
              <X className="h-3.5 w-3.5" />
            </RefrigerationIconButton>
          </div>

          <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_140px_120px_120px_auto]">
            <EditorField label="Канал вимірювання">
              <select
                aria-label="Замінити канал датчика"
                value={selectedSensor.id}
                onChange={(event) => replace(event.target.value)}
                className={inputClass}
              >
                {replacementChannels.map((channel) => (
                  <option key={channel.channelId} value={channel.channelId}>
                    {channel.channelId} · {channel.metric}
                  </option>
                ))}
              </select>
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
              <RefrigerationIconButton
                label="Видалити датчик з підкладки"
                onClick={remove}
                tone="danger"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </RefrigerationIconButton>
            </div>
          </div>
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

function EditorField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="space-y-1.5">
      <span className="text-[9px] font-semibold tracking-wider text-slate-600 uppercase">{label}</span>
      {children}
    </label>
  );
}

const inputClass =
  "w-full rounded-xl border border-white/[0.08] bg-[#0b1e38] px-3 py-2.5 text-xs text-slate-200 outline-none focus:border-cyan-300/35 focus:ring-2 focus:ring-cyan-300/10";
