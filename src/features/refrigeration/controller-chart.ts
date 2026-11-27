import {
  CHART_SERIES_TOKENS,
  buildChartSegments,
  reduceChartSegmentsToPointBudget,
  type ChartRendererScene,
  type ChartSeries,
  type ChartSeriesIdentity,
} from "@/features/charts";
import { buildRawStatisticsRows, type RawStatisticsRow } from "@/features/charts/raw-sample-statistics";
import {
  newestSampleValidity,
  resolveSeriesFreshness,
  withInvalidNewestSample,
  type SeriesFreshness,
} from "@/features/charts/series-freshness";
import {
  CADENCE_OBSERVATION_LIMIT,
  observedCadenceMs,
  resolveLiveFreshness,
} from "@/features/live/freshness";
import type { TelemetrySample } from "@/lib/telemetry/types";

import { EMBRACO_METRICS, type RefrigerationHistoryRange } from "./controller-monitoring";
import { EMBRACO_KK1_CONTROLLER_ID, operatorEmbracoCelsius } from "./embraco-operator-scale";

const TEMPERATURE_NAMES = new Map<string, string>([
  [EMBRACO_METRICS.cabinet, "Температура в об’ємі"],
  [EMBRACO_METRICS.evaporator, "Датчик відтайки"],
  [EMBRACO_METRICS.condenser, "Конденсатор"],
  [EMBRACO_METRICS.setpoint, "Уставка"],
]);

function timestamp(sample: TelemetrySample): number {
  const value = Date.parse(sample.captured_at);
  return Number.isFinite(value) ? value : Number.NaN;
}

/** Axis unit for the presentation-only HMI-informed estimate; never shares the calibrated °C axis. */
export const EMBRACO_PROVISIONAL_UNIT = "°C (попередньо)";
export const EMBRACO_PROVISIONAL_SUFFIX = " · попередня шкала";

/**
 * A sample that cannot be drawn (communication error, unconvertible reading) must
 * still split the line, otherwise the renderer joins points across the outage.
 */
function breakMarker(sample: TelemetrySample, channelId: string, unit: string): TelemetrySample {
  return {
    ...sample,
    value: null,
    unit,
    quality: sample.quality === "valid" ? "unknown" : sample.quality,
    channel_id: channelId,
  };
}

function reduced(segments: ChartSeries["segments"], maximumPoints?: number): ChartSeries["segments"] {
  return reduceChartSegmentsToPointBudget(segments, "refrigeration-controller", { maximumPoints });
}

/**
 * Per-series freshness (#1677): the series' own newest RAW sample decides, with the #1522 threshold
 * (server contract, else the cadence observed in its own raw timestamps, else 30 s). The controller
 * `online` flag still wins when it is false; `freshUntilMs` lets a clock overlay flip a silent series to
 * stale without rebuilding the scene.
 */
function refrigerationSeriesFreshness(
  online: boolean,
  ordered: readonly TelemetrySample[],
  now: number = Date.now(),
): SeriesFreshness {
  const latest = ordered.at(-1);
  const page = online ? "live" : "offline";
  if (!latest) return { freshness: withInvalidNewestSample(page, null) };
  const recent = [...new Set(ordered.map(timestamp))].slice(-CADENCE_OBSERVATION_LIMIT);
  return resolveSeriesFreshness({
    page,
    latest: { timestampMs: timestamp(latest), valid: newestSampleValidity([latest])?.valid ?? false },
    staleAfterMs: resolveLiveFreshness(latest, observedCadenceMs(recent)).staleAfterMs,
    now,
  });
}

function seriesFromSamples(
  samples: readonly TelemetrySample[],
  name: string,
  visualIndex: number,
  online: boolean,
  maximumPoints?: number,
  now?: number,
): ChartSeries | null {
  const ordered = [...samples]
    .filter((sample) => Number.isFinite(timestamp(sample)))
    .sort((left, right) => timestamp(left) - timestamp(right));
  const first = ordered[0];
  if (!first) return null;
  const hasRenderableValue = ordered.some(
    (sample) => sample.quality === "valid" && sample.value !== null && Number.isFinite(sample.value),
  );
  if (!hasRenderableValue) return null;
  const identity: ChartSeriesIdentity = {
    nodeId: first.node_id,
    equipmentId: first.equipment_id,
    channelId: first.channel_id,
    metric: first.metric,
    nativeUnit: first.unit,
  };
  const token = CHART_SERIES_TOKENS[visualIndex % CHART_SERIES_TOKENS.length];
  const segments = buildChartSegments(
    identity,
    ordered.map((sample) => ({
      id: sample.event_id,
      timestampMs: timestamp(sample),
      value: sample.value,
      quality: sample.quality,
      sourceEventId: sample.event_id,
    })),
  );
  return {
    identity,
    name,
    colorToken: token.color,
    // #1868: the setpoint is a configured reference, not a measurement, so it keeps the dashed
    // reference style; every measured controller value is solid.
    dashStyle: first.metric === EMBRACO_METRICS.setpoint ? "dashed" : token.dashStyle,
    markerShape: token.markerShape,
    ...refrigerationSeriesFreshness(online, ordered, now),
    segments: reduced(segments, maximumPoints),
    visible: true,
    semanticMode: "instantaneous",
    displayPrecision: first.unit === "rpm" ? 0 : 1,
  };
}

export function buildEmbracoTemperatureScene(
  history: ReadonlyMap<string, readonly TelemetrySample[]>,
  range: RefrigerationHistoryRange,
  online: boolean,
  maximumPoints?: number,
  now?: number,
): ChartRendererScene {
  const series = [...TEMPERATURE_NAMES.entries()].flatMap(([metric, name], index) => {
    const built = seriesFromSamples(history.get(metric) ?? [], name, index, online, maximumPoints, now);
    return built ? [built] : [];
  });
  return { series, xDomain: { fromMs: range.from.getTime(), toMs: range.to.getTime() } };
}

/**
 * Provisional HMI-informed (0.01 °C/count), not independently calibrated.
 * Unverified raw telemetry stays immutable and retains `quality: unknown` in storage.
 * The synthetic `valid` quality exists ONLY in the chart renderer's local input,
 * permitting a visibly labeled derived series without rewriting source evidence.
 */
export function buildEmbracoOperatorCelsiusScene(
  history: ReadonlyMap<string, readonly TelemetrySample[]>,
  range: RefrigerationHistoryRange,
  online: boolean,
  controllerEquipmentId: string,
  maximumPoints?: number,
  now?: number,
): ChartRendererScene {
  if (controllerEquipmentId !== EMBRACO_KK1_CONTROLLER_ID) {
    return { series: [], xDomain: { fromMs: range.from.getTime(), toMs: range.to.getTime() } };
  }
  const probes = [
    [EMBRACO_METRICS.cabinet, "Температура в об’ємі"],
    [EMBRACO_METRICS.evaporator, "Датчик відтайки"],
  ] as const;
  const series = probes.flatMap(([metric, name], index) => {
    const source = history.get(metric) ?? [];
    const calibratedChannel = (sample: TelemetrySample) => sample.channel_id;
    const provisionalChannel = (sample: TelemetrySample) => `${sample.channel_id}:operator-degC`;
    const calibrated: TelemetrySample[] = [];
    const provisional: TelemetrySample[] = [];
    for (const sample of source) {
      const operatorCelsius = operatorEmbracoCelsius(sample);
      const calibratedValue =
        sample.equipment_id === EMBRACO_KK1_CONTROLLER_ID &&
        sample.quality === "valid" &&
        sample.value !== null &&
        Number.isFinite(sample.value);
      if (operatorCelsius !== null) {
        provisional.push({
          ...sample,
          value: operatorCelsius,
          unit: EMBRACO_PROVISIONAL_UNIT,
          quality: "valid" as const,
          channel_id: provisionalChannel(sample),
        });
        calibrated.push(breakMarker(sample, calibratedChannel(sample), "°C"));
      } else if (calibratedValue) {
        calibrated.push({ ...sample, unit: "°C" });
        provisional.push(breakMarker(sample, provisionalChannel(sample), EMBRACO_PROVISIONAL_UNIT));
      } else if (sample.equipment_id === EMBRACO_KK1_CONTROLLER_ID) {
        calibrated.push(breakMarker(sample, calibratedChannel(sample), "°C"));
        provisional.push(breakMarker(sample, provisionalChannel(sample), EMBRACO_PROVISIONAL_UNIT));
      }
    }
    const visualIndex = index * 2;
    const calibratedSeries = seriesFromSamples(calibrated, name, visualIndex, online, maximumPoints, now);
    const provisionalSeries = seriesFromSamples(
      provisional,
      `${name}${EMBRACO_PROVISIONAL_SUFFIX}`,
      visualIndex + 1,
      online,
      maximumPoints,
      now,
    );
    return [calibratedSeries, provisionalSeries].flatMap((built) =>
      built ? [{ ...built, displayPrecision: 2 }] : [],
    );
  });
  return { series, xDomain: { fromMs: range.from.getTime(), toMs: range.to.getTime() } };
}

/**
 * Physical signed FC03 register readings, NOT engineering degrees Celsius.
 * The original unknown-quality °C samples remain unmodified in telemetry and CSV.
 * This separate raw-unit scene is only for diagnostics until an approved scale exists.
 */
export function buildEmbracoProbeRawScene(
  history: ReadonlyMap<string, readonly TelemetrySample[]>,
  range: RefrigerationHistoryRange,
  online: boolean,
  maximumPoints?: number,
  now?: number,
): ChartRendererScene {
  const probes = [
    [EMBRACO_METRICS.cabinet, "Температура в об’ємі · raw"],
    [EMBRACO_METRICS.evaporator, "Датчик відтайки · raw"],
  ] as const;
  const series = probes.flatMap(([metric, name], index) => {
    const rawSamples = (history.get(metric) ?? []).map((sample) =>
      (sample.quality === "valid" || sample.quality === "unknown") &&
      sample.raw_value !== null &&
      Number.isInteger(sample.raw_value) &&
      sample.raw_value >= 0 &&
      sample.raw_value <= 65535
        ? {
            ...sample,
            value: sample.raw_value >= 32768 ? sample.raw_value - 65536 : sample.raw_value,
            unit: "raw",
            // The validated raw reading is distinct from the unverified Celsius value.
            quality: "valid" as const,
            channel_id: `${sample.channel_id}:raw`,
          }
        : breakMarker(sample, `${sample.channel_id}:raw`, "raw"),
    );
    const built = seriesFromSamples(rawSamples, name, index, online, maximumPoints, now);
    return built ? [{ ...built, displayPrecision: 0 }] : [];
  });
  return { series, xDomain: { fromMs: range.from.getTime(), toMs: range.to.getTime() } };
}

export function buildEmbracoCompressorScene(
  history: ReadonlyMap<string, readonly TelemetrySample[]>,
  range: RefrigerationHistoryRange,
  online: boolean,
  maximumPoints?: number,
  now?: number,
): ChartRendererScene {
  const series = seriesFromSamples(
    history.get(EMBRACO_METRICS.compressorSpeed) ?? [],
    "Compressor speed",
    0,
    online,
    maximumPoints,
    now,
  );
  return {
    series: series ? [series] : [],
    xDomain: { fromMs: range.from.getTime(), toMs: range.to.getTime() },
  };
}

/**
 * Exact statistics for the Embraco KK1 probe series of {@link buildEmbracoOperatorCelsiusScene},
 * computed from the RAW history (never from the reduced chart series) with the same value rules:
 * the provisional operator scale yields a valid value only for the two operator probes, the
 * calibrated series only for samples that are genuinely valid °C, everything else is a non-valid poll.
 */
export function buildEmbracoTemperatureStatisticsRows(
  history: ReadonlyMap<string, readonly TelemetrySample[]>,
  scene: ChartRendererScene,
  domain: { fromMs: number; toMs: number },
): RawStatisticsRow[] {
  const probes = [
    [EMBRACO_METRICS.cabinet, "Температура в об’ємі"],
    [EMBRACO_METRICS.evaporator, "Датчик відтайки"],
  ] as const;
  const sources = new Map<string, TelemetrySample[]>();
  for (const [metric, name] of probes) {
    const calibrated: TelemetrySample[] = [];
    const provisional: TelemetrySample[] = [];
    for (const sample of history.get(metric) ?? []) {
      if (sample.equipment_id !== EMBRACO_KK1_CONTROLLER_ID) continue;
      const operatorCelsius = operatorEmbracoCelsius(sample);
      const calibratedValid =
        sample.quality === "valid" && sample.value !== null && Number.isFinite(sample.value);
      if (operatorCelsius !== null) {
        provisional.push({ ...sample, value: operatorCelsius, quality: "valid" });
        calibrated.push({ ...sample, value: null, quality: "unknown" });
      } else if (calibratedValid) {
        calibrated.push(sample);
        provisional.push({ ...sample, value: null, quality: "unknown" });
      } else {
        calibrated.push({ ...sample, value: null, quality: "unknown" });
        provisional.push({ ...sample, value: null, quality: "unknown" });
      }
    }
    sources.set(name, calibrated);
    sources.set(`${name}${EMBRACO_PROVISIONAL_SUFFIX}`, provisional);
  }
  return buildRawStatisticsRows(scene.series, (_identity, series) => sources.get(series.name) ?? [], domain);
}
