"use client";

import { fromZonedInputValue, toZonedInputValue } from "@/features/display-time/zoned-input";
import { formatOperationalTimestamp } from "@/features/display-time/format";
import { useDisplayTimeZone } from "@/hooks/use-display-time-zone";

import { CalendarRange, Download, LoaderCircle } from "lucide-react";
import { clsx } from "clsx";
import { useMemo, useState } from "react";

import { DashboardAlertEvents } from "@/components/live-dashboards/dashboard-alert-events";
import { applyAlertAnnotations } from "@/features/charts/alert-events";
import { useDashboardAlertEvents } from "@/features/live-dashboards/use-dashboard-alert-events";
import { DashboardIntervalStatistics } from "@/components/live-dashboards/dashboard-interval-statistics";
import { ChartDensityControl } from "@/components/charts/chart-density-control";
import {
  readStoredChartDensity,
  resolveChartPointBudget,
  storeChartDensity,
  type ChartDensityMode,
} from "@/features/charts/density";
import { RefrigerationControllerChart } from "@/components/refrigeration/refrigeration-controller-chart";
import { triggerBrowserBlobDownload } from "@/features/live-dashboards/browser-download";
import type { ChartXDomain } from "@/features/charts/domain";
import { CHART_GRID_INSETS } from "@/features/charts/echarts-adapter";
import {
  buildEmbracoCompressorScene,
  buildEmbracoTemperatureStatisticsRows,
  buildEmbracoOperatorCelsiusScene,
  buildEmbracoProbeRawScene,
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
  buildCompressorTimeline,
  buildControlStateTimeline,
  buildUnknownTimeline,
  buildDefrostTimeline,
  buildRelayTimeline,
  buildRelayTransitions,
  clipTimeline,
  summarizeActiveTimeline,
  type RelayTransition,
  type TimelineInterval,
} from "@/features/refrigeration/controller-timeline";
import {
  buildCompressorStartEvents,
  calculateCompressorRuntimeDuty,
} from "@/features/refrigeration/compressor-runtime";
import type { RefrigerationControllerModel } from "@/features/refrigeration/use-refrigeration-controller";

const PRESETS: readonly { id: RefrigerationHistoryPreset; label: string }[] = [
  { id: "1h", label: "1 година" },
  { id: "6h", label: "6 годин" },
  { id: "24h", label: "24 години" },
  { id: "7d", label: "7 днів" },
  { id: "custom", label: "Власний період" },
];

/** Upper bound of simultaneously plotted series: 2 operator-°C pairs, 2 raw probes, compressor. */
const REFRIGERATION_PLOTTED_SERIES = 7;

export function RefrigerationControllerHistory({ controller }: { controller: RefrigerationControllerModel }) {
  const displayTimeZone = useDisplayTimeZone();
  const [cursorSelection, setCursorSelection] = useState<{
    rangeKey: string;
    timestampMs: number | null;
  }>({ rangeKey: "", timestampMs: null });
  const [analysisSelection, setAnalysisSelection] = useState<{
    rangeKey: string;
    domain: ChartXDomain | null;
  }>({ rangeKey: "", domain: null });
  const [viewportSelection, setViewportSelection] = useState<{
    rangeKey: string;
    domain: ChartXDomain | null;
  }>({ rangeKey: "", domain: null });
  const rangeLabel =
    controller.preset === "custom"
      ? formatCustomRange(controller.range, displayTimeZone)
      : (PRESETS.find((item) => item.id === controller.preset)?.label ?? controller.preset);
  const loadedAnalysisDomain = useMemo<ChartXDomain>(
    () => ({ fromMs: controller.range.from.getTime(), toMs: controller.range.to.getTime() }),
    [controller.range],
  );
  const loadedAnalysisRangeKey = `${controller.binding?.id}:${loadedAnalysisDomain.fromMs}:${loadedAnalysisDomain.toMs}`;
  const viewportDomain = useMemo(
    () =>
      clampAnalysisDomain(
        viewportSelection.rangeKey === loadedAnalysisRangeKey ? viewportSelection.domain : null,
        loadedAnalysisDomain,
      ),
    [loadedAnalysisDomain, loadedAnalysisRangeKey, viewportSelection],
  );
  const setViewportDomain = (domain: ChartXDomain | null) => {
    setViewportSelection({ rangeKey: loadedAnalysisRangeKey, domain });
    setSharedCursorMs(null);
  };
  const viewportRange = useMemo(
    () => ({ from: new Date(viewportDomain.fromMs), to: new Date(viewportDomain.toMs) }),
    [viewportDomain],
  );
  const sharedCursorMs =
    cursorSelection.rangeKey === loadedAnalysisRangeKey &&
    cursorSelection.timestampMs !== null &&
    cursorSelection.timestampMs >= viewportDomain.fromMs &&
    cursorSelection.timestampMs <= viewportDomain.toMs
      ? cursorSelection.timestampMs
      : null;
  const setSharedCursorMs = (timestampMs: number | null) => {
    setCursorSelection((current) =>
      current.rangeKey === loadedAnalysisRangeKey && current.timestampMs === timestampMs
        ? current
        : { rangeKey: loadedAnalysisRangeKey, timestampMs },
    );
  };
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
  const analysisRangeLabel = formatAnalysisRange(analysisDomain, displayTimeZone);
  const chartRangeLabel =
    viewportDomain.fromMs === loadedAnalysisDomain.fromMs && viewportDomain.toMs === loadedAnalysisDomain.toMs
      ? rangeLabel
      : formatAnalysisRange(viewportDomain, displayTimeZone);
  const analysisUnavailableLabel = controller.historyLoading
    ? "Завантаження історії…"
    : controller.historyError
      ? "Історія недоступна"
      : null;
  const analysisReady = analysisUnavailableLabel === null;

  const [density, setDensity] = useState<ChartDensityMode>(() => readStoredChartDensity("refrigeration"));
  const densityResolution = useMemo(
    () => resolveChartPointBudget(density, REFRIGERATION_PLOTTED_SERIES),
    [density],
  );
  const pointsPerSeries = densityResolution.perSeries;
  const temperatureScene = useMemo(
    () =>
      buildEmbracoOperatorCelsiusScene(
        controller.history,
        controller.range,
        controller.latest?.online ?? false,
        controller.binding?.controllerEquipmentId ?? "",
        pointsPerSeries,
      ),
    [
      controller.history,
      controller.latest?.online,
      controller.range,
      controller.binding?.controllerEquipmentId,
      pointsPerSeries,
    ],
  );
  const probeRawScene = useMemo(
    () =>
      buildEmbracoProbeRawScene(
        controller.history,
        controller.range,
        controller.latest?.online ?? false,
        pointsPerSeries,
      ),
    [controller.history, controller.latest?.online, controller.range, pointsPerSeries],
  );
  const compressorScene = useMemo(
    () =>
      buildEmbracoCompressorScene(
        controller.history,
        controller.range,
        controller.latest?.online ?? false,
        pointsPerSeries,
      ),
    [controller.history, controller.latest?.online, controller.range, pointsPerSeries],
  );
  const alertEvents = useDashboardAlertEvents({
    enabled: controller.binding !== null,
    rangeKey: `refrigeration:${controller.binding?.controllerEquipmentId ?? ""}:${controller.range.from.toISOString()}:${controller.range.to.toISOString()}`,
  });
  // Open alerts extend to the end of the shown range (deterministic, no wall clock in render).
  const evaluationNowMs = controller.range.to.getTime();
  const annotatedTemperatureScene = useMemo(
    () => applyAlertAnnotations(temperatureScene, alertEvents.alerts, evaluationNowMs),
    [alertEvents.alerts, evaluationNowMs, temperatureScene],
  );
  const annotatedProbeRawScene = useMemo(
    () => applyAlertAnnotations(probeRawScene, alertEvents.alerts, evaluationNowMs),
    [alertEvents.alerts, evaluationNowMs, probeRawScene],
  );
  const annotatedCompressorScene = useMemo(
    () => applyAlertAnnotations(compressorScene, alertEvents.alerts, evaluationNowMs),
    [alertEvents.alerts, evaluationNowMs, compressorScene],
  );
  // Exact statistics come from the RAW history, not from the reduced chart series (#1675).
  const temperatureStatisticsRows = useMemo(
    () => buildEmbracoTemperatureStatisticsRows(controller.history, temperatureScene, viewportDomain),
    [controller.history, temperatureScene, viewportDomain],
  );
  const displayedPoints = useMemo(
    () =>
      [temperatureScene, probeRawScene, compressorScene].reduce(
        (total, scene) =>
          total +
          scene.series.reduce(
            (sum, entry) =>
              sum + entry.segments.reduce((points, segment) => points + segment.points.length, 0),
            0,
          ),
        0,
      ),
    [compressorScene, probeRawScene, temperatureScene],
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
  // #1829: lanes are built once per loaded history over the loaded range; a zoom/pan only clips
  // their intervals (identical to building them for the viewport, without re-reading raw history).
  const fullStateTimeline = useMemo(
    () =>
      buildControlStateTimeline(controller.history.get(EMBRACO_METRICS.controlState) ?? [], controller.range),
    [controller.history, controller.range],
  );
  const fullStateTimelineWithUnknown = useMemo(
    () =>
      [
        ...fullStateTimeline,
        ...buildUnknownTimeline(controller.history.get(EMBRACO_METRICS.controlState) ?? [], controller.range),
      ].sort((left, right) => left.fromMs - right.fromMs),
    [fullStateTimeline, controller.history, controller.range],
  );
  const stateTimelineWithUnknown = useMemo(
    () => clipTimeline(fullStateTimelineWithUnknown, viewportRange),
    [fullStateTimelineWithUnknown, viewportRange],
  );
  const defrostTimeline = useMemo(
    () => buildDefrostTimeline(controller.history.get(EMBRACO_METRICS.controlState) ?? [], controller.range),
    [controller.history, controller.range],
  );
  const fullCompressorLane = useMemo(() => {
    const speed = controller.history.get(EMBRACO_METRICS.compressorSpeed) ?? [];
    return [
      ...buildCompressorTimeline(speed, controller.range),
      ...buildUnknownTimeline(speed, controller.range),
    ].sort((left, right) => left.fromMs - right.fromMs);
  }, [controller.history, controller.range]);
  const compressorLane = useMemo(
    () => clipTimeline(fullCompressorLane, viewportRange),
    [fullCompressorLane, viewportRange],
  );
  const defrostLane = useMemo(
    () =>
      [
        ...defrostTimeline,
        ...buildUnknownTimeline(controller.history.get(EMBRACO_METRICS.controlState) ?? [], controller.range),
      ].sort((left, right) => left.fromMs - right.fromMs),
    [defrostTimeline, controller.history, controller.range],
  );
  const defrost = useMemo(
    () => summarizeActiveTimeline(defrostTimeline, analysisRange),
    [defrostTimeline, analysisRange],
  );
  const fullRelayTimelines = useMemo(() => {
    const relays = controller.history.get(EMBRACO_METRICS.relays) ?? [];
    const unknown = buildUnknownTimeline(relays, controller.range);
    return [0, 1, 2, 3].map((relay) =>
      [...buildRelayTimeline(relays, relay, controller.range), ...unknown].sort(
        (left, right) => left.fromMs - right.fromMs,
      ),
    );
  }, [controller.history, controller.range]);
  const relayTimelines = useMemo(
    () => fullRelayTimelines.map((timeline) => clipTimeline(timeline, viewportRange)),
    [fullRelayTimelines, viewportRange],
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

  const chartInteractions = {
    sharedCursorMs,
    onSharedCursorChange: setSharedCursorMs,
    rangeSelection: selectedAnalysisDomain,
    onRangeSelectionChange: setSelectedAnalysisDomain,
    viewportDomain,
    onViewportChange: setViewportDomain,
  };

  const exportSelectedInterval = () => {
    if (!controller.binding || !analysisReady) return;
    const csv = buildControllerAnalysisCsv({
      history: controller.history,
      range: analysisDomain,
      duty,
      compressorStarts,
      relayTransitions,
      equipmentId: controller.binding.controllerEquipmentId,
      timeZone: displayTimeZone,
    });
    triggerBrowserBlobDownload({
      blob: new Blob([csv], { type: "text/csv;charset=utf-8" }),
      filename: controllerAnalysisCsvFilename(controller.binding.controllerEquipmentId, analysisDomain),
    });
  };

  if (!controller.binding) {
    return <EmptyHistory text="Для графіків спочатку потрібна прив’язка перевіреного контролера." />;
  }

  const timelineLanes = (
    <section className="mt-2 border-t border-white/[0.07] pt-3">
      <h2 className="text-sm font-semibold text-white">Режими та реле</h2>
      <p className="mt-1 text-xs text-slate-400">Позначка на доріжках відповідає часу курсора графіка.</p>
      <ul
        className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-slate-400"
        data-testid="timeline-state-legend"
        aria-label="Позначення станів доріжок"
      >
        <li>OFF — вимкнено</li>
        <li>ON — увімкнено (компресор: швидкість &gt; 0 об/хв)</li>
        <li>Невідомо (штрихування) — опитування було, але валідного стану немає</li>
        <li>Немає даних (порожньо) — опитування відсутнє</li>
      </ul>
      <div
        className="mt-4 grid gap-2"
        style={{ paddingRight: CHART_GRID_INSETS.right }}
        data-testid="relay-analysis-lanes"
        data-chart-x-domain-from-ms={viewportDomain.fromMs}
        data-chart-x-domain-to-ms={viewportDomain.toMs}
      >
        <TimelineRow
          label="Режим"
          intervals={stateTimelineWithUnknown}
          range={viewportRange}
          cursorMs={sharedCursorMs}
          selection={selectedAnalysisDomain}
        />
        <TimelineRow
          label="Компресор"
          intervals={compressorLane}
          range={viewportRange}
          cursorMs={sharedCursorMs}
          selection={selectedAnalysisDomain}
          binary
        />
        <TimelineRow
          label="Відтайка"
          intervals={defrostLane}
          range={viewportRange}
          cursorMs={sharedCursorMs}
          selection={selectedAnalysisDomain}
          binary
        />
        {relayTimelines.map((intervals, index) => (
          <TimelineRow
            key={index}
            label={`Relay ${index + 1}`}
            intervals={intervals}
            range={viewportRange}
            cursorMs={sharedCursorMs}
            selection={selectedAnalysisDomain}
            binary
          />
        ))}
      </div>
    </section>
  );

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

      <section className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-3">
        <ChartDensityControl
          mode={density}
          resolution={densityResolution}
          onChange={(next) => {
            setDensity(next);
            storeChartDensity("refrigeration", next);
          }}
          displayedPoints={displayedPoints}
          availableMeasurements={null}
        />
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
          <p className="mt-1 text-[10px] text-slate-500">
            На графіку температури або компресора затисніть ліву кнопку миші та протягніть по відрізку.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[10px] text-slate-500">
            {selectedAnalysisDomain ? "Вибраний відрізок графіка" : "Повний період"}
          </span>
          <button
            type="button"
            onClick={exportSelectedInterval}
            disabled={!analysisReady}
            data-testid="export-controller-analysis-csv"
            className="inline-flex min-h-9 items-center gap-2 rounded-xl border border-cyan-300/20 bg-cyan-400/[0.06] px-3 text-xs text-cyan-100 outline-none hover:bg-cyan-400/10 focus-visible:ring-2 focus-visible:ring-cyan-300 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Download className="h-3.5 w-3.5" />
            Експорт CSV
          </button>
          {selectedAnalysisDomain ? (
            <button
              type="button"
              onClick={() => setViewportDomain(analysisDomain)}
              disabled={
                viewportDomain.fromMs === analysisDomain.fromMs && viewportDomain.toMs === analysisDomain.toMs
              }
              className="min-h-9 rounded-xl border border-white/10 px-3 text-xs text-slate-200 outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 disabled:opacity-40"
            >
              Наблизити відрізок
            </button>
          ) : null}
          {selectedAnalysisDomain ? (
            <button
              type="button"
              onClick={() => {
                setSelectedAnalysisDomain(null);
                setViewportDomain(null);
              }}
              className="min-h-9 rounded-xl border border-white/10 px-3 text-xs text-slate-200 outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
            >
              Скинути вибір
            </button>
          ) : null}
        </div>
      </section>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <DutyCard
          label="Коефіцієнт роботи"
          value={!analysisReady || duty.dutyPercent === null ? "—" : `${duty.dutyPercent.toFixed(1)} %`}
          meta={analysisUnavailableLabel ?? undefined}
        />
        <DutyCard
          label="Робота"
          value={!analysisReady || duty.status !== "available" ? "—" : formatDuration(duty.runningMs)}
          meta={analysisUnavailableLabel ?? undefined}
        />
        <DutyCard
          label="Покриття"
          value={!analysisReady || duty.status !== "available" ? "—" : `${duty.coveragePercent.toFixed(1)} %`}
          meta={
            analysisUnavailableLabel ??
            (duty.continuityBreaks > 0 ? `Прогалин: ${duty.continuityBreaks}` : "Без розривів")
          }
        />
        <DutyCard
          label="Пуски компресора"
          value={analysisReady ? String(compressorStarts.length) : "—"}
          meta={analysisUnavailableLabel ?? "Підтверджені переходи RPM 0 → >0"}
        />
        <DutyCard
          label="Тривалість відтайки"
          value={analysisReady && defrost.coveredMs > 0 ? formatDuration(defrost.activeMs, true) : "—"}
          meta={
            analysisUnavailableLabel ??
            (defrost.coveredMs > 0
              ? `Покриття стану ${((100 * defrost.coveredMs) / (analysisDomain.toMs - analysisDomain.fromMs)).toFixed(1)} %`
              : "Немає спостережень стану")
          }
        />
      </div>

      <RefrigerationControllerChart
        title="Температури контролера · °C"
        context="Температура в об’ємі · Датчик відтайки · попередній коефіцієнт 0,01"
        rangeLabel={chartRangeLabel}
        scene={annotatedTemperatureScene}
        afterPlot={temperatureScene.series.length ? timelineLanes : undefined}
        {...chartInteractions}
        emptyMessage="У вибраному періоді немає показників двох датчиків для перерахунку °C."
      />
      <section
        className="rounded-xl border border-amber-400/20 bg-amber-400/[0.05] px-4 py-3 text-xs text-amber-200"
        data-testid="embraco-unverified-scale-note"
      >
        <strong>Температура в °C (попередній коефіцієнт ×0,01)</strong> — масштаб переглянуто після показу
        контролера +0,1 °C; відповідність датчика на дисплеї та калібрування ще не підтверджені. У CSV
        розраховані °C наведені окремим стовпчиком з позначкою походження, а вихідні raw і якість вимірювання
        збережено без змін.
      </section>
      <DashboardIntervalStatistics
        rows={temperatureStatisticsRows}
        fromMs={viewportDomain.fromMs}
        toMs={viewportDomain.toMs}
        isViewport={
          viewportDomain.fromMs !== loadedAnalysisDomain.fromMs ||
          viewportDomain.toMs !== loadedAnalysisDomain.toMs
        }
        displayTimeZone={displayTimeZone}
      />
      <RefrigerationControllerChart
        title="Діагностика · вихідні raw"
        context="Температура в об’ємі · Датчик відтайки · вихідні регістри (не °C)"
        rangeLabel={chartRangeLabel}
        scene={annotatedProbeRawScene}
        {...chartInteractions}
        emptyMessage="За вибраний період немає вихідних регістрів двох датчиків."
      />
      <RefrigerationControllerChart
        title="Швидкість компресора"
        context="Embraco Sync · rpm"
        rangeLabel={chartRangeLabel}
        scene={annotatedCompressorScene}
        afterPlot={temperatureScene.series.length ? undefined : timelineLanes}
        {...chartInteractions}
        emptyMessage="У вибраному періоді немає валідної історії швидкості компресора."
      />

      <DashboardAlertEvents
        events={[annotatedTemperatureScene, annotatedProbeRawScene, annotatedCompressorScene].flatMap(
          (scene) => scene.events ?? [],
        )}
        status={alertEvents.status}
        message={alertEvents.message}
        displayTimeZone={displayTimeZone}
      />

      <section className="min-w-0 rounded-2xl border border-white/[0.08] bg-[#081a32] px-4 pb-4">
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
  cursorMs,
  selection,
  binary = false,
}: {
  label: string;
  intervals: readonly TimelineInterval[];
  range: { from: Date; to: Date };
  cursorMs: number | null;
  selection: ChartXDomain | null;
  binary?: boolean;
}) {
  const displayTimeZone = useDisplayTimeZone();
  const fromMs = range.from.getTime();
  const toMs = range.to.getTime();
  const span = toMs - fromMs;
  const percentage = (timestampMs: number) => `${((timestampMs - fromMs) / span) * 100}%`;
  const visibleIntervals = useMemo(() => {
    const result: TimelineInterval[] = [];
    for (const item of intervals) {
      const from = Math.max(item.fromMs, fromMs);
      const to = Math.min(item.toMs, toMs);
      if (to <= from) continue;
      const previous = result.at(-1);
      if (
        previous?.toMs === from &&
        previous.label === item.label &&
        previous.active === item.active &&
        previous.kind === item.kind
      ) {
        previous.toMs = to;
      } else {
        result.push({ ...item, fromMs: from, toMs: to });
      }
    }
    return result;
  }, [intervals, fromMs, toMs]);
  const selectedFrom = Math.max(selection?.fromMs ?? toMs, fromMs);
  const selectedTo = Math.min(selection?.toMs ?? fromMs, toMs);
  const observed =
    cursorMs === null
      ? null
      : visibleIntervals.find((item) => cursorMs >= item.fromMs && cursorMs < item.toMs);
  return (
    <div
      className="grid items-center"
      style={{ gridTemplateColumns: `${CHART_GRID_INSETS.left}px minmax(0,1fr)` }}
      data-timeline-label={label}
    >
      <div className="min-w-0 pr-1 text-[10px] text-slate-400">
        <span>{label}</span>
        {cursorMs !== null ? (
          <span
            className="block truncate text-slate-200"
            data-testid="timeline-cursor-state"
            title={observed?.label ?? "Немає даних"}
          >
            {observed?.label ?? "Немає даних"}
          </span>
        ) : null}
      </div>
      <div className="relative h-7 overflow-hidden rounded-md bg-[#06142a] ring-1 ring-white/[0.07] ring-inset">
        {selectedTo > selectedFrom ? (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-y-0 border-x border-cyan-300/30 bg-cyan-400/10"
            style={{ left: percentage(selectedFrom), right: percentage(fromMs + toMs - selectedTo) }}
          />
        ) : null}
        {visibleIntervals.map((item) => (
          <span
            key={item.fromMs}
            title={`${item.label} · ${formatObservedTime(item.fromMs, displayTimeZone)} → ${formatObservedTime(item.toMs, displayTimeZone)}`}
            aria-label={binary ? `${label} ${item.label}` : undefined}
            tabIndex={binary ? 0 : undefined}
            className={clsx(
              "absolute inset-y-1 min-w-px rounded",
              item.kind === "unknown"
                ? "border border-dashed border-amber-300/60 bg-[repeating-linear-gradient(135deg,rgba(245,179,1,.22)_0_4px,transparent_4px_8px)]"
                : item.active
                  ? "bg-cyan-400/55"
                  : "bg-slate-500/25",
              binary &&
                "flex items-center justify-center overflow-hidden text-[8px] font-semibold text-white outline-none focus-visible:ring-2 focus-visible:ring-cyan-200",
            )}
            style={{
              left: percentage(item.fromMs),
              right: percentage(fromMs + toMs - item.toMs),
            }}
          >
            <span className="truncate px-1 text-[9px] text-slate-100">{item.label}</span>
          </span>
        ))}
        {visibleIntervals.length === 0 ? (
          <span className="absolute inset-0 grid place-items-center text-[9px] text-slate-400">
            Немає даних
          </span>
        ) : null}
        {cursorMs !== null ? (
          <div
            className="pointer-events-none absolute inset-y-0 z-10 border-l border-dashed border-slate-100/75"
            style={{ left: percentage(cursorMs) }}
            aria-hidden="true"
          />
        ) : null}
      </div>
    </div>
  );
}

function RelayTransitionJournal({ transitions }: { transitions: readonly RelayTransition[] }) {
  const displayTimeZone = useDisplayTimeZone();
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
                  <time className="text-slate-300">
                    {formatObservedTime(transition.observedAtMs, displayTimeZone)}
                  </time>
                </p>
                <p className="truncate" title={transition.previousEventId}>
                  Попередній sample: {formatObservedTime(transition.previousObservedAtMs, displayTimeZone)} ·{" "}
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
  const displayTimeZone = useDisplayTimeZone();
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
                {formatOperationalTimestamp(new Date(sample.captured_at), displayTimeZone, {
                  year: "numeric",
                  month: "numeric",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                })}
              </time>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function formatObservedTime(timestampMs: number, displayTimeZone: string): string {
  return formatOperationalTimestamp(new Date(timestampMs), displayTimeZone, {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
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
  const displayTimeZone = useDisplayTimeZone();
  return (
    <label className="flex items-center gap-2 text-[10px] text-slate-500">
      {label}
      <input
        type="datetime-local"
        value={toZonedInputValue(value.getTime(), displayTimeZone)}
        onChange={(event) => {
          const nextMs = fromZonedInputValue(event.target.value, displayTimeZone);
          if (nextMs !== null) onChange(new Date(nextMs));
        }}
        className="min-h-9 rounded-xl border border-white/[0.08] bg-[#06142a] px-2 text-xs text-slate-200 outline-none focus:border-cyan-300/30"
      />
    </label>
  );
}

function clampAnalysisDomain(domain: ChartXDomain | null, loaded: ChartXDomain): ChartXDomain {
  if (!domain) return loaded;
  const fromMs = Math.max(loaded.fromMs, Math.min(domain.fromMs, loaded.toMs));
  const toMs = Math.min(loaded.toMs, Math.max(domain.toMs, loaded.fromMs));
  return toMs > fromMs ? { fromMs, toMs } : loaded;
}

function formatAnalysisRange(domain: ChartXDomain, displayTimeZone: string): string {
  return `${formatOperationalTimestamp(new Date(domain.fromMs), displayTimeZone, { year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" })} → ${formatOperationalTimestamp(new Date(domain.toMs), displayTimeZone, { year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
}

function formatDuration(milliseconds: number, includeSeconds = false): string {
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return "—";
  if (includeSeconds && milliseconds < 60_000) return `${Math.floor(milliseconds / 1_000)} с`;
  const totalMinutes = Math.floor(milliseconds / 60_000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  const label = hours > 0 ? `${hours} год ${minutes} хв` : `${minutes} хв`;
  const seconds = Math.floor(milliseconds / 1000) % 60;
  return includeSeconds && seconds > 0 ? `${label} ${seconds} с` : label;
}

function formatCustomRange(range: { from: Date; to: Date }, displayTimeZone: string): string {
  return `${formatOperationalTimestamp(range.from, displayTimeZone, { year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" })} → ${formatOperationalTimestamp(range.to, displayTimeZone, { year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
}

function EmptyHistory({ text }: { text: string }) {
  return (
    <section className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-8 text-center text-xs text-slate-500">
      {text}
    </section>
  );
}
