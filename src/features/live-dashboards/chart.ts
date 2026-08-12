import {
  CHART_SERIES_TOKENS,
  ChartReductionBudgetError,
  buildChartSegments,
  chartSeriesKey,
  reduceChartSegments,
  type ChartEventMarker,
  type ChartFreshnessState,
  type ChartPoint,
  type ChartRendererScene,
  type ChartSeries,
  type ChartSeriesIdentity,
  type ChartXDomain,
} from "@/features/charts";
import { groupCompatibleChartUnits, type ChartUnitGroup } from "@/features/charts/units";
import { timeWindowMilliseconds } from "@/features/live-dashboards/model";
import type {
  LiveDashboard,
  LiveDashboardSeries,
  LiveDashboardTelemetryStatus,
} from "@/features/live-dashboards/types";
import type { TelemetrySample } from "@/lib/telemetry/types";

const MAXIMUM_SOURCE_GAP_MS = 30_000;
const DEFAULT_POINT_BUDGET = 240;
const SAVED_AREA_FILL_OPACITY = 0.14;

export interface SavedDashboardChartGroup {
  id: string;
  nativeUnit: string;
  physicalQuantity: ChartUnitGroup["physicalQuantity"];
  scene: ChartRendererScene;
}

export interface SavedDashboardChartBuildOptions {
  dashboardId: string;
  series: readonly LiveDashboardSeries[];
  status: LiveDashboardTelemetryStatus;
  xDomain: ChartXDomain;
  hiddenSeriesKeys?: ReadonlySet<string>;
  soloSeriesKey?: string | null;
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

function transitionPins(samples: readonly TelemetrySample[]): Map<string, ChartPoint["pinReasons"]> {
  const pins = new Map<string, ChartPoint["pinReasons"]>();
  let previous: TelemetrySample | null = null;

  for (const sample of orderedSamples(samples)) {
    if (previous === null) {
      if (sample.alarm !== null) pins.set(sample.event_id, ["alarm"]);
      previous = sample;
      continue;
    }
    if (previous.alarm !== sample.alarm) {
      pins.set(previous.event_id, ["alarm"]);
      pins.set(sample.event_id, ["alarm"]);
    }
    previous = sample;
  }

  return pins;
}

function alarmEvents(series: readonly ChartSeries[]): ChartEventMarker[] {
  const events = new Map<string, ChartEventMarker>();
  for (const item of series) {
    const seriesKey = chartSeriesKey(item.identity);
    for (const segment of item.segments) {
      for (const point of segment.points) {
        if (!point.pinReasons?.includes("alarm")) continue;
        const id = `${seriesKey}:${point.id}:alarm`;
        events.set(id, {
          id,
          timestampMs: point.timestampMs,
          type: "alarm_context",
          label: `Alarm context · ${item.name}`,
          severity: "alarm",
        });
      }
    }
  }
  return [...events.values()].sort(
    (left, right) => left.timestampMs - right.timestampMs || left.id.localeCompare(right.id),
  );
}

export function savedDashboardChartFreshness(status: LiveDashboardTelemetryStatus): ChartFreshnessState {
  if (status === "live") return "live";
  if (status === "stale") return "stale";
  if (status === "connecting") return "connecting";
  if (status === "reconnecting") return "reconnecting";
  return "offline";
}

export function savedDashboardChartIdentity(
  dashboardId: string,
  series: LiveDashboardSeries,
): ChartSeriesIdentity {
  return {
    nodeId: `live-dashboard:${dashboardId}`,
    equipmentId: series.item.channel_ref_id,
    channelId: series.item.channel_id,
    metric: series.item.metric,
    nativeUnit: series.item.native_unit,
  };
}

function semanticMode(identity: ChartSeriesIdentity): ChartSeries["semanticMode"] {
  const unit = identity.nativeUnit.toLowerCase();
  const metric = identity.metric.toLowerCase();
  return unit === "kwh" || unit === "wh" || metric.includes("energy")
    ? "cumulative_counter"
    : "instantaneous";
}

function reduceTruthfully(segments: ChartSeries["segments"]): ChartSeries["segments"] {
  const sourcePointCount = segments.reduce((sum, segment) => sum + segment.points.length, 0);
  if (sourcePointCount === 0) return segments;
  try {
    return reduceChartSegments(segments, { maximumPoints: DEFAULT_POINT_BUDGET });
  } catch (error) {
    if (!(error instanceof ChartReductionBudgetError)) throw error;
    return reduceChartSegments(segments, { maximumPoints: sourcePointCount });
  }
}

function buildSeries(
  dashboardId: string,
  source: LiveDashboardSeries,
  status: LiveDashboardTelemetryStatus,
  visualIndex: number,
  hiddenSeriesKeys: ReadonlySet<string>,
  soloSeriesKey: string | null,
): ChartSeries {
  const identity = savedDashboardChartIdentity(dashboardId, source);
  const key = chartSeriesKey(identity);
  const token = CHART_SERIES_TOKENS[visualIndex % CHART_SERIES_TOKENS.length];
  const samples = orderedSamples(source.history);
  const pins = transitionPins(samples);
  const segments = buildChartSegments(
    identity,
    samples.map((sample) => ({
      id: sample.event_id,
      timestampMs: timestamp(sample),
      value: sample.value,
      quality: sample.quality,
      sourceEventId: sample.event_id,
      pinReasons: pins.get(sample.event_id),
    })),
    { maximumSourceGapMs: MAXIMUM_SOURCE_GAP_MS },
  );

  return {
    identity,
    name: `${source.item.channel_id} · ${source.item.metric}`,
    colorToken: source.item.color ?? token.color,
    dashStyle: token.dashStyle,
    markerShape: token.markerShape,
    freshness: savedDashboardChartFreshness(status),
    segments: reduceTruthfully(segments),
    visible: soloSeriesKey ? soloSeriesKey === key : !hiddenSeriesKeys.has(key),
    semanticMode: semanticMode(identity),
    ...(source.item.visualization === "area" ? { areaFillOpacity: SAVED_AREA_FILL_OPACITY } : {}),
  };
}

export function buildSavedDashboardChartGroups(
  options: SavedDashboardChartBuildOptions,
): SavedDashboardChartGroup[] {
  const hiddenSeriesKeys = options.hiddenSeriesKeys ?? new Set<string>();
  const soloSeriesKey = options.soloSeriesKey ?? null;
  const plotted = options.series
    .filter((item) => item.item.visualization === "line" || item.item.visualization === "area")
    .sort(
      (left, right) => left.item.position - right.item.position || left.item.id.localeCompare(right.item.id),
    );
  const entries = plotted.map((source, index) => ({
    source,
    index,
    chartSeries: buildSeries(
      options.dashboardId,
      source,
      options.status,
      index,
      hiddenSeriesKeys,
      soloSeriesKey,
    ),
  }));
  const byKey = new Map(entries.map((entry) => [chartSeriesKey(entry.chartSeries.identity), entry]));
  const groups = groupCompatibleChartUnits(entries.map((entry) => entry.chartSeries.identity));

  return groups
    .map((group) => {
      const selected = group.series
        .flatMap((identity) => {
          const entry = byKey.get(chartSeriesKey(identity));
          return entry ? [entry] : [];
        })
        .sort((left, right) => left.index - right.index);
      const series = selected.map((entry) => entry.chartSeries);
      return {
        id: group.id,
        nativeUnit: group.nativeUnit,
        physicalQuantity: group.physicalQuantity,
        firstPosition: selected[0]?.index ?? Number.MAX_SAFE_INTEGER,
        scene: {
          series,
          xDomain: options.xDomain,
          events: alarmEvents(series),
        },
      };
    })
    .sort((left, right) => left.firstPosition - right.firstPosition)
    .map(({ firstPosition: _firstPosition, ...group }) => group);
}

export function savedDashboardResetDomain(
  timeWindow: LiveDashboard["time_window"],
  anchorMs: number,
): ChartXDomain {
  const toMs = Number.isFinite(anchorMs) ? anchorMs : Date.now();
  return { fromMs: toMs - timeWindowMilliseconds(timeWindow), toMs };
}
