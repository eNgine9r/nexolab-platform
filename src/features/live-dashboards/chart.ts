import {
  CHART_SERIES_TOKENS,
  buildChartSegments,
  buildChartYAxisModel,
  chartSeriesKey,
  partitionChartSeriesByAxisBudget,
  chartPointBudget,
  reduceChartSegmentsToPointBudget,
  type ChartFreshnessState,
  type ChartPhysicalQuantity,
  type ChartRendererScene,
  type ChartSeries,
  type ChartSeriesIdentity,
  type ChartXDomain,
} from "@/features/charts";
import { dashboardItemIdentity, timeWindowMilliseconds } from "@/features/live-dashboards/model";
import {
  savedDashboardDisplaySample,
  savedDashboardSeriesLabel,
  savedDashboardSeriesUnit,
} from "@/features/live-dashboards/embraco-series";
import { isDigitalMetric } from "@/features/charts/digital-channels";
import { buildAlertChartAnnotations } from "@/features/charts/alert-events";
import { liveHistorySegments } from "@/features/live/live-history";
import { liveFreshnessFor, type CadenceObservations } from "@/features/live/freshness";
import { resolveSeriesFreshness, type SeriesFreshness } from "@/features/charts/series-freshness";
import type {
  LiveDashboard,
  LiveDashboardSeries,
  LiveDashboardTelemetryStatus,
} from "@/features/live-dashboards/types";
import type { AlertInstance } from "@/lib/alerts/types";
import type { TelemetrySample } from "@/lib/telemetry/types";

const SAVED_AREA_FILL_OPACITY = 0.14;

export interface SavedDashboardChartGroup {
  id: string;
  title: string;
  equipmentId: string | null;
  nativeUnits: readonly string[];
  physicalQuantities: readonly ChartPhysicalQuantity[];
  instruments: ReadonlyMap<string, { key: string; label: string; node: string | null }>;
  scene: ChartRendererScene;
}

export interface SavedDashboardChartBuildOptions {
  dashboardId: string;
  series: readonly LiveDashboardSeries[];
  status: LiveDashboardTelemetryStatus;
  xDomain: ChartXDomain;
  hiddenSeriesKeys?: ReadonlySet<string>;
  soloSeriesKey?: string | null;
  /**
   * #1643: when provided, freshness is evaluated per series from each item's own newest sample
   * (server contract → observed cadence → 30 s default, the #1522 rule) instead of from the
   * page-wide status, so one live channel can never make a silent or invalid channel look live.
   */
  cadenceObservations?: CadenceObservations;
  /** Evaluation clock (epoch ms) for per-series freshness. Defaults to `Date.now()`. */
  now?: number;
  /** User-selected maximum rendered points per series (#1620); defaults to the surface budget. */
  pointsPerSeries?: number;
  /**
   * Canonical alert history (#1647). Only alerts matching a plotted series produce markers,
   * alarm regions and threshold lines; telemetry-sample alarm context never does.
   */
  alerts?: readonly AlertInstance[];
}

function timestamp(sample: TelemetrySample): number {
  const parsed = Date.parse(sample.captured_at);
  return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
}

function orderedSamples(samples: readonly TelemetrySample[]): TelemetrySample[] {
  return [...samples].sort(
    (left, right) => timestamp(left) - timestamp(right) || left.event_id.localeCompare(right.event_id),
  );
}

export function savedDashboardChartFreshness(status: LiveDashboardTelemetryStatus): ChartFreshnessState {
  if (status === "live") return "live";
  if (status === "stale") return "stale";
  if (status === "connecting") return "connecting";
  if (status === "reconnecting") return "reconnecting";
  return "offline";
}

/**
 * Per-series freshness. Page connectivity (connecting/reconnecting/offline/…) always wins;
 * otherwise the series' own newest sample decides: no sample → stale, a newest sample without
 * a valid measurement → invalid, a valid sample older than its cadence-aware threshold → stale.
 * The Embraco operator-derived °C display keeps persisted quality `unknown`, so for it only
 * age decides (its provisional labelling is handled elsewhere and is never hidden here).
 */
export function savedDashboardSeriesFreshnessDetail(
  status: LiveDashboardTelemetryStatus,
  source: LiveDashboardSeries,
  cadence: CadenceObservations | undefined,
  now: number,
): SeriesFreshness {
  const page = savedDashboardChartFreshness(status);
  const latest = source.latest;
  if (!latest) return resolveSeriesFreshness({ page, latest: null, staleAfterMs: 0, now });
  const operatorDerived = savedDashboardDisplaySample(source.item, latest)?.operatorDerived === true;
  const valid =
    operatorDerived || (latest.quality === "valid" && latest.value !== null && Number.isFinite(latest.value));
  return resolveSeriesFreshness({
    page,
    latest: { timestampMs: timestamp(latest), valid },
    staleAfterMs: liveFreshnessFor(latest, dashboardItemIdentity(source.item), cadence).staleAfterMs,
    now,
  });
}

export function savedDashboardSeriesFreshness(
  status: LiveDashboardTelemetryStatus,
  source: LiveDashboardSeries,
  cadence: CadenceObservations | undefined,
  now: number,
): ChartFreshnessState {
  return savedDashboardSeriesFreshnessDetail(status, source, cadence, now).freshness;
}

export function savedDashboardChartIdentity(
  dashboardId: string,
  series: LiveDashboardSeries,
): ChartSeriesIdentity {
  return {
    nodeId: series.item.node_id ?? `live-dashboard:${dashboardId}`,
    equipmentId: series.item.equipment_id ?? series.item.channel_ref_id ?? series.item.id,
    channelId: series.item.channel_id,
    metric: series.item.metric,
    nativeUnit: savedDashboardSeriesUnit(series.item),
  };
}

function sourceEquipmentId(series: LiveDashboardSeries): string {
  return (
    series.latest?.equipment_id ??
    series.history[0]?.equipment_id ??
    series.item.equipment_id ??
    series.item.channel_ref_id ??
    series.item.id
  );
}

function observedInstrument(series: LiveDashboardSeries): {
  key: string;
  label: string;
  node: string | null;
} {
  const sample = series.latest ?? series.history[0];
  const node = sample?.node_id ?? series.item.node_id ?? null;
  const equipment = sample?.equipment_id ?? series.item.equipment_id;
  return equipment
    ? { key: JSON.stringify([node, equipment]), label: equipment, node }
    : { key: "unidentified", label: "Прилад не визначено", node: null };
}

function semanticMode(identity: ChartSeriesIdentity): ChartSeries["semanticMode"] {
  const unit = identity.nativeUnit.toLowerCase();
  const metric = identity.metric.toLowerCase();
  return unit === "kwh" || unit === "wh" || metric.includes("energy")
    ? "cumulative_counter"
    : "instantaneous";
}

function reduceTruthfully(
  segments: ChartSeries["segments"],
  maximumPoints?: number,
): ChartSeries["segments"] {
  return reduceChartSegmentsToPointBudget(segments, "saved-dashboard", { maximumPoints });
}

/**
 * #1821: with viewport detail, the hook's history holds full-range points plus the zoomed window's
 * original measurements, each within its own budget. Reducing that again over the whole span would
 * discard the detail, so the chart-level reduction then only bounds both together.
 */
const ANNOTATED_HISTORY_BUDGET_FACTOR = 3;

function chartBudget(source: LiveDashboardSeries, pointsPerSeries: number | undefined): number | undefined {
  if (!source.continuityAnnotated || !source.viewportDetail) return pointsPerSeries;
  return (pointsPerSeries ?? chartPointBudget("saved-dashboard")) * ANNOTATED_HISTORY_BUDGET_FACTOR;
}

function buildSeries(
  dashboardId: string,
  source: LiveDashboardSeries,
  status: LiveDashboardTelemetryStatus,
  visualIndex: number,
  hiddenSeriesKeys: ReadonlySet<string>,
  soloSeriesKey: string | null,
  perSeries: Pick<
    SavedDashboardChartBuildOptions,
    "cadenceObservations" | "now" | "pointsPerSeries"
  > | null = null,
): ChartSeries {
  const identity = savedDashboardChartIdentity(dashboardId, source);
  const key = chartSeriesKey(identity);
  const token = CHART_SERIES_TOKENS[visualIndex % CHART_SERIES_TOKENS.length];
  const samples = orderedSamples(source.history);
  const segments = liveHistorySegments(samples).flatMap((sourceSegment, segmentIndex) =>
    buildChartSegments(
      identity,
      sourceSegment.map((sample) => {
        const display = savedDashboardDisplaySample(source.item, sample);
        return {
          id: sample.event_id,
          timestampMs: timestamp(sample),
          value: display?.value ?? null,
          // Derived operator °C is chart-local. Persisted sample quality remains unknown.
          quality: display?.operatorDerived ? ("valid" as const) : sample.quality,
          sourceEventId: sample.event_id,
        };
      }),
      // #1805: reduced history already carries its source gaps as segment markers decided on RAW
      // data. Re-deriving a tolerance from reduced points would break continuous data; invalid
      // samples still break. Raw input (not annotated) keeps the cadence-derived detection.
      source.continuityAnnotated ? { maximumSourceGapMs: Number.MAX_SAFE_INTEGER } : {},
    ).map((segment, index) =>
      segmentIndex > 0 && index === 0 && segment.points[0]
        ? {
            ...segment,
            precedingBreak: {
              reason: "explicit_gap" as const,
              atMs: segment.points[0].timestampMs,
            },
          }
        : segment,
    ),
  );

  return {
    identity,
    name: savedDashboardSeriesLabel(source.item),
    colorToken: source.item.color ?? token.color,
    dashStyle: token.dashStyle,
    markerShape: token.markerShape,
    ...(perSeries
      ? savedDashboardSeriesFreshnessDetail(
          status,
          source,
          perSeries.cadenceObservations,
          perSeries.now ?? Date.now(),
        )
      : { freshness: savedDashboardChartFreshness(status) }),
    segments: reduceTruthfully(segments, chartBudget(source, perSeries?.pointsPerSeries)),
    visible: soloSeriesKey ? soloSeriesKey === key : !hiddenSeriesKeys.has(key),
    semanticMode: semanticMode(identity),
    ...(identity.nativeUnit === "°C" && source.item.equipment_id === "EMBRACO-2"
      ? { displayPrecision: 2 }
      : {}),
    ...(source.item.visualization === "area" ? { areaFillOpacity: SAVED_AREA_FILL_OPACITY } : {}),
  };
}

function annotations(
  partition: readonly ChartSeries[],
  options: SavedDashboardChartBuildOptions,
): Pick<ChartRendererScene, "events" | "thresholds" | "alarmRegions"> {
  if (!options.alerts || options.alerts.length === 0) return {};
  const built = buildAlertChartAnnotations(
    options.alerts,
    partition.map((entry) => entry.identity),
    options.xDomain,
    options.now ?? Date.now(),
  );
  return {
    ...(built.events.length > 0 ? { events: built.events } : {}),
    ...(built.thresholds.length > 0 ? { thresholds: built.thresholds } : {}),
    ...(built.alarmRegions.length > 0 ? { alarmRegions: built.alarmRegions } : {}),
  };
}

export function buildSavedDashboardChartGroups(
  options: SavedDashboardChartBuildOptions,
): SavedDashboardChartGroup[] {
  const hiddenSeriesKeys = options.hiddenSeriesKeys ?? new Set<string>();
  const soloSeriesKey = options.soloSeriesKey ?? null;
  const plotted = options.series
    // Known digital channels are state lanes (#1679), never numeric lines.
    .filter(
      (item) =>
        (item.item.visualization === "line" || item.item.visualization === "area") &&
        !isDigitalMetric(item.item.metric),
    )
    .sort(
      (left, right) => left.item.position - right.item.position || left.item.id.localeCompare(right.item.id),
    );
  const chartSeries = plotted.map((source, index) =>
    buildSeries(
      options.dashboardId,
      source,
      options.status,
      index,
      hiddenSeriesKeys,
      soloSeriesKey,
      options.now !== undefined ||
        options.cadenceObservations !== undefined ||
        options.pointsPerSeries !== undefined
        ? options
        : null,
    ),
  );
  if (chartSeries.length === 0) return [];

  const instruments = new Map(
    chartSeries.map((series, index) => [chartSeriesKey(series.identity), observedInstrument(plotted[index])]),
  );
  const equipmentIds = [...new Set(plotted.map(sourceEquipmentId))];
  const equipmentId = equipmentIds.length === 1 ? equipmentIds[0] : null;
  const partitions = partitionChartSeriesByAxisBudget(chartSeries);

  return partitions.map((partition, partitionIndex) => {
    const axisModel = buildChartYAxisModel(partition);
    return {
      id: `dashboard:${options.dashboardId}:axes:${partitionIndex}`,
      title:
        partitions.length === 1
          ? "Графік Dashboard"
          : `Графік Dashboard · ${partitionIndex + 1}/${partitions.length}`,
      equipmentId,
      nativeUnits: axisModel.allAxes.map((axis) => axis.nativeUnit),
      physicalQuantities: axisModel.allAxes.map((axis) => axis.physicalQuantity),
      instruments,
      scene: {
        series: partition,
        xDomain: options.xDomain,
        ...annotations(partition, options),
      },
    };
  });
}

export function savedDashboardResetDomain(
  timeWindow: LiveDashboard["time_window"],
  anchorMs: number,
): ChartXDomain {
  const toMs = Number.isFinite(anchorMs) ? anchorMs : Date.now();
  return { fromMs: toMs - timeWindowMilliseconds(timeWindow), toMs };
}
