"use client";

import { useState } from "react";

import { fromZonedInputValue, toZonedInputValue } from "@/features/display-time/zoned-input";
import { useDisplayTimeZone } from "@/hooks/use-display-time-zone";

const DEFAULT_SPAN_MS = 24 * 60 * 60_000;

/**
 * "Власний період" picker shared by the Overview and Energy history charts (#1683). Values are
 * entered in the operator's display time zone; validation (start before end, at most 31 days)
 * is owned by the caller's `onApply`, whose thrown message is shown verbatim.
 */
export function CustomHistoryRangeForm({
  initialWindow,
  onApply,
  onCancel,
  testId,
}: {
  initialWindow: { from: string; to: string } | null;
  /** Applies the period; throws an `Error` with an operator message when it is invalid. */
  onApply: (fromMs: number | null, toMs: number | null) => void;
  onCancel: () => void;
  testId?: string;
}) {
  const displayTimeZone = useDisplayTimeZone();
  const [from, setFrom] = useState(() => {
    const fallback = Date.now() - DEFAULT_SPAN_MS;
    const parsed = initialWindow ? Date.parse(initialWindow.from) : Number.NaN;
    return toZonedInputValue(Number.isFinite(parsed) ? parsed : fallback, displayTimeZone);
  });
  const [to, setTo] = useState(() => {
    const parsed = initialWindow ? Date.parse(initialWindow.to) : Number.NaN;
    return toZonedInputValue(Number.isFinite(parsed) ? parsed : Date.now(), displayTimeZone);
  });
  const [error, setError] = useState<string | null>(null);

  const apply = () => {
    try {
      onApply(fromZonedInputValue(from, displayTimeZone), fromZonedInputValue(to, displayTimeZone));
      setError(null);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Некоректний період.");
    }
  };

  return (
    <div
      className="mt-3 grid gap-3 rounded-xl border border-white/[0.07] bg-[#06142a]/70 p-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
      data-testid={testId}
    >
      <label className="grid gap-1 text-[10px] text-slate-400">
        Від
        <input
          type="datetime-local"
          value={from}
          onChange={(event) => setFrom(event.target.value)}
          className="min-h-9 rounded-xl border border-white/[0.08] bg-[#081a32] px-2 text-xs text-slate-200 outline-none focus:border-cyan-300/30"
        />
      </label>
      <label className="grid gap-1 text-[10px] text-slate-400">
        До
        <input
          type="datetime-local"
          value={to}
          onChange={(event) => setTo(event.target.value)}
          className="min-h-9 rounded-xl border border-white/[0.08] bg-[#081a32] px-2 text-xs text-slate-200 outline-none focus:border-cyan-300/30"
        />
      </label>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={apply}
          className="min-h-9 rounded-xl bg-blue-600 px-3 text-xs font-medium text-white hover:bg-blue-500"
        >
          Застосувати
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="min-h-9 rounded-xl border border-white/10 px-3 text-xs text-slate-400 hover:text-slate-200"
        >
          Скасувати
        </button>
      </div>
      {error ? (
        <p role="alert" className="text-xs text-red-200 sm:col-span-3">
          {error}
        </p>
      ) : null}
    </div>
  );
}
