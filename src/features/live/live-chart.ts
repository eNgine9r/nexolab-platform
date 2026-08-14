import {
  CHART_SERIES_TOKENS,
  chartSeriesKey,
  type ChartFreshnessState,
  type ChartPoint,
  type ChartRendererScene,
  type ChartSeries,
  type ChartSeriesIdentity,
  type ChartXDomain,
} from "@/features/charts";
import { groupCompatibleChartUnits, type ChartUnitGroup } from "@/features/charts/units";
import { liveHistorySegments } from "@/features/live/live-history";
import { liveChannelKey } from "@/features/live/live-telemetry";
import type { LiveTelemetryStatus } from "@/hooks/use-live-telemetry";
import type { TelemetrySample } from "@/lib/telemetry/types";

export interface LiveChartGroup {
  id: string;
  nativeUnit: string;
  physicalQuantity: ChartUnitGroup["physicalQuantity"];
  scene: ChartRendererScene;
}

export interface LiveChartBuildOptions {
  selectedIdentities: readonly TelemetrySample[];
  historySamples: readonly TelemetrySample[];
  status: LiveTelemetryStatus;
  xDomain: ChartXDomain;
  hiddenSeriesKeys?: ReadonlySet<string>;
  soloSeriesKey?: string | null;
}

export function liveSampleChartIdentity(sample: TelemetrySample): ChartSeriesIdentity {
  return {
    nodeId: sample.node_id,
    equipmentId: sample.equipment_id,
    channelId: sample.channel_id,
    metric: sample.metric,
    nativeUnit: sample.unit,
  };
}

export function liveStatusChartFreshness(status: LiveTelemetryStatus): ChartFreshnessState {
  if (status === "live") return "live";
  if (status === "stale") return "stale";
  if (status === "connecting") return "connecting";
  if (status === "reconnecting") return "reconnecting";
  return "offline";
}

function pointFromSample(sample: TelemetrySample): ChartPoint {
  return {
    id: sample.event_id,
    timestampMs: Date.parse(sample.captured_at),
    value: sample.value!,
    quality: sample.quality,
    sourceEventId: sample.event_id,
  };
}

function semanticMode(identity: ChartSeriesIdentity): ChartSeries["semanticMode"] {
  const unit = identity.nativeUnit.toLowerCase();
  const metric = identity.metric.toLowerCase();
  return unit === "kwh" || unit === "wh" || metric.includes("energy")
    ? "cumulative_counter"
    : "instantaneous";
}

function seriesName(sample: TelemetrySample): string {
  return `${sample.equipment_id} · ${sample.channel_id} · ${sample.metric}`;
}

function buildSeries(
  identitySample: TelemetrySample,
  historySamples: readonly TelemetrySample[],
  status: LiveTelemetryStatus,
  index: number,
  hiddenSeriesKeys: ReadonlySet<string>,
  soloSeriesKey: string | null,
): ChartSeries {
  const identity = liveSampleChartIdentity(identitySample);
  const key = chartSeriesKey(identity);
  const token = CHART_SERIES_TOKENS[index % CHART_SERIES_TOKENS.length];
  const samples = historySamples.filter(
    (sample) => liveChannelKey(sample) === liveChannelKey(identitySample),
  );
  const segments = liveHistorySegments(samples);

  return {
    identity,
    name: seriesName(identitySample),
    colorToken: token.color,
    dashStyle: token.dashStyle,
    markerShape: token.markerShape,
    freshness: liveStatusChartFreshness(status),
    segments: segments.map((segment, segmentIndex) => ({
      id: `${key}:segment:${segmentIndex}:${Date.parse(segment[0]?.captured_at ?? "")}`,
      seriesKey: key,
      points: segment
        .filter(
          (sample) => sample.quality === "valid" && sample.value !== null && Number.isFinite(sample.value),
        )
        .map(pointFromSample),
      ...(segmentIndex > 0 && segment[0]
        ? {
            precedingBreak: {
              reason: "explicit_gap" as const,
              atMs: Date.parse(segment[0].captured_at),
              sourceEventId: segment[0].event_id,
            },
          }
        : {}),
    })),
    visible: soloSeriesKey ? soloSeriesKey === key : !hiddenSeriesKeys.has(key),
    semanticMode: semanticMode(identity),
  };
}

export function buildLiveChartGroups(options: LiveChartBuildOptions): LiveChartGroup[] {
  const hiddenSeriesKeys = options.hiddenSeriesKeys ?? new Set<string>();
  const soloSeriesKey = options.soloSeriesKey ?? null;
  const allSeries = options.selectedIdentities.map((identity, index) =>
    buildSeries(identity, options.historySamples, options.status, index, hiddenSeriesKeys, soloSeriesKey),
  );
  const byKey = new Map(allSeries.map((series) => [chartSeriesKey(series.identity), series]));
  const groups = groupCompatibleChartUnits(allSeries.map((series) => series.identity));

  return groups.map((group) => {
    const series = group.series.flatMap((identity) => {
      const item = byKey.get(chartSeriesKey(identity));
      return item ? [item] : [];
    });
    return {
      id: group.id,
      nativeUnit: group.nativeUnit,
      physicalQuantity: group.physicalQuantity,
      scene: {
        series,
        xDomain: options.xDomain,
      },
    };
  });
}
