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
  const [search, setSearch] = useState("");
  const [selectedOnly, setSelectedOnly] = useState(false);
  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  const selectedKeys = new Set(draft.map(energySeriesSelectionKey));
  const toggle = (pair: EnergySeriesSelection) =>
    setDraft((current) => {
      const key = energySeriesSelectionKey(pair);
      return current.some((item) => energySeriesSelectionKey(item) === key)
        ? current.filter((item) => energySeriesSelectionKey(item) !== key)
        : normalizeEnergySeriesSelection([...current, pair]);
    });
  const normalizedSearch = search.trim().toLocaleLowerCase("uk-UA");
  const visibleMeters = ENERGY_METERS.map((meter) => {
    const meterText = [meter.label, meter.equipmentId, meter.modelLabel, String(meter.unitId)]
      .join(" ")
      .toLocaleLowerCase("uk-UA");
    const matchesMeter = meterText.includes(normalizedSearch);
    const metrics = ENERGY_METRICS.filter((metric) => {
      const key = energySeriesSelectionKey({ unitId: meter.unitId, metric: metric.id });
      if (selectedOnly && !selectedKeys.has(key)) return false;
      if (!normalizedSearch || matchesMeter) return true;
      return [metric.label, metric.shortLabel, metric.id, metric.expectedUnit]
        .join(" ")
        .toLocaleLowerCase("uk-UA")
        .includes(normalizedSearch);
    });
    return { meter, metrics };
  }).filter((group) => group.metrics.length > 0);

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
        <header className="flex items-start justify-between gap-3 border-b border-white/[0.06] p-4 sm:p-5">
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
        <div className="space-y-3 border-b border-white/[0.06] p-3 sm:p-4">
          <label className="block text-xs font-medium text-slate-200">
            Пошук лічильника або показника
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="W1, напруга, струм, kWh…"
              className="mt-1.5 h-11 w-full rounded-xl border border-white/10 bg-[#06142a] px-3 text-sm text-white outline-none placeholder:text-slate-500 focus-visible:ring-2 focus-visible:ring-cyan-300"
            />
          </label>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              aria-pressed={selectedOnly}
              onClick={() => setSelectedOnly((current) => !current)}
              className={`min-h-10 rounded-xl border px-3 text-xs font-medium focus-visible:ring-2 focus-visible:ring-cyan-300 ${selectedOnly ? "border-cyan-300/30 bg-cyan-400/10 text-cyan-100" : "border-white/10 text-slate-300 hover:text-white"}`}
            >
              Лише вибрані
            </button>
            <p role="status" className="text-xs text-slate-300">
              {visibleMeters.length} із {ENERGY_METERS.length} лічильників · {draft.length} серій обрано
            </p>
          </div>
        </div>
        <div className="min-h-0 space-y-3 overflow-y-auto p-3 sm:p-4">
          {visibleMeters.length === 0 ? (
            <div className="rounded-xl border border-dashed border-white/10 p-5 text-center">
              <p className="text-sm text-slate-300">За цими умовами показників немає</p>
              <button
                type="button"
                onClick={() => {
                  setSearch("");
                  setSelectedOnly(false);
                }}
                className="mt-2 min-h-10 rounded-lg border border-white/10 px-3 text-xs font-medium text-cyan-200 hover:border-cyan-300/30"
              >
                Показати всі параметри
              </button>
            </div>
          ) : null}
          {visibleMeters.map(({ meter, metrics }) => (
            <fieldset key={meter.unitId} className="min-w-0 rounded-xl border border-white/[0.08] p-3">
              <legend className="px-2 text-xs font-semibold text-cyan-200">
                {meter.label} · {meter.equipmentId}
                <span className="ml-2 text-[11px] font-normal text-slate-400">
                  {draft.filter((pair) => pair.unitId === meter.unitId).length} обрано
                </span>
              </legend>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {metrics.map((metric) => {
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
                            className="mt-1 block text-[11px] leading-4"
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
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] p-3 sm:p-4">
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
