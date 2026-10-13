"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import {
  energySeriesDisplayUnit,
  energySeriesSelectionKey,
  normalizeEnergySeriesSelection,
  type EnergySeriesSelection,
} from "@/features/energy/energy-series-selection";
import { ENERGY_METERS, ENERGY_METRICS, energyMeterSupportsMetric } from "@/features/energy/energy-telemetry";

export function EnergyParameterDialog({
  selected,
  onApply,
  onClose,
}: {
  selected: readonly EnergySeriesSelection[];
  onApply: (selected: EnergySeriesSelection[]) => void;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [draft, setDraft] = useState(() => normalizeEnergySeriesSelection(selected));
  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  const selectedKeys = new Set(draft.map(energySeriesSelectionKey));
  const toggle = (pair: EnergySeriesSelection) =>
    setDraft((current) =>
      selectedKeys.has(energySeriesSelectionKey(pair))
        ? current.filter((item) => energySeriesSelectionKey(item) !== energySeriesSelectionKey(pair))
        : normalizeEnergySeriesSelection([...current, pair]),
    );

  return (
    <dialog
      ref={dialogRef}
      aria-modal="true"
      aria-labelledby="energy-parameters-title"
      className="fixed inset-0 z-[80] m-0 h-full max-h-none w-full max-w-none place-items-center border-0 bg-[#020817]/80 p-3 backdrop-blur-sm open:grid"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onKeyDown={(event) => {
        if (event.key !== "Tab") return;
        const controls = event.currentTarget.querySelectorAll<HTMLElement>(
          "button:not([disabled]), input:not([disabled])",
        );
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }}
    >
      <section className="flex max-h-[88vh] w-full max-w-3xl flex-col overflow-hidden rounded-3xl border border-cyan-300/15 bg-[#081a34] text-slate-100 shadow-2xl shadow-black/50">
        <header className="flex items-start justify-between gap-4 border-b border-white/[0.06] p-5">
          <div>
            <h2 id="energy-parameters-title" className="text-base font-semibold text-white">
              Параметри на графіку
            </h2>
            <p className="mt-2 text-xs leading-5 text-slate-400">
              Оберіть потрібні показники кожного лічильника. Частота вимірювань не змінюється.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрити вибір параметрів"
            className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/10 text-slate-300 focus-visible:outline-2 focus-visible:outline-cyan-300"
          >
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="min-h-0 space-y-4 overflow-y-auto p-5">
          {ENERGY_METERS.map((meter) => (
            <fieldset key={meter.unitId} className="min-w-0 rounded-2xl border border-white/[0.08] p-3">
              <legend className="px-2 text-sm font-semibold text-cyan-200">
                {meter.label} · {meter.equipmentId}
              </legend>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {ENERGY_METRICS.map((metric) => {
                  const pair = { unitId: meter.unitId, metric: metric.id };
                  const supported = energyMeterSupportsMetric(meter, metric.id);
                  return (
                    <label
                      key={metric.id}
                      className={`flex min-h-11 min-w-0 items-center gap-2 rounded-xl border border-white/[0.06] px-3 py-2 text-xs ${supported ? "cursor-pointer text-slate-200" : "text-slate-500"}`}
                    >
                      <input
                        type="checkbox"
                        checked={selectedKeys.has(energySeriesSelectionKey(pair))}
                        disabled={!supported}
                        onChange={() => toggle(pair)}
                        aria-label={`${meter.label} · ${metric.label}`}
                        aria-describedby={
                          !supported ? `unsupported-energy-${meter.unitId}-${metric.shortLabel}` : undefined
                        }
                        className="h-4 w-4 shrink-0 accent-cyan-400"
                      />
                      <span className="min-w-0">
                        {metric.label} · {energySeriesDisplayUnit(metric.id)}
                        {!supported ? (
                          <span
                            id={`unsupported-energy-${meter.unitId}-${metric.shortLabel}`}
                            className="mt-1 block text-[10px]"
                          >
                            Не підтримується цим лічильником
                          </span>
                        ) : null}
                      </span>
                    </label>
                  );
                })}
              </div>
            </fieldset>
          ))}
        </div>
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] p-5">
          <button
            type="button"
            onClick={() => setDraft([])}
            className="min-h-10 rounded-xl border border-white/10 px-3 text-xs text-slate-300"
          >
            Очистити вибір
          </button>
          <span className="text-xs text-slate-400" aria-live="polite">
            Вибрано серій: {draft.length}
          </span>
          <button
            type="button"
            onClick={() => {
              onApply(draft);
              onClose();
            }}
            className="min-h-10 rounded-xl bg-blue-500 px-4 text-xs font-medium text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300"
          >
            Застосувати
          </button>
        </footer>
      </section>
    </dialog>
  );
}
