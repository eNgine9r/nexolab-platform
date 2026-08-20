"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, Eye, EyeOff, RotateCcw, X } from "lucide-react";

import type { Xjp60dTargetDiagnostic } from "@/hooks/use-xjp60d-sensor-management";

type Props = {
  open: boolean;
  monitoredChannelIds: readonly string[];
  visibleChannelIds: readonly string[];
  targetDiagnostics: readonly Xjp60dTargetDiagnostic[];
  monitoringError: string | null;
  onApply: (channelIds: readonly string[]) => void;
  onClose: () => void;
};

function compareChannels(left: string, right: string): number {
  const [leftUnit = 0, leftChannel = 0] = left.split("-").map(Number);
  const [rightUnit = 0, rightChannel = 0] = right.split("-").map(Number);
  return leftUnit - rightUnit || leftChannel - rightChannel;
}

function diagnosticLabel(diagnostic: Xjp60dTargetDiagnostic | undefined): string {
  if (!diagnostic || diagnostic.state === "unknown") return "Стан очікується";
  if (diagnostic.state === "initializing") return "Моніторинг · ініціалізація";
  if (diagnostic.recovery_state === "cooldown") return "Моніторинг · втрата зв’язку";
  if (diagnostic.state === "communication_error") return "Моніторинг · помилка зв’язку";
  if (diagnostic.state === "sensor_error") return "Моніторинг · помилка датчика";
  if (diagnostic.recovery_state === "recovered") return "Моніторинг · зв’язок відновлено";
  return "Моніторинг · дані надходять";
}

export function TemperatureVisibilityDialog(props: Props) {
  if (!props.open) return null;
  return <TemperatureVisibilityDialogContent {...props} />;
}

function TemperatureVisibilityDialogContent({
  monitoredChannelIds,
  visibleChannelIds,
  targetDiagnostics,
  monitoringError,
  onApply,
  onClose,
}: Props) {
  const monitored = useMemo(
    () => [...new Set(monitoredChannelIds)].sort(compareChannels),
    [monitoredChannelIds],
  );
  const [selected, setSelected] = useState<string[]>(() =>
    [...new Set(visibleChannelIds)].filter((item) => monitored.includes(item)).sort(compareChannels),
  );
  const diagnostics = useMemo(
    () => new Map(targetDiagnostics.map((item) => [item.channel_id, item])),
    [targetDiagnostics],
  );

  const toggle = (channelId: string) => {
    setSelected((current) =>
      current.includes(channelId)
        ? current.filter((item) => item !== channelId)
        : [...current, channelId].sort(compareChannels),
    );
  };

  return (
    <div
      className="fixed inset-0 z-[80] grid place-items-center bg-[#020817]/80 p-3 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="temperature-visibility-title"
    >
      <section className="flex max-h-[88vh] w-full max-w-2xl flex-col overflow-hidden rounded-3xl border border-cyan-300/15 bg-[#081a34] shadow-2xl shadow-black/50">
        <header className="flex items-start justify-between gap-4 border-b border-white/[0.06] px-5 py-4">
          <div>
            <p className="text-[9px] tracking-[0.18em] text-cyan-300 uppercase">Overview presentation</p>
            <h2 id="temperature-visibility-title" className="mt-1 text-base font-semibold text-white">
              Датчики на графіку Огляду
            </h2>
            <p className="mt-1 max-w-xl text-[10px] leading-5 text-slate-400">
              Вибір змінює лише відображення в цьому браузері. Збір RS-485, monitoring enrollment, Live,
              історія та прив’язки до обладнання не змінюються.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрити вибір датчиків Огляду"
            className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-white/[0.07] text-slate-400 hover:border-cyan-300/25 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        {monitoringError ? (
          <div
            className="mx-5 mt-4 flex items-start gap-2 rounded-xl border border-amber-300/15 bg-amber-400/[0.05] p-3 text-[10px] text-amber-100"
            role="alert"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>Не вдалося підтвердити актуальний monitoring set: {monitoringError}</span>
          </div>
        ) : null}

        <div className="flex items-center justify-between gap-3 border-b border-white/[0.05] px-5 py-3">
          <span className="text-[10px] text-slate-400">
            {selected.length} показано · {monitored.length} у безперервному моніторингу
          </span>
          <button
            type="button"
            onClick={() => setSelected(monitored)}
            className="inline-flex items-center gap-2 rounded-xl border border-white/10 px-3 py-2 text-[10px] text-slate-300 hover:border-cyan-300/25 hover:text-white"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Показати всі
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {monitored.length === 0 ? (
            <div className="grid min-h-40 place-items-center rounded-2xl border border-dashed border-white/[0.08] text-center">
              <div>
                <EyeOff className="mx-auto h-6 w-6 text-slate-600" />
                <p className="mt-3 text-[11px] text-slate-300">
                  {monitoringError
                    ? "Monitoring set недоступний через помилку Device Agent"
                    : "Немає каналів у безперервному моніторингу"}
                </p>
                <p className="mt-1 text-[9px] text-slate-500">
                  Monitoring enrollment виконується окремо в Налаштуваннях.
                </p>
              </div>
            </div>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2">
              {monitored.map((channelId) => {
                const checked = selected.includes(channelId);
                return (
                  <label
                    key={channelId}
                    className={`flex cursor-pointer items-center gap-3 rounded-2xl border p-3 transition ${
                      checked
                        ? "border-cyan-300/25 bg-cyan-400/[0.07]"
                        : "border-white/[0.06] bg-[#07162d]/70 hover:border-cyan-300/15"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      aria-label={`Показувати ${channelId} на Огляді`}
                      onChange={() => toggle(channelId)}
                      className="h-4 w-4 accent-cyan-400"
                    />
                    <div className="min-w-0 flex-1">
                      <p className="text-[10px] font-semibold text-white">{channelId}</p>
                      <p className="mt-1 text-[8px] text-slate-500">
                        {diagnosticLabel(diagnostics.get(channelId))}
                      </p>
                    </div>
                    {checked ? (
                      <Eye className="h-3.5 w-3.5 text-cyan-200" aria-hidden="true" />
                    ) : (
                      <EyeOff className="h-3.5 w-3.5 text-slate-600" aria-hidden="true" />
                    )}
                  </label>
                );
              })}
            </div>
          )}
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-white/[0.06] px-5 py-4">
          <p className="text-[9px] text-slate-500">Display-only · жодних Device Agent mutations</p>
          <button
            type="button"
            onClick={() => {
              onApply(selected);
              onClose();
            }}
            className="rounded-xl bg-blue-600 px-4 py-2.5 text-[10px] font-medium text-white hover:bg-blue-500"
          >
            Застосувати відображення
          </button>
        </footer>
      </section>
    </div>
  );
}
