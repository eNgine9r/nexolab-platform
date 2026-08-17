"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CalendarDays, ChevronDown, Clock3, LoaderCircle, TriangleAlert } from "lucide-react";

import {
  formatEnergyConsumptionSelector,
  formatEnergyConsumptionWindow,
  resolveEnergyConsumptionWindow,
  type EnergyConsumptionCustomRange,
  type EnergyConsumptionPreset,
  type EnergyConsumptionResult,
  type EnergyConsumptionWindow,
} from "@/features/energy/energy-consumption";
import type { EnergyConsumptionLoader } from "@/features/energy/use-energy-consumption";
import type { TelemetrySample } from "@/lib/telemetry/types";

const ENERGY_CONSUMPTION_SETTLE_DELAY_MS = 600;

const PRESETS: Array<{ value: Exclude<EnergyConsumptionPreset, "custom">; label: string }> = [
  { value: "today", label: "Сьогодні" },
  { value: "yesterday", label: "Вчора" },
  { value: "last24h", label: "Останні 24 години" },
  { value: "last7d", label: "7 днів" },
  { value: "last30d", label: "30 днів" },
  { value: "month", label: "Цей місяць" },
];

type ConsumptionView =
  | { status: "loading"; result: null }
  | { status: "ready"; result: EnergyConsumptionResult };

type ConsumptionLoadState = {
  requestKey: string;
  result: EnergyConsumptionResult;
};

function toLocalInputValue(value: Date): string {
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}`;
}

function defaultCustomRange(now: Date): EnergyConsumptionCustomRange {
  return {
    fromLocal: toLocalInputValue(new Date(now.getTime() - 24 * 60 * 60 * 1000)),
    toLocal: toLocalInputValue(now),
  };
}

function formatConsumption(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${new Intl.NumberFormat("uk-UA", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)} kWh`;
}

function statusCopy(view: ConsumptionView): { value: string; helper: string; tone: string } {
  if (view.status === "loading") {
    return {
      value: "—",
      helper: "Обчислюємо за підтвердженими показами лічильника…",
      tone: "text-slate-500",
    };
  }
  const result = view.result;
  if (result.status === "ready") {
    return { value: formatConsumption(result.valueKwh), helper: "", tone: "text-slate-500" };
  }
  if (result.status === "discontinuity") {
    return {
      value: "—",
      helper: "Виявлено reset/rollover або інший розрив лічильника. Значення не вигадується.",
      tone: "text-amber-200/75",
    };
  }
  return {
    value: "—",
    helper: result.message ?? "Недостатньо підтверджених даних для вибраного періоду.",
    tone: result.status === "error" ? "text-red-200/70" : "text-slate-500",
  };
}

export function EnergyConsumptionPanel({
  unitId,
  currentCumulative,
  loader,
}: {
  unitId: number;
  currentCumulative: TelemetrySample | null;
  loader: EnergyConsumptionLoader;
}) {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const initialNow = useMemo(() => new Date(), []);
  const [preset, setPreset] = useState<EnergyConsumptionPreset>("last24h");
  const [customRange, setCustomRange] = useState<EnergyConsumptionCustomRange>(() =>
    defaultCustomRange(initialNow),
  );
  const [customDraft, setCustomDraft] = useState<EnergyConsumptionCustomRange>(() =>
    defaultCustomRange(initialNow),
  );
  const [customOpen, setCustomOpen] = useState(false);
  const [customError, setCustomError] = useState<string | null>(null);
  const [loadState, setLoadState] = useState<ConsumptionLoadState | null>(null);
  const refreshKey = currentCumulative?.event_id ?? null;

  const window = useMemo<EnergyConsumptionWindow | null>(() => {
    const referenceNow = refreshKey ? new Date() : initialNow;
    return resolveEnergyConsumptionWindow(
      preset,
      referenceNow,
      preset === "custom" ? customRange : undefined,
    );
  }, [customRange, initialNow, preset, refreshKey]);

  const requestKey = useMemo(() => {
    if (!window) return `invalid:${unitId}:${preset}`;
    return [
      unitId,
      preset,
      window.from.toISOString(),
      window.to.toISOString(),
      currentCumulative?.event_id ?? "history",
    ].join(":");
  }, [currentCumulative?.event_id, preset, unitId, window]);

  useEffect(() => {
    if (!window || !loader.enabled) return;

    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void loader
        .load(unitId, window, currentCumulative, controller.signal)
        .then((result) => {
          if (!controller.signal.aborted) setLoadState({ requestKey, result });
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          setLoadState({
            requestKey,
            result: {
              status: "error",
              valueKwh: null,
              startSample: null,
              endSample: null,
              message: error instanceof Error ? error.message : "Не вдалося завантажити споживання.",
            },
          });
        });
    }, ENERGY_CONSUMPTION_SETTLE_DELAY_MS);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [currentCumulative, loader, requestKey, unitId, window]);

  const view = useMemo<ConsumptionView>(() => {
    if (!window || !loader.enabled) {
      return {
        status: "ready",
        result: {
          status: "error",
          valueKwh: null,
          startSample: null,
          endSample: null,
          message: "Споживання недоступне без локального live runtime.",
        },
      };
    }
    if (!loadState || loadState.requestKey !== requestKey) {
      return { status: "loading", result: null };
    }
    return { status: "ready", result: loadState.result };
  }, [loadState, loader.enabled, requestKey, window]);

  const resolvedWindow = window ?? resolveEnergyConsumptionWindow("last24h", initialNow)!;
  const selectorLabel = formatEnergyConsumptionSelector(preset, resolvedWindow);
  const periodCopy = formatEnergyConsumptionWindow(preset, resolvedWindow);
  const copy = statusCopy(view);
  const warning = view.status === "ready" && view.result.status === "discontinuity";

  const choosePreset = (next: Exclude<EnergyConsumptionPreset, "custom">) => {
    setPreset(next);
    setCustomOpen(false);
    setCustomError(null);
    detailsRef.current?.removeAttribute("open");
  };

  const beginCustom = () => {
    setCustomDraft(customRange);
    setCustomOpen(true);
    setCustomError(null);
  };

  const applyCustom = () => {
    const nextWindow = resolveEnergyConsumptionWindow("custom", new Date(), customDraft);
    if (!nextWindow) {
      setCustomError("Вкажіть коректний початок і кінець: початок має бути раніше завершення.");
      return;
    }
    setCustomRange(customDraft);
    setPreset("custom");
    setCustomOpen(false);
    setCustomError(null);
    detailsRef.current?.removeAttribute("open");
  };

  return (
    <div className="mt-3 rounded-xl border border-cyan-300/10 bg-cyan-400/[0.035] px-3 py-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-medium tracking-[0.1em] text-cyan-300 uppercase">Споживання</p>
        </div>
        <details ref={detailsRef} className="group relative z-20">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-xl border border-cyan-300/15 bg-[#07182f] px-2.5 py-1.5 text-[9px] text-cyan-100 transition hover:border-cyan-300/30 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 [&::-webkit-details-marker]:hidden">
            <span className="max-w-[150px] truncate">{selectorLabel}</span>
            <ChevronDown className="h-3 w-3 shrink-0 transition group-open:rotate-180" />
          </summary>
          <div className="absolute top-[calc(100%+8px)] right-0 w-[250px] rounded-2xl border border-white/10 bg-[#07182f] p-2 shadow-2xl shadow-black/45">
            {PRESETS.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => choosePreset(option.value)}
                className={`flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-[10px] transition hover:bg-white/[0.05] ${
                  preset === option.value ? "bg-cyan-400/[0.07] text-cyan-100" : "text-slate-300"
                }`}
              >
                {option.value === "last24h" ? (
                  <Clock3 className="h-3.5 w-3.5 text-slate-500" />
                ) : (
                  <CalendarDays className="h-3.5 w-3.5 text-slate-500" />
                )}
                {option.label}
              </button>
            ))}
            <div className="my-1 border-t border-white/[0.07]" />
            <button
              type="button"
              onClick={beginCustom}
              className={`flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-[10px] transition hover:bg-white/[0.05] ${
                preset === "custom" ? "bg-cyan-400/[0.07] text-cyan-100" : "text-slate-300"
              }`}
            >
              <CalendarDays className="h-3.5 w-3.5 text-slate-500" />
              Власний період…
            </button>

            {customOpen ? (
              <div className="mt-2 rounded-xl border border-cyan-300/10 bg-cyan-400/[0.025] p-3">
                <label className="grid gap-1 text-[9px] text-slate-500">
                  Від
                  <input
                    type="datetime-local"
                    value={customDraft.fromLocal}
                    onChange={(event) =>
                      setCustomDraft((current) => ({ ...current, fromLocal: event.target.value }))
                    }
                    className="min-w-0 rounded-lg border border-white/10 bg-[#06142a] px-2 py-1.5 text-[10px] text-slate-200 outline-none focus:border-cyan-300/35"
                  />
                </label>
                <label className="mt-2 grid gap-1 text-[9px] text-slate-500">
                  До
                  <input
                    type="datetime-local"
                    value={customDraft.toLocal}
                    onChange={(event) =>
                      setCustomDraft((current) => ({ ...current, toLocal: event.target.value }))
                    }
                    className="min-w-0 rounded-lg border border-white/10 bg-[#06142a] px-2 py-1.5 text-[10px] text-slate-200 outline-none focus:border-cyan-300/35"
                  />
                </label>
                {customError ? (
                  <p className="mt-2 text-[9px] leading-4 text-red-200/80">{customError}</p>
                ) : null}
                <div className="mt-3 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setCustomOpen(false);
                      setCustomError(null);
                    }}
                    className="rounded-lg px-2.5 py-1.5 text-[9px] text-slate-400 hover:bg-white/[0.04]"
                  >
                    Скасувати
                  </button>
                  <button
                    type="button"
                    onClick={applyCustom}
                    className="rounded-lg border border-cyan-300/20 bg-cyan-400/10 px-2.5 py-1.5 text-[9px] font-medium text-cyan-100 hover:bg-cyan-400/15"
                  >
                    Застосувати
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        </details>
      </div>

      <div className="mt-4 flex items-center gap-2">
        {view.status === "loading" ? <LoaderCircle className="h-4 w-4 animate-spin text-cyan-300" /> : null}
        {warning ? <TriangleAlert className="h-4 w-4 text-amber-300" /> : null}
        <p className="text-2xl font-semibold tracking-tight text-white">{copy.value}</p>
      </div>
      <p className="mt-2 text-[9px] text-slate-500">Період: {periodCopy}</p>
      {copy.helper ? <p className={`mt-1.5 text-[8px] leading-4 ${copy.tone}`}>{copy.helper}</p> : null}
      <p className="mt-2 text-[8px] text-slate-600">
        Джерело: різниця підтверджених `electrical.energy.active` · без інтегрування потужності
      </p>
    </div>
  );
}
