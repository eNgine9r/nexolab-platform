"use client";

import { useMemo, useState } from "react";

import { ChartRendererHost } from "@/components/charts/chart-renderer-host";
import { ChartShell } from "@/components/charts/chart-shell";
import type { ChartRendererScene } from "@/features/charts";
import { chartSeriesKey, type ChartCursorInspection, type ChartXDomain } from "@/features/charts/domain";
import { EChartsRendererAdapter } from "@/features/charts/echarts-adapter";

export function RefrigerationControllerChart({
  title,
  context,
  rangeLabel,
  scene: baseScene,
  emptyMessage,
}: {
  title: string;
  context: string;
  rangeLabel: string;
  scene: ChartRendererScene;
  emptyMessage: string;
}) {
  const adapter = useMemo(() => new EChartsRendererAdapter(), []);
  const [inspection, setInspection] = useState<ChartCursorInspection | null>(null);
  const [sharedCursorMs, setSharedCursorMs] = useState<number | null>(null);
  const [viewportDomain, setViewportDomain] = useState<ChartXDomain | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());
  const [solo, setSolo] = useState<string | null>(null);
  const scene = useMemo(
    () => ({
      ...baseScene,
      xDomain: viewportDomain ?? baseScene.xDomain,
      series: baseScene.series.map((series) => {
        const key = chartSeriesKey(series.identity);
        return { ...series, visible: solo ? key === solo : !hidden.has(key) };
      }),
    }),
    [baseScene, hidden, solo, viewportDomain],
  );

  if (baseScene.series.length === 0) {
    return (
      <section className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-5">
        <p className="text-[10px] tracking-[0.16em] text-cyan-300 uppercase">{context}</p>
        <h2 className="mt-1 text-lg font-semibold text-white">{title}</h2>
        <div className="mt-4 rounded-xl border border-dashed border-white/10 bg-[#06142a]/70 p-8 text-center text-xs text-slate-500">
          {emptyMessage}
        </div>
      </section>
    );
  }

  return (
    <ChartShell
      title={title}
      context={context}
      selectedRange={rangeLabel}
      series={scene.series}
      inspection={inspection}
      onToggleSeries={(key) => {
        setSolo(null);
        setHidden((current) => {
          const next = new Set(current);
          if (next.has(key)) next.delete(key);
          else next.add(key);
          return next;
        });
      }}
      onSoloSeries={(key) => setSolo((current) => (current === key ? null : key))}
      onResetZoom={() => {
        adapter.resetZoom();
        setViewportDomain(null);
      }}
    >
      <ChartRendererHost
        adapter={adapter}
        scene={scene}
        reducedMotion
        sharedCursorMs={sharedCursorMs}
        interactionDomain={baseScene.xDomain}
        onCursor={(next) => {
          setInspection(next);
          setSharedCursorMs(next?.timestampMs ?? null);
        }}
        onXDomainChange={setViewportDomain}
      />
    </ChartShell>
  );
}
