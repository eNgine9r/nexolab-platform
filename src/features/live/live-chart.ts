import {
  CHART_SERIES_TOKENS,
  buildChartYAxisModel,
  chartSeriesKey,
  partitionChartSeriesByAxisBudget,
  type ChartFreshnessState,
  type ChartPhysicalQuantity,
  type ChartPoint,
  type ChartRendererScene,
  type ChartSeries,
  type ChartSeriesIdentity,
  type ChartXDomain,
} from "@/features/charts";
import { isLiveSampleFresh, liveFreshnessFor, type CadenceObservations } from "@/features/live/freshness";
import { liveHistorySegments } from "@/features/live/live-history";
import { liveChannelKey } from "@/features/live/live-telemetry";
import type { LiveTelemetryStatus } from "@/hooks/use-live-telemetry";
import type { TelemetrySample } from "@/lib/telemetry/types";

export interface LiveChartGroup {
  id: string;
  equipmentId: string;
  nativeUnits: readonly string[];
  physicalQuantities: readonly ChartPhysicalQuantity[];
  scene: ChartRendererScene;
}

export interface LiveChartBuildOptions {
  selectedIdentities: readonly TelemetrySample[];
  historySamples: readonly TelemetrySample[];
  status: LiveTelemetryStatus;
  xDomain: ChartXDomain;
  hiddenSeriesKeys?: ReadonlySet<string>;
  soloSeriesKey?: string | null;
  /** Presentation-only channel names; telemetry identities and history never change. */
  displayNames?: Readonly<Record<string, string>>;
  /**
   * Newest sample per channel (keyed by liveChannelKey). When provided, freshness and the
   * legend are evaluated per series instead of from the page-wide status, so one live channel
   * can never make a silent or invalid channel look "live".
   */
  latestSamples?: Readonly<Record<string, TelemetrySample>>;
  cadenceObservations?: CadenceObservations;
  now?: number;
}

/** Per-series freshness: page connectivity first, then this channel's own newest sample. */
export function liveSeriesFreshness(
  status: LiveTelemetryStatus,
  latest: TelemetrySample | undefined,
  key: string,
  cadence: CadenceObservations | undefined,
  now: number,
): ChartFreshnessState {
  if (status !== "live" && status !== "stale") return liveStatusChartFreshness(status);
  if (!latest) return "stale";
  if (latest.quality !== "valid" || latest.value === null || !Number.isFinite(latest.value)) return "invalid";
  return isLiveSampleFresh(latest, now, liveFreshnessFor(latest, key, cadence)) ? "live" : "stale";
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

function seriesName(sample: TelemetrySample, displayNames: Readonly<Record<string, string>>): string {
  const label = displayNames[sample.node_id + "/" + sample.channel_id] ?? sample.channel_id;
  return `${sample.equipment_id} · ${label} · ${sample.metric}`;
}

function buildSeries(
  identitySample: TelemetrySample,
  channelHistory: readonly TelemetrySample[],
  status: LiveTelemetryStatus,
  index: number,
  displayNames: Readonly<Record<string, string>>,
  hiddenSeriesKeys: ReadonlySet<string>,
  soloSeriesKey: string | null,
  perSeries: Pick<LiveChartBuildOptions, "latestSamples" | "cadenceObservations" | "now"> = {},
): ChartSeries {
  const identity = liveSampleChartIdentity(identitySample);
  const key = chartSeriesKey(identity);
  const channelKey = liveChannelKey(identitySample);
  const latest = perSeries.latestSamples?.[channelKey];
  const freshness = perSeries.latestSamples
    ? liveSeriesFreshness(
        status,
        latest,
        channelKey,
        perSeries.cadenceObservations,
        perSeries.now ?? Date.now(),
      )
    : liveStatusChartFreshness(status);
  const token = CHART_SERIES_TOKENS[index % CHART_SERIES_TOKENS.length];
  const segments = liveHistorySegments(channelHistory);

  return {
    identity,
    name: seriesName(identitySample, displayNames),
    colorToken: token.color,
    dashStyle: token.dashStyle,
    markerShape: token.markerShape,
    freshness,
    ...(latest
      ? {
          latest: {
            timestampMs: Date.parse(latest.captured_at),
            value: latest.value,
            quality: latest.quality,
          },
        }
      : {}),
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

function equipmentSceneGroups(series: readonly ChartSeries[]): Array<{
  equipmentId: string;
  series: ChartSeries[];
}> {
  const byEquipment = new Map<string, ChartSeries[]>();
  for (const item of series) {
    const equipmentId = item.identity.equipmentId;
    byEquipment.set(equipmentId, [...(byEquipment.get(equipmentId) ?? []), item]);
  }
  return [...byEquipment.entries()].flatMap(([equipmentId, equipmentSeries]) =>
    partitionChartSeriesByAxisBudget(equipmentSeries).map((partition) => ({
      equipmentId,
      series: partition,
    })),
  );
}

export function buildLiveChartGroups(options: LiveChartBuildOptions): LiveChartGroup[] {
  const hiddenSeriesKeys = options.hiddenSeriesKeys ?? new Set<string>();
  const soloSeriesKey = options.soloSeriesKey ?? null;
  // P0 charts: history grouped by channel once. Filtering the whole history per selected channel
  // built a five-part key per sample per channel (~430 ms per build for 24 channels on a Pi 5),
  // and the groups rebuild on every zoom commit, clock tick and live sample.
  const byChannel = new Map<string, TelemetrySample[]>();
  for (const sample of options.historySamples) {
    const key = liveChannelKey(sample);
    const list = byChannel.get(key);
    if (list) list.push(sample);
    else byChannel.set(key, [sample]);
  }
  const allSeries = options.selectedIdentities.map((identity, index) =>
    buildSeries(
      identity,
      byChannel.get(liveChannelKey(identity)) ?? [],
      options.status,
      index,
      options.displayNames ?? {},
      hiddenSeriesKeys,
      soloSeriesKey,
      {
        latestSamples: options.latestSamples,
        cadenceObservations: options.cadenceObservations,
        now: options.now,
      },
    ),
  );

  return equipmentSceneGroups(allSeries).map(({ equipmentId, series }, partitionIndex) => {
    const axisModel = buildChartYAxisModel(series);
    return {
      id: `equipment:${equipmentId.length}:${equipmentId}:axes:${partitionIndex}`,
      equipmentId,
      nativeUnits: axisModel.allAxes.map((axis) => axis.nativeUnit),
      physicalQuantities: axisModel.allAxes.map((axis) => axis.physicalQuantity),
      scene: {
        series,
        xDomain: options.xDomain,
      },
    };
  });
}
