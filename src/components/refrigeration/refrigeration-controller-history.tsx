"use client";

import { CalendarRange, LoaderCircle } from "lucide-react";
import { clsx } from "clsx";
import { useMemo, useState } from "react";

import { RefrigerationControllerChart } from "@/components/refrigeration/refrigeration-controller-chart";
import type { ChartXDomain } from "@/features/charts/domain";
import {
  buildEmbracoCompressorScene,
  buildEmbracoTemperatureScene,
} from "@/features/refrigeration/controller-chart";
import {
  EMBRACO_METRICS,
  type RefrigerationHistoryPreset,
} from "@/features/refrigeration/controller-monitoring";
import {
  buildControlStateTimeline,
  buildRelayTimeline,
  type TimelineInterval,
} from "@/features/refrigeration/controller-timeline";
import { calculateCompressorRuntimeDuty } from "@/features/refrigeration/compressor-runtime";
import type { RefrigerationControllerModel } from "@/features/refrigeration/use-refrigeration-controller";

const PRESETS: readonly { id: RefrigerationHistoryPreset; label: string }[] = [
  { id: "1h", label: "1 год" },
  { id: "12h", label: "12 год" },
  { id: "24h", label: "24 год" },
  { id: "custom", label: "Кастом" },
];

export function RefrigerationControllerHistory({ controller }: { controller: RefrigerationControllerModel }) {
  const [analysisSelection, setAnalysisSelection] = useState<{
    rangeKey: string;
    domain: ChartXDomain | null;
  }>({ rangeKey: "", domain: null });
  const rangeLabel =
    controller.preset === "custom"
      ? formatCustomRange(controller.range)
      : (PRESETS.find((item) => item.id === controller.preset)?.label ?? controller.preset);
  const loadedAnalysisDomain = useMemo<ChartXDomain>(
    () => ({ fromMs: controller.range.from.getTime(), toMs: controller.range.to.getTime() }),
    [controller.range],
  );
  const loadedAnalysisRangeKey = `${loadedAnalysisDomain.fromMs}:${loadedAnalysisDomain.toMs}`;
  const selectedAnalysisDomain =
    analysisSelection.rangeKey === loadedAnalysisRangeKey ? analysisSelection.domain : null;
  const setSelectedAnalysisDomain = (domain: ChartXDomain | null) => {
    setAnalysisSelection({ rangeKey: loadedAnalysisRangeKey, domain });
  };
  const analysisDomain = useMemo(
    () => clampAnalysisDomain(selectedAnalysisDomain, loadedAnalysisDomain),
    [loadedAnalysisDomain, selectedAnalysisDomain],
  );
  const analysisRangeLabel = formatAnalysisRange(analysisDomain);

  const temperatureScene = useMemo(
    () =>
      buildEmbracoTemperatureScene(controller.history, controller.range, controller.latest?.online ?? false),
    [controller.history, controller.latest?.online, controller.range],
  );
  const compressorScene = useMemo(
    () =>
      buildEmbracoCompressorScene(controller.history, controller.range, controller.latest?.online ?? false),
    [controller.history, controller.latest?.online, controller.range],
  );
  const duty = useMemo(
    () =>
      calculateCompressorRuntimeDuty(
        (controller.history.get(EMBRACO_METRICS.compressorSpeed) ?? []).map((sample) => ({
          capturedAt: sample.captured_at,
          value: sample.value,
          quality: sample.quality,
        })),
        {
          from: new Date(analysisDomain.fromMs).toISOString(),
          to: new Date(analysisDomain.toMs).toISOString(),
        },
      ),
    [analysisDomain, controller.history],
  );
  const stateTimeline = useMemo(
    () =>
      buildControlStateTimeline(controller.history.get(EMBRACO_METRICS.controlState) ?? [], controller.range),
    [controller.history, controller.range],
  );
  const relayTimelines = useMemo(
    () =>
      [0, 1, 2, 3].map((relay) =>
        buildRelayTimeline(controller.history.get(EMBRACO_METRICS.relays) ?? [], relay, controller.range),
      ),
    [controller.history, controller.range],
  );

  if (!controller.binding) {
    return <EmptyHistory text="Для графіків спочатку потрібна прив’язка перевіреного контролера." />;
  }

  return (
    <div className="grid gap-3 xl:gap-4" data-testid="refrigeration-controller-history">
      <section className="flex flex-wrap items-center gap-2 rounded-2xl border border-white/[0.08] bg-[#081a32] p-3">
        <div className="mr-auto flex items-center gap-2 px-1 text-xs text-slate-400">
          <CalendarRange className="h-4 w-4 text-cyan-300" />
          Період історії
        </div>
        {PRESETS.map((item) => (
          <button
            key={item.id}
            type="button"
            aria-pressed={controller.preset === item.id}
            onClick={() => controller.setPreset(item.id)}
            className={clsx(
              "min-h-9 rounded-xl border px-3 text-xs transition",
              controller.preset === item.id
                ? "border-cyan-300/25 bg-cyan-400/10 text-cyan-100"
                : "border-white/[0.08] bg-white/[0.025] text-slate-400 hover:text-white",
            )}
          >
            {item.label}
          </button>
        ))}
        {controller.preset === "custom" ? (
          <div className="flex w-full flex-wrap items-center gap-2 border-t border-white/[0.07] pt-3 sm:w-auto sm:border-t-0 sm:pt-0">
            <DateTimeInput
              label="Від"
              value={controller.customRange.from}
              onChange={(from) => {
                if (from < controller.customRange.to) {
                  controller.setCustomRange({ ...controller.customRange, from });
                }
              }}
            />
            <DateTimeInput
              label="До"
              value={controller.customRange.to}
              onChange={(to) => {
                if (controller.customRange.from < to) {
                  controller.setCustomRange({ ...controller.customRange, to });
                }
              }}
            />
          </div>
        ) : null}
      </section>

      {controller.historyLoading ? (
        <section className="grid min-h-48 place-items-center rounded-2xl border border-white/[0.08] bg-[#081a32]">
          <div className="text-center text-xs text-slate-500">
            <LoaderCircle className="mx-auto mb-2 h-5 w-5 animate-spin text-cyan-300" />
            Завантаження persisted history…
          </div>
        </section>
      ) : null}
      {controller.historyError ? (
        <p
          role="alert"
          className="rounded-xl border border-rose-400/20 bg-rose-400/[0.06] px-3 py-2 text-xs text-rose-200"
        >
          {controller.historyError}
        </p>
      ) : null}

      <section
        className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-white/[0.08] bg-[#081a32] px-4 py-3"
        data-testid="compressor-analysis-range"
      >
        <div className="min-w-0">
          <p className="text-[9px] tracking-[0.14em] text-slate-500 uppercase">Інтервал розрахунку</p>
          <p className="mt-1 text-xs text-slate-200 tabular-nums">{analysisRangeLabel}</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-slate-500">
            {selectedAnalysisDomain ? "Вибраний відрізок графіка" : "Повний період"}
          </span>
          {selectedAnalysisDomain ? (
            <button
              type="button"
              onClick={() => setSelectedAnalysisDomain(null)}
              className="min-h-9 rounded-xl border border-white/10 px-3 text-xs text-slate-200 outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
            >
              Скинути вибір
            </button>
          ) : null}
        </div>
      </section>

      <div className="grid gap-3 sm:grid-cols-3">
        <DutyCard
          label="Коефіцієнт роботи"
          value={duty.dutyPercent === null ? "—" : `${duty.dutyPercent.toFixed(1)} %`}
        />
        <DutyCard label="Робота" value={formatDuration(duty.runningMs)} />
        <DutyCard
          label="Покриття"
          value={`${duty.coveragePercent.toFixed(1)} %`}
          meta={duty.continuityBreaks > 0 ? `Прогалин: ${duty.continuityBreaks}` : "Без розривів"}
        />
      </div>

      <RefrigerationControllerChart
        title="Температури контролера"
        context="Cabinet · Evaporator · Condenser · Setpoint"
        rangeLabel={rangeLabel}
        scene={temperatureScene}
        emptyMessage="Температурний scale ще не підтверджений або в обраному періоді немає valid °C даних. Raw регістри не візуалізуються як температура."
      />
      <RefrigerationControllerChart
        title="Швидкість компресора"
        context="Embraco Sync · rpm"
        rangeLabel={analysisRangeLabel}
        scene={compressorScene}
        emptyMessage="У вибраному періоді немає валідної історії швидкості компресора."
        viewportDomain={selectedAnalysisDomain}
        onViewportDomainChange={setSelectedAnalysisDomain}
        showRangeSlider
      />

      <section className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-4 sm:p-5">
        <p className="text-[10px] tracking-[0.16em] text-cyan-300 uppercase">Operating timeline</p>
        <h2 className="mt-1 text-lg font-semibold text-white">Режими та реле</h2>
        <div className="mt-4 grid gap-3">
          <TimelineRow label="State" intervals={stateTimeline} range={controller.range} />
          {relayTimelines.map((intervals, index) => (
            <TimelineRow
              key={index}
              label={`Relay ${index + 1}`}
              intervals={intervals}
              range={controller.range}
              activeOnly
            />
          ))}
        </div>
      </section>

      <AlarmHistory controller={controller} />
    </div>
  );
}

function TimelineRow({
  label,
  intervals,
  range,
  activeOnly = false,
}: {
  label: string;
  intervals: readonly TimelineInterval[];
  range: { from: Date; to: Date };
  activeOnly?: boolean;
}) {
  const span = Math.max(1, range.to.getTime() - range.from.getTime());
  const visible = activeOnly ? intervals.filter((item) => item.active) : intervals;
  return (
    <div className="grid grid-cols-[72px_minmax(0,1fr)] items-center gap-3">
      <span className="text-[10px] text-slate-500">{label}</span>
      <div className="relative h-8 overflow-hidden rounded-lg border border-white/[0.07] bg-[#06142a]">
        {visible.map((item, index) => {
          const left = ((item.fromMs - range.from.getTime()) / span) * 100;
          const width = ((item.toMs - item.fromMs) / span) * 100;
          return (
            <span
              key={`${item.fromMs}-${index}`}
              title={item.label}
              className={clsx(
                "absolute top-1 bottom-1 min-w-px rounded",
                item.active ? "bg-cyan-400/55" : "bg-slate-500/25",
              )}
              style={{ left: `${Math.max(0, left)}%`, width: `${Math.max(0.15, width)}%` }}
            />
          );
        })}
        {visible.length === 0 ? (
          <span className="absolute inset-0 grid place-items-center text-[9px] text-slate-700">
            No observed intervals
          </span>
        ) : null}
      </div>
    </div>
  );
}

function AlarmHistory({ controller }: { controller: RefrigerationControllerModel }) {
  const samples = controller.history.get(EMBRACO_METRICS.alarms) ?? [];
  const events = samples
    .filter((sample) => sample.quality === "valid" && (sample.value ?? 0) > 0)
    .slice(-8)
    .reverse();
  return (
    <section className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-4 sm:p-5">
      <p className="text-[10px] tracking-[0.16em] text-cyan-300 uppercase">Alarm events</p>
      <h2 className="mt-1 text-lg font-semibold text-white">Тривоги за період</h2>
      {events.length === 0 ? (
        <p className="mt-4 text-xs text-slate-500">
          У валідних sample за цей інтервал активні alarm bits не зафіксовані.
        </p>
      ) : (
        <div className="mt-4 grid gap-2">
          {events.map((sample) => (
            <div
              key={sample.event_id}
              className="flex items-center justify-between gap-3 rounded-xl border border-rose-400/15 bg-rose-400/[0.05] px-3 py-2 text-xs"
            >
              <span className="text-rose-200">Alarm bitfield {Math.trunc(sample.value ?? 0)}</span>
              <time className="text-[10px] text-slate-500">
                {new Date(sample.captured_at).toLocaleString("uk-UA")}
              </time>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function DutyCard({ label, value, meta }: { label: string; value: string; meta?: string }) {
  return (
    <article className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-4">
      <p className="text-[9px] tracking-[0.14em] text-slate-500 uppercase">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-white tabular-nums">{value}</p>
      {meta ? <p className="mt-1 text-[10px] text-slate-500">{meta}</p> : null}
    </article>
  );
}

function DateTimeInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: Date;
  onChange: (value: Date) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-[10px] text-slate-500">
      {label}
      <input
        type="datetime-local"
        value={toLocalInput(value)}
        onChange={(event) => {
          const next = new Date(event.target.value);
          if (Number.isFinite(next.getTime())) onChange(next);
        }}
        className="min-h-9 rounded-xl border border-white/[0.08] bg-[#06142a] px-2 text-xs text-slate-200 outline-none focus:border-cyan-300/30"
      />
    </label>
  );
}

function toLocalInput(value: Date): string {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function clampAnalysisDomain(domain: ChartXDomain | null, loaded: ChartXDomain): ChartXDomain {
  if (!domain) return loaded;
  const fromMs = Math.max(loaded.fromMs, Math.min(domain.fromMs, loaded.toMs));
  const toMs = Math.min(loaded.toMs, Math.max(domain.toMs, loaded.fromMs));
  return toMs > fromMs ? { fromMs, toMs } : loaded;
}

function formatAnalysisRange(domain: ChartXDomain): string {
  return `${new Date(domain.fromMs).toLocaleString("uk-UA")} → ${new Date(domain.toMs).toLocaleString("uk-UA")}`;
}

function formatDuration(milliseconds: number): string {
  if (!Number.isFinite(milliseconds) || milliseconds <= 0) return "0 хв";
  const totalMinutes = Math.floor(milliseconds / 60_000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours > 0 ? `${hours} год ${minutes} хв` : `${minutes} хв`;
}

function formatCustomRange(range: { from: Date; to: Date }): string {
  return `${range.from.toLocaleString("uk-UA")} → ${range.to.toLocaleString("uk-UA")}`;
}

function EmptyHistory({ text }: { text: string }) {
  return (
    <section className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-8 text-center text-xs text-slate-500">
      {text}
    </section>
  );
}
