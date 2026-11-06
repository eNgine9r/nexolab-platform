"use client";

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Eye, EyeOff, RotateCcw, X } from "lucide-react";

import type { Xjp60dTargetDiagnostic } from "@/hooks/use-xjp60d-sensor-management";
import { OverviewSensorGroups } from "./overview-sensor-groups";

type Props = {
  organizationId?: string | null;
  nodeId?: string | null;
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
  organizationId = null,
  nodeId = null,
  monitoredChannelIds,
  visibleChannelIds,
  targetDiagnostics,
  monitoringError,
  onApply,
  onClose,
}: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    dialog.showModal();
    // Close while connected so the browser restores the element that opened it.
    return () => dialog.close();
  }, []);

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
    <dialog
      ref={dialogRef}
      className="fixed inset-0 z-[80] m-0 h-full max-h-none w-full max-w-none place-items-center border-0 bg-[#020817]/80 p-3 backdrop-blur-sm open:grid"
      onKeyDown={(event) => {
        if (event.key !== "Tab") return;
        const controls = event.currentTarget.querySelectorAll<HTMLElement>(
          "button:not([disabled]), input:not([disabled])",
        );
        const first = controls[0];
        const last = controls[controls.length - 1];
        // Native modal inertness blocks page focus, but Chrome can Tab into browser chrome.
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      aria-modal="true"
      aria-labelledby="temperature-visibility-title"
    >
      <section className="flex max-h-[88vh] w-full max-w-2xl flex-col overflow-hidden rounded-3xl border border-cyan-300/15 bg-[#081a34] shadow-2xl shadow-black/50">
        <header className="flex items-start justify-between gap-3 border-b border-white/[0.06] px-4 py-3 sm:px-5">
          <div>
            <p className="text-[11px] font-semibold text-cyan-300 uppercase">Відображення</p>
            <h2 id="temperature-visibility-title" className="mt-1 text-base font-semibold text-white">
              Датчики на графіку Огляду
            </h2>
            <p className="mt-1 max-w-xl text-xs leading-5 text-slate-400">
              Вибір змінює лише відображення в цьому браузері. Збір RS-485, безперервний
              моніторинг, історія та прив’язки приладів залишаються без змін.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрити вибір датчиків Огляду"
            className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/[0.07] text-slate-300 hover:border-cyan-300/25 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        {monitoringError ? (
          <div
            className="mx-4 mt-3 flex items-start gap-2 rounded-xl border border-amber-300/15 bg-amber-400/[0.05] p-3 text-xs text-amber-100 sm:mx-5"
            role="alert"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>Не вдалося підтвердити актуальний monitoring set: {monitoringError}</span>
          </div>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/[0.05] px-4 py-2.5 sm:px-5">
          <span className="text-xs text-slate-300">
            {selected.length} показано · {monitored.length} у безперервному моніторингу
          </span>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setSelected(monitored)}
              className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 px-3 py-2 text-xs text-slate-200 hover:border-cyan-300/25 hover:text-white"
            >
              <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
              Показати всі
            </button>
            <button
              type="button"
              onClick={() => setSelected([])}
              disabled={selected.length === 0}
              className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 px-3 py-2 text-xs text-slate-200 hover:border-cyan-300/25 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
            >
              <EyeOff className="h-3.5 w-3.5" aria-hidden="true" />
              Приховати всі
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-3 sm:p-4">
          {monitored.length === 0 ? (
            <div className="grid min-h-40 place-items-center rounded-2xl border border-dashed border-white/[0.08] text-center">
              <div>
                <EyeOff className="mx-auto h-6 w-6 text-slate-600" />
                <p className="mt-3 text-xs text-slate-300">
                  {monitoringError
                    ? "Monitoring set недоступний через помилку Device Agent"
                    : "Немає каналів у безперервному моніторингу"}
                </p>
                <p className="mt-1 text-[11px] text-slate-400">
                  Monitoring enrollment виконується окремо в Налаштуваннях.
                </p>
              </div>
            </div>
          ) : (
            <OverviewSensorGroups
              organizationId={organizationId}
              nodeId={nodeId}
              channelIds={monitored}
              selected={selected}
              onToggleGroup={(ids) =>
                setSelected((current) =>
                  ids.every((id) => current.includes(id))
                    ? current.filter((id) => !ids.includes(id))
                    : [...new Set([...current, ...ids])].sort(compareChannels),
                )
              }
              renderSensor={(channelId, label) => {
                const checked = selected.includes(channelId);
                return (
                  <label
                    key={channelId}
                    className={`flex cursor-pointer items-center gap-2.5 rounded-xl border p-2.5 transition ${
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
                      <p className="text-xs font-semibold break-words text-white">{label}</p>
                      {label !== channelId ? <p className="text-[11px] text-slate-400">{channelId}</p> : null}
                      <p className="mt-1 text-[11px] leading-4 text-slate-400">
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
              }}
            />
          )}
        </div>

        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] px-4 py-3 sm:px-5">
          <p className="text-[11px] text-slate-400">Лише відображення · жодних Device Agent mutations</p>
          <button
            type="button"
            onClick={() => {
              onApply(selected);
              onClose();
            }}
            className="rounded-xl bg-blue-600 px-4 py-2.5 text-xs font-semibold text-white hover:bg-blue-500"
          >
            Застосувати відображення
          </button>
        </footer>
      </section>
    </dialog>
  );
}
