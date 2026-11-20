import {
  CHART_SERIES_TOKENS,
  buildChartSegments,
  reduceChartSegmentsToPointBudget,
  type ChartRendererScene,
  type ChartSeries,
  type ChartSeriesIdentity,
} from "@/features/charts";
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

function reduced(segments: ChartSeries["segments"]): ChartSeries["segments"] {
  return reduceChartSegmentsToPointBudget(segments, "refrigeration-controller");
}

function seriesFromSamples(
  samples: readonly TelemetrySample[],
  name: string,
  visualIndex: number,
  online: boolean,
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
    dashStyle: name === "Setpoint" ? "dashed" : token.dashStyle,
    markerShape: token.markerShape,
    freshness: online ? "live" : "offline",
    segments: reduced(segments),
    visible: true,
    semanticMode: "instantaneous",
    displayPrecision: first.unit === "rpm" ? 0 : 1,
  };
}

export function buildEmbracoTemperatureScene(
  history: ReadonlyMap<string, readonly TelemetrySample[]>,
  range: RefrigerationHistoryRange,
  online: boolean,
): ChartRendererScene {
  const series = [...TEMPERATURE_NAMES.entries()].flatMap(([metric, name], index) => {
    const built = seriesFromSamples(history.get(metric) ?? [], name, index, online);
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
): ChartRendererScene {
  if (controllerEquipmentId !== EMBRACO_KK1_CONTROLLER_ID) {
    return { series: [], xDomain: { fromMs: range.from.getTime(), toMs: range.to.getTime() } };
  }
  const probes = [
    [EMBRACO_METRICS.cabinet, "Температура в об’ємі"],
    [EMBRACO_METRICS.evaporator, "Датчик відтайки"],
  ] as const;
  const series = probes.flatMap(([metric, name], index) => {
    const displaySamples = (history.get(metric) ?? []).flatMap((sample) => {
      const operatorCelsius = operatorEmbracoCelsius(sample);
      if (operatorCelsius !== null) {
        return [
          {
            ...sample,
            value: operatorCelsius,
            unit: "°C",
            quality: "valid" as const,
            channel_id: `${sample.channel_id}:operator-degC`,
          },
        ];
      }
      if (
        sample.equipment_id === EMBRACO_KK1_CONTROLLER_ID &&
        sample.quality === "valid" &&
        sample.value !== null &&
        Number.isFinite(sample.value)
      ) {
        return [{ ...sample, unit: "°C" }];
      }
      return [];
    });
    const built = seriesFromSamples(displaySamples, name, index, online);
    return built ? [{ ...built, displayPrecision: 2 }] : [];
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
): ChartRendererScene {
  const probes = [
    [EMBRACO_METRICS.cabinet, "Температура в об’ємі · raw"],
    [EMBRACO_METRICS.evaporator, "Датчик відтайки · raw"],
  ] as const;
  const series = probes.flatMap(([metric, name], index) => {
    const rawSamples = (history.get(metric) ?? [])
      .filter(
        (sample) =>
          (sample.quality === "valid" || sample.quality === "unknown") &&
          sample.raw_value !== null &&
          Number.isInteger(sample.raw_value) &&
          sample.raw_value >= 0 &&
          sample.raw_value <= 65535,
      )
      .map((sample) => ({
        ...sample,
        value: sample.raw_value! >= 32768 ? sample.raw_value! - 65536 : sample.raw_value!,
        unit: "raw",
        // The validated raw reading is distinct from the unverified Celsius value.
        quality: "valid" as const,
        channel_id: `${sample.channel_id}:raw`,
      }));
    const built = seriesFromSamples(rawSamples, name, index, online);
    return built ? [{ ...built, displayPrecision: 0 }] : [];
  });
  return { series, xDomain: { fromMs: range.from.getTime(), toMs: range.to.getTime() } };
}

export function buildEmbracoCompressorScene(
  history: ReadonlyMap<string, readonly TelemetrySample[]>,
  range: RefrigerationHistoryRange,
  online: boolean,
): ChartRendererScene {
  const series = seriesFromSamples(
    history.get(EMBRACO_METRICS.compressorSpeed) ?? [],
    "Compressor speed",
    0,
    online,
  );
  return {
    series: series ? [series] : [],
    xDomain: { fromMs: range.from.getTime(), toMs: range.to.getTime() },
  };
}
