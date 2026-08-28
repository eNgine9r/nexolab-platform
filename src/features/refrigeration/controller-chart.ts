import {
  CHART_SERIES_TOKENS,
  ChartReductionBudgetError,
  buildChartSegments,
  reduceChartSegments,
  type ChartRendererScene,
  type ChartSeries,
  type ChartSeriesIdentity,
} from "@/features/charts";
import type { TelemetrySample } from "@/lib/telemetry/types";

import { EMBRACO_METRICS, type RefrigerationHistoryRange } from "./controller-monitoring";

const MAXIMUM_POINTS = 360;
const TEMPERATURE_NAMES = new Map<string, string>([
  [EMBRACO_METRICS.cabinet, "Cabinet"],
  [EMBRACO_METRICS.evaporator, "Evaporator"],
  [EMBRACO_METRICS.condenser, "Condenser"],
  [EMBRACO_METRICS.setpoint, "Setpoint"],
]);

function timestamp(sample: TelemetrySample): number {
  const value = Date.parse(sample.captured_at);
  return Number.isFinite(value) ? value : Number.NaN;
}

function reduced(segments: ChartSeries["segments"]): ChartSeries["segments"] {
  const count = segments.reduce((sum, segment) => sum + segment.points.length, 0);
  if (count <= MAXIMUM_POINTS) return segments;
  try {
    return reduceChartSegments(segments, { maximumPoints: MAXIMUM_POINTS });
  } catch (error) {
    if (!(error instanceof ChartReductionBudgetError)) throw error;
    return reduceChartSegments(segments, { maximumPoints: count });
  }
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
