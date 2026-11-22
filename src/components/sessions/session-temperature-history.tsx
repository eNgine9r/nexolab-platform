"use client";

import { useEffect, useMemo, useState } from "react";

import { OverviewChartPanel } from "@/components/dashboard/overview-chart-panel";
import type { ChartXDomain } from "@/features/charts/domain";
import { buildOverviewChartGroups } from "@/features/dashboard/overview-chart";
import { sessionChartDomain, type SessionHistoryWindow } from "@/components/sessions/session-chart-domain";
import { isLiveSampleFresh, resolveLiveFreshness } from "@/features/live/freshness";
import type { TelemetrySample } from "@/lib/telemetry/types";

/**
 * Real session temperature history on the canonical chart system.
 * Replaces the previous TemperatureChart call that fell back to hard-coded demo tiles
 * (chart audit 2026-11-21): session evidence must never show fabricated values.
 */
export function SessionTemperatureHistory({
  samples,
  now,
  historyWindow,
}: {
  samples: readonly TelemetrySample[];
  /** Requested history window; becomes the x domain so silent edges stay visible. */
  historyWindow?: SessionHistoryWindow | null;
  now?: number;
}) {
  const [hiddenSeriesKeys, setHiddenSeriesKeys] = useState<Set<string>>(() => new Set());
  const [soloSeriesKey, setSoloSeriesKey] = useState<string | null>(null);
  const [sharedCursorMs, setSharedCursorMs] = useState<number | null>(null);
  const [viewportDomain, setViewportDomain] = useState<ChartXDomain | null>(null);
  const [clock, setClock] = useState(() => Date.now());
  useEffect(() => {
    const timer = globalThis.setInterval(() => setClock(Date.now()), 30_000);
    return () => globalThis.clearInterval(timer);
  }, []);
  const effectiveNow = now ?? clock;

  const resetDomain = useMemo<ChartXDomain | null>(
    () =>
      sessionChartDomain(
        samples.map((sample) => Date.parse(sample.captured_at)),
        historyWindow,
      ),
    [samples, historyWindow],
  );

  // A session history is evidence, not a live view: it is "live" only while its newest sample is fresh.
  const status = useMemo(() => {
    const newest = samples.reduce<TelemetrySample | null>(
      (best, sample) =>
        !best || Date.parse(sample.captured_at) > Date.parse(best.captured_at) ? sample : best,
      null,
    );
    return newest && isLiveSampleFresh(newest, effectiveNow, resolveLiveFreshness(newest)) ? "live" : "stale";
  }, [effectiveNow, samples]);

  const groups = useMemo(
    () =>
      resetDomain
        ? buildOverviewChartGroups({
            samples,
            status,
            xDomain: viewportDomain ?? resetDomain,
            hiddenSeriesKeys,
            soloSeriesKey,
          })
        : [],
    [hiddenSeriesKeys, resetDomain, samples, soloSeriesKey, status, viewportDomain],
  );

  if (!resetDomain || groups.length === 0) {
    return (
      <p className="p-4 text-xs text-slate-400" data-testid="session-temperature-history-empty">
        Для цієї сесії ще немає збережених вимірювань температури.
      </p>
    );
  }

  return (
    <div className="space-y-3 p-3" data-testid="session-temperature-history">
      {groups.map((group) => (
        <OverviewChartPanel
          key={group.id}
          group={group}
          rangeLabel="Період сесії"
          sharedCursorMs={sharedCursorMs}
          resetDomain={resetDomain}
          onSharedCursorChange={setSharedCursorMs}
          onXDomainChange={setViewportDomain}
          onResetView={() => setViewportDomain(null)}
          onToggleSeries={(seriesKey) => {
            setSoloSeriesKey(null);
            setHiddenSeriesKeys((current) => {
              const next = new Set(current);
              if (next.has(seriesKey)) next.delete(seriesKey);
              else next.add(seriesKey);
              return next;
            });
          }}
          onSoloSeries={(seriesKey) =>
            setSoloSeriesKey((current) => (current === seriesKey ? null : seriesKey))
          }
        />
      ))}
    </div>
  );
}
