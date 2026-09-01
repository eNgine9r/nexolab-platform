"use client";

import { CalendarRange, Download, LoaderCircle } from "lucide-react";
import { clsx } from "clsx";
import { useMemo, useState } from "react";

import { RefrigerationControllerChart } from "@/components/refrigeration/refrigeration-controller-chart";
import { triggerBrowserBlobDownload } from "@/features/live-dashboards/browser-download";
import type { ChartXDomain } from "@/features/charts/domain";
import {
  buildEmbracoCompressorScene,
  buildEmbracoTemperatureScene,
} from "@/features/refrigeration/controller-chart";
import {
  buildControllerAnalysisCsv,
  controllerAnalysisCsvFilename,
} from "@/features/refrigeration/controller-history-export";
import {
  EMBRACO_METRICS,
  type RefrigerationHistoryPreset,
} from "@/features/refrigeration/controller-monitoring";
import {
  buildControlStateTimeline,
  buildRelayTimeline,
  buildRelayTransitions,
  type RelayTransition,
  type TimelineInterval,
} from "@/features/refrigeration/controller-timeline";
import {
  buildCompressorStartEvents,
  calculateCompressorRuntimeDuty,
} from "@/features/refrigeration/compressor-runtime";
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
  const analysisRange = useMemo(
    () => ({ from: new Date(analysisDomain.fromMs), to: new Date(analysisDomain.toMs) }),
    [analysisDomain],
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
  const compressorSamples = useMemo(
    () =>
      (controller.history.get(EMBRACO_METRICS.compressorSpeed) ?? []).map((sample) => ({
        capturedAt: sample.captured_at,
        value: sample.value,
        quality: sample.quality,
        eventId: sample.event_id,
      })),
    [controller.history],
  );
  const compressorAnalysisRange = useMemo(
    () => ({
      from: new Date(analysisDomain.fromMs).toISOString(),
      to: new Date(analysisDomain.toMs).toISOString(),
    }),
    [analysisDomain],
  );
  const duty = useMemo(
    () => calculateCompressorRuntimeDuty(compressorSamples, compressorAnalysisRange),
    [compressorAnalysisRange, compressorSamples],
  );
  const compressorStarts = useMemo(
    () => buildCompressorStartEvents(compressorSamples, compressorAnalysisRange),
    [compressorAnalysisRange, compressorSamples],
  );
  const stateTimeline = useMemo(
    () =>
      buildControlStateTimeline(controller.history.get(EMBRACO_METRICS.controlState) ?? [], analysisRange),
    [analysisRange, controller.history],
  );
  const relayTimelines = useMemo(
    () =>
      [0, 1, 2, 3].map((relay) =>
        buildRelayTimeline(controller.history.get(EMBRACO_METRICS.relays) ?? [], relay, analysisRange),
      ),
    [analysisRange, controller.history],
  );
  const relayTransitions = useMemo(
    () =>
      [0, 1, 2, 3]
        .flatMap((relay) =>
          buildRelayTransitions(controller.history.get(EMBRACO_METRICS.relays) ?? [], relay, analysisRange),
        )
        .sort((left, right) => left.observedAtMs - right.observedAtMs),
    [analysisRange, controller.history],
  );

  const exportSelectedInterval = () => {
    if (!controller.binding) return;
    const csv = buildControllerAnalysisCsv({
      history: controller.history,
      range: analysisDomain,
      duty,
      compressorStarts,
      relayTransitions,
      equipmentId: controller.binding.controllerEquipmentId,
      timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
    });
    triggerBrowserBlobDownload({
      blob: new Blob([csv], { type: "text/csv;charset=utf-8" }),
      filename: controllerAnalysisCsvFilename(controller.binding.controllerEquipmentId, analysisDomain),
    });
  };

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
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[10px] text-slate-500">
            {selectedAnalysisDomain ? "Вибраний відрізок графіка" : "Повний період"}
          </span>
          <button
            type="button"
            onClick={exportSelectedInterval}
            data-testid="export-controller-analysis-csv"
            className="inline-flex min-h-9 items-center gap-2 rounded-xl border border-cyan-300/20 bg-cyan-400/[0.06] px-3 text-xs text-cyan-100 outline-none hover:bg-cyan-400/10 focus-visible:ring-2 focus-visible:ring-cyan-300"
          >
            <Download className="h-3.5 w-3.5" />
            Export CSV
          </button>
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

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
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
        <DutyCard
          label="Пуски компресора"
          value={String(compressorStarts.length)}
          meta="Підтверджені переходи RPM 0 → >0"
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
        <p className="mt-1 text-[10px] text-slate-500">
          Усі digital lanes синхронізовані з поточним інтервалом розрахунку.
        </p>
        <div className="mt-4 grid gap-3" data-testid="relay-analysis-lanes">
          <TimelineRow label="State" intervals={stateTimeline} range={analysisRange} />
          {relayTimelines.map((intervals, index) => (
            <TimelineRow
              key={index}
              label={`Relay ${index + 1}`}
              intervals={intervals}
              range={analysisRange}
            />
          ))}
        </div>
        <RelayTransitionJournal transitions={relayTransitions} />
      </section>

      <AlarmHistory controller={controller} range={analysisRange} />
    </div>
  );
}

function TimelineRow({
  label,
  intervals,
  range,
}: {
  label: string;
  intervals: readonly TimelineInterval[];
  range: { from: Date; to: Date };
}) {
  const span = Math.max(1, range.to.getTime() - range.from.getTime());
  return (
    <div className="grid grid-cols-[72px_minmax(0,1fr)] items-center gap-3">
      <span className="text-[10px] text-slate-500">{label}</span>
      <div className="relative h-8 overflow-hidden rounded-lg border border-white/[0.07] bg-[#06142a]">
        {intervals.map((item, index) => {
          const left = ((item.fromMs - range.from.getTime()) / span) * 100;
          const width = ((item.toMs - item.fromMs) / span) * 100;
          return (
            <span
              key={`${item.fromMs}-${index}`}
              title={`${item.label} · ${formatObservedTime(item.fromMs)} → ${formatObservedTime(item.toMs)}`}
              className={clsx(
                "absolute top-1 bottom-1 min-w-px rounded",
                item.active ? "bg-cyan-400/55" : "bg-slate-500/25",
              )}
              style={{ left: `${Math.max(0, left)}%`, width: `${Math.max(0.15, width)}%` }}
            />
          );
        })}
        {intervals.length === 0 ? (
          <span className="absolute inset-0 grid place-items-center text-[9px] text-slate-700">
            No observed intervals
          </span>
        ) : null}
      </div>
    </div>
  );
}

function RelayTransitionJournal({ transitions }: { transitions: readonly RelayTransition[] }) {
  return (
    <div className="mt-5 border-t border-white/[0.07] pt-4" data-testid="relay-transition-journal">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="text-[9px] tracking-[0.14em] text-slate-500 uppercase">Relay traceability</p>
          <h3 className="mt-1 text-sm font-semibold text-white">Журнал перемикань реле</h3>
        </div>
        <span className="text-[10px] text-slate-500">Подій: {transitions.length}</span>
      </div>
      <p className="mt-2 text-[10px] leading-4 text-slate-500">
        Час події — перший зафіксований sample нового стану; фізичне перемикання відбулося між попереднім і
        поточним опитуванням.
      </p>
      {transitions.length === 0 ? (
        <p className="mt-3 rounded-xl border border-dashed border-white/[0.08] bg-[#06142a]/60 px-3 py-3 text-xs text-slate-600">
          У вибраному інтервалі підтверджених перемикань реле немає.
        </p>
      ) : (
        <div className="mt-3 max-h-64 overflow-auto rounded-xl border border-white/[0.07]">
          {transitions.map((transition) => (
            <div
              key={`${transition.relayIndex}-${transition.eventId}-${transition.observedAtMs}`}
              className="grid gap-1 border-b border-white/[0.06] px-3 py-2.5 last:border-b-0 sm:grid-cols-[88px_84px_minmax(0,1fr)] sm:items-center"
            >
              <span className="text-xs font-medium text-slate-200">Relay {transition.relayIndex + 1}</span>
              <span
                className={clsx(
                  "w-fit rounded-md border px-2 py-1 text-[10px] font-semibold",
                  transition.toState
                    ? "border-cyan-300/20 bg-cyan-400/[0.08] text-cyan-100"
                    : "border-white/10 bg-white/[0.03] text-slate-400",
                )}
              >
                {transition.fromState ? "ON" : "OFF"} → {transition.toState ? "ON" : "OFF"}
              </span>
              <div className="min-w-0 text-[10px] text-slate-500 tabular-nums">
                <p>
                  Зафіксовано:{" "}
                  <time className="text-slate-300">{formatObservedTime(transition.observedAtMs)}</time>
                </p>
                <p className="truncate" title={transition.previousEventId}>
                  Попередній sample: {formatObservedTime(transition.previousObservedAtMs)} ·{" "}
                  {transition.previousEventId}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AlarmHistory({
  controller,
  range,
}: {
  controller: RefrigerationControllerModel;
  range: { from: Date; to: Date };
}) {
  const samples = controller.history.get(EMBRACO_METRICS.alarms) ?? [];
  const fromMs = range.from.getTime();
  const toMs = range.to.getTime();
  const events = samples
    .filter((sample) => {
      const capturedAtMs = Date.parse(sample.captured_at);
      return (
        sample.quality === "valid" &&
        (sample.value ?? 0) > 0 &&
        Number.isFinite(capturedAtMs) &&
        capturedAtMs >= fromMs &&
        capturedAtMs <= toMs
      );
    })
    .slice(-8)
    .reverse();
  return (
    <section className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-4 sm:p-5">
      <p className="text-[10px] tracking-[0.16em] text-cyan-300 uppercase">Alarm events</p>
      <h2 className="mt-1 text-lg font-semibold text-white">Тривоги за вибраний інтервал</h2>
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

function formatObservedTime(timestampMs: number): string {
  return new Date(timestampMs).toLocaleString("uk-UA");
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
