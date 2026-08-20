"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, LoaderCircle, RefreshCw, Save, Thermometer, X } from "lucide-react";

import type { Xjp60dDiscoveryPoint, Xjp60dSensorManagement } from "@/hooks/use-xjp60d-sensor-management";

type DisplayPoint = Omit<Xjp60dDiscoveryPoint, "quality"> & {
  quality: Xjp60dDiscoveryPoint["quality"] | "unknown";
};

type SensorManagementDialogProps = {
  open: boolean;
  canManage: boolean;
  management: Xjp60dSensorManagement;
  onClose: () => void;
  onSaved: () => void;
};

function compareChannels(left: string, right: string): number {
  const [leftUnit = 0, leftChannel = 0] = left.split("-").map(Number);
  const [rightUnit = 0, rightChannel = 0] = right.split("-").map(Number);
  return leftUnit - rightUnit || leftChannel - rightChannel;
}

function chamberLabel(unitId: number): string {
  if (unitId >= 101 && unitId <= 115) return "КК2";
  if (unitId >= 126 && unitId <= 138) return "КК1";
  return "Інше";
}

function formatTemperature(point: DisplayPoint): string {
  if (point.value === null || point.quality !== "valid") return "—";
  return `${new Intl.NumberFormat("uk-UA", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(point.value)} °C`;
}

function diagnosticLabel(state: string, recoveryState: string): string {
  if (state === "initializing") return "Ініціалізація — очікується перша спроба";
  if (recoveryState === "cooldown") return "Тимчасова втрата зв’язку — cooldown";
  if (state === "communication_error") return "Помилка зв’язку";
  if (state === "sensor_error") return "Помилка входу датчика";
  if (recoveryState === "recovered") return "Зв’язок відновлено";
  if (state === "valid") return "Моніторинг · дані надходять";
  return state;
}

export function SensorManagementDialog(props: SensorManagementDialogProps) {
  if (!props.open) return null;
  return <SensorManagementDialogContent {...props} />;
}

function SensorManagementDialogContent({
  canManage,
  management,
  onClose,
  onSaved,
}: SensorManagementDialogProps) {
  const [selected, setSelected] = useState<string[]>(() => [...management.monitoredChannelIds]);
  const configurationReady = management.configuration !== null && !management.isLoading;

  const points = useMemo(() => {
    const map = new Map<string, DisplayPoint>();
    const discovery = management.configuration?.last_discovery;
    for (const point of [...(discovery?.available_points ?? []), ...(discovery?.unavailable_points ?? [])]) {
      map.set(point.channel_id, point);
    }
    for (const channelId of management.monitoredChannelIds) {
      if (map.has(channelId)) continue;
      const [unitId, channel] = channelId.split("-").map(Number);
      map.set(channelId, {
        channel_id: channelId,
        unit_id: unitId,
        channel,
        quality: "unknown",
        value: null,
        unit: "degC",
        alarm: null,
        raw_status: null,
      });
    }
    return [...map.values()].sort((left, right) => compareChannels(left.channel_id, right.channel_id));
  }, [management.monitoredChannelIds, management.configuration?.last_discovery]);

  const discovery = management.configuration?.last_discovery;
  const diagnostics = useMemo(
    () =>
      new Map((management.configuration?.target_diagnostics ?? []).map((item) => [item.channel_id, item])),
    [management.configuration?.target_diagnostics],
  );
  const toggle = (channelId: string) => {
    setSelected((current) =>
      current.includes(channelId)
        ? current.filter((item) => item !== channelId)
        : [...current, channelId].sort(compareChannels),
    );
  };

  const save = async () => {
    if (!canManage || !configurationReady || management.isSaving || management.isDiscovering) return;
    if (await management.save(selected)) {
      onSaved();
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 z-[80] grid place-items-center bg-[#020817]/80 p-3 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="sensor-management-title"
    >
      <section className="flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden rounded-3xl border border-cyan-300/15 bg-[#081a34] shadow-2xl shadow-black/50">
        <header className="flex items-start justify-between gap-4 border-b border-white/[0.06] px-5 py-4">
          <div>
            <p className="text-[9px] tracking-[0.18em] text-cyan-300 uppercase">RS-485 commissioning</p>
            <h2 id="sensor-management-title" className="mt-1 text-base font-semibold text-white">
              Безперервний моніторинг XJP60D
            </h2>
            <p className="mt-1 max-w-2xl text-[10px] leading-5 text-slate-400">
              Discovery лише виявляє канали. Безперервно опитуються тільки явно увімкнені тут канали;
              Overview, Live та підкладки не змінюють monitoring enrollment.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрити керування датчиками"
            className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-white/[0.07] text-slate-400 hover:border-cyan-300/25 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.05] px-5 py-3">
          <div className="flex flex-wrap gap-2 text-[9px]">
            <span className="rounded-full border border-emerald-300/15 bg-emerald-400/[0.05] px-2.5 py-1 text-emerald-200">
              {selected.length} у моніторингу
            </span>
            <span className="rounded-full border border-white/[0.07] px-2.5 py-1 text-slate-400">
              {discovery?.available_points.length ?? 0} підключених знайдено
            </span>
            {discovery ? (
              <span className="rounded-full border border-white/[0.07] px-2.5 py-1 text-slate-500">
                {discovery.duration_ms} мс · {discovery.reachable_controller_count}/
                {discovery.controller_count} контролерів
              </span>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => void management.discover()}
            disabled={!canManage || management.isDiscovering || management.isSaving}
            className="inline-flex items-center gap-2 rounded-xl border border-cyan-300/20 bg-cyan-400/[0.06] px-3 py-2 text-[10px] font-medium text-cyan-100 hover:bg-cyan-400/[0.1] disabled:cursor-not-allowed disabled:opacity-45"
          >
            {management.isDiscovering ? (
              <LoaderCircle className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            Оновити список датчиків
          </button>
        </div>

        {management.error ? (
          <div className="mx-5 mt-4 flex items-start gap-2 rounded-xl border border-red-300/15 bg-red-400/[0.05] p-3 text-[10px] text-red-100">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{management.error}</span>
          </div>
        ) : null}

        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {management.isLoading && points.length === 0 ? (
            <div className="grid min-h-48 place-items-center text-[10px] text-cyan-200">
              <span className="inline-flex items-center gap-2">
                <LoaderCircle className="h-4 w-4 animate-spin" /> Завантаження конфігурації…
              </span>
            </div>
          ) : points.length === 0 ? (
            <div className="grid min-h-48 place-items-center rounded-2xl border border-dashed border-white/[0.08] text-center">
              <div>
                <Thermometer className="mx-auto h-6 w-6 text-slate-600" />
                <p className="mt-3 text-[11px] text-slate-300">Список ще не сформовано</p>
                <p className="mt-1 text-[9px] text-slate-500">Запустіть одноразове зчитування RS-485.</p>
              </div>
            </div>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {points.map((point) => {
                const checked = selected.includes(point.channel_id);
                const active = management.monitoredChannelIds.includes(point.channel_id);
                const diagnostic = active ? diagnostics.get(point.channel_id) : undefined;
                const unavailable = point.quality !== "valid";
                const disabled = !canManage || !configurationReady || (unavailable && !checked);
                return (
                  <label
                    key={point.channel_id}
                    className={`flex items-center gap-3 rounded-2xl border p-3 transition ${
                      checked
                        ? "border-cyan-300/25 bg-cyan-400/[0.07]"
                        : "border-white/[0.06] bg-[#07162d]/70"
                    } ${
                      disabled ? "cursor-not-allowed opacity-55" : "cursor-pointer hover:border-cyan-300/15"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={disabled}
                      onChange={() => toggle(point.channel_id)}
                      className="h-4 w-4 accent-cyan-400"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-[10px] font-semibold text-white">{point.channel_id}</p>
                        {diagnostic?.state === "initializing" ? (
                          <LoaderCircle className="h-3.5 w-3.5 animate-spin text-cyan-300" />
                        ) : point.quality === "valid" ? (
                          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-300" />
                        ) : (
                          <AlertTriangle className="h-3.5 w-3.5 text-amber-300" />
                        )}
                      </div>
                      <p className="mt-1 text-[8px] text-slate-500">
                        {chamberLabel(point.unit_id)} · вхід {point.channel} ·{" "}
                        {diagnostic
                          ? diagnosticLabel(diagnostic.state, diagnostic.recovery_state)
                          : point.quality}
                      </p>
                      {diagnostic ? (
                        <p className="mt-1 text-[8px] text-slate-600">
                          {diagnostic.outcomes.attempts} спроб · {diagnostic.outcomes.successes} успішних ·{" "}
                          {diagnostic.consecutive_failures} послідовних помилок
                        </p>
                      ) : null}
                    </div>
                    <span className="text-[10px] font-medium text-slate-200">{formatTemperature(point)}</span>
                  </label>
                );
              })}
            </div>
          )}
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-white/[0.06] px-5 py-4">
          <p className="text-[9px] text-slate-500">
            Commissioning-операція змінює persisted monitoring set Device Agent; Modbus залишається read-only.
          </p>
          <button
            type="button"
            onClick={() => void save()}
            disabled={!canManage || !configurationReady || management.isSaving || management.isDiscovering}
            className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-[10px] font-medium text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-45"
          >
            {management.isSaving ? (
              <LoaderCircle className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            Зберегти моніторинг
          </button>
        </footer>
      </section>
    </div>
  );
}
