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
import type { DashboardTelemetryStatus } from "@/lib/telemetry/dashboard-state";
import { isTemperatureProbeSample } from "@/lib/telemetry/temperature-channel";
import type { TelemetrySample } from "@/lib/telemetry/types";

const MAXIMUM_SOURCE_GAP_MS = 30_000;
const DEFAULT_POINT_BUDGET = 240;

const HISTORY_RANGE_MS = {
  "1h": 60 * 60 * 1_000,
  "6h": 6 * 60 * 60 * 1_000,
  "24h": 24 * 60 * 60 * 1_000,
} as const;

export type OverviewHistoryRange = keyof typeof HISTORY_RANGE_MS;

export interface OverviewChartGroup {
  id: string;
  nativeUnit: string;
  physicalQuantity: ChartUnitGroup["physicalQuantity"];
  scene: ChartRendererScene;
}

export interface OverviewChartBuildOptions {
  samples: readonly TelemetrySample[];
  status: DashboardTelemetryStatus;
  xDomain: ChartXDomain;
  hiddenSeriesKeys?: ReadonlySet<string>;
  soloSeriesKey?: string | null;
}

function timestamp(sample: TelemetrySample): number {
  const parsed = Date.parse(sample.captured_at);
  return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
}

function orderedUniqueSamples(samples: readonly TelemetrySample[]): TelemetrySample[] {
  const byEventId = new Map<string, TelemetrySample>();
  for (const sample of samples) {
    const existing = byEventId.get(sample.event_id);
    if (!existing || timestamp(sample) < timestamp(existing)) byEventId.set(sample.event_id, sample);
  }
  return [...byEventId.values()].sort(
    (left, right) => timestamp(left) - timestamp(right) || left.event_id.localeCompare(right.event_id),
  );
}

export function overviewChartFreshness(status: DashboardTelemetryStatus): ChartFreshnessState {
  if (status === "live") return "live";
  if (status === "stale") return "stale";
  if (status === "connecting") return "connecting";
  if (status === "reconnecting") return "reconnecting";
  return "offline";
}

export function overviewChartIdentity(sample: TelemetrySample): ChartSeriesIdentity {
  return {
    nodeId: sample.node_id,
    equipmentId: sample.equipment_id,
    channelId: sample.channel_id,
    metric: sample.metric,
    nativeUnit: sample.unit,
  };
}

function transitionPins(samples: readonly TelemetrySample[]): Map<string, ChartPoint["pinReasons"]> {
  const pins = new Map<string, ChartPoint["pinReasons"]>();
  let previous: TelemetrySample | null = null;

  for (const sample of orderedUniqueSamples(samples)) {
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
  source: readonly TelemetrySample[],
  status: DashboardTelemetryStatus,
  visualIndex: number,
  hiddenSeriesKeys: ReadonlySet<string>,
  soloSeriesKey: string | null,
): ChartSeries {
  const samples = orderedUniqueSamples(source);
  const identity = overviewChartIdentity(samples[0]);
  const key = chartSeriesKey(identity);
  const token = CHART_SERIES_TOKENS[visualIndex % CHART_SERIES_TOKENS.length];
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
    name: identity.channelId,
    colorToken: token.color,
    dashStyle: token.dashStyle,
    markerShape: token.markerShape,
    freshness: overviewChartFreshness(status),
    segments: reduceTruthfully(segments),
    visible: soloSeriesKey ? soloSeriesKey === key : !hiddenSeriesKeys.has(key),
    semanticMode: "instantaneous",
  };
}

export function buildOverviewChartGroups(options: OverviewChartBuildOptions): OverviewChartGroup[] {
  const hiddenSeriesKeys = options.hiddenSeriesKeys ?? new Set<string>();
  const soloSeriesKey = options.soloSeriesKey ?? null;
  const groupedSamples = new Map<string, TelemetrySample[]>();
  const identities = new Map<string, ChartSeriesIdentity>();

  for (const sample of options.samples.filter(isTemperatureProbeSample)) {
    const identity = overviewChartIdentity(sample);
    const key = chartSeriesKey(identity);
    groupedSamples.set(key, [...(groupedSamples.get(key) ?? []), sample]);
    identities.set(key, identity);
  }

  const orderedKeys = [...groupedSamples.keys()].sort((left, right) => left.localeCompare(right, "en"));
  const entries = orderedKeys.map((key, index) => ({
    key,
    index,
    chartSeries: buildSeries(
      groupedSamples.get(key) ?? [],
      options.status,
      index,
      hiddenSeriesKeys,
      soloSeriesKey,
    ),
  }));
  const byKey = new Map(entries.map((entry) => [entry.key, entry]));
  const unitGroups = groupCompatibleChartUnits(
    orderedKeys.flatMap((key) => {
      const identity = identities.get(key);
      return identity ? [identity] : [];
    }),
  );

  return unitGroups
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
        firstIndex: selected[0]?.index ?? Number.MAX_SAFE_INTEGER,
        scene: {
          series,
          xDomain: options.xDomain,
          events: alarmEvents(series),
        },
      };
    })
    .sort((left, right) => left.firstIndex - right.firstIndex)
    .map(({ firstIndex: _firstIndex, ...group }) => group);
}

export function overviewResetDomain(
  range: OverviewHistoryRange,
  historyWindow: { from: string; to: string } | null,
  samples: readonly TelemetrySample[],
): ChartXDomain {
  const sampleAnchor = samples
    .filter(isTemperatureProbeSample)
    .reduce((latest, sample) => Math.max(latest, timestamp(sample)), Number.NEGATIVE_INFINITY);
  const windowAnchor = historyWindow ? Date.parse(historyWindow.to) : Number.NEGATIVE_INFINITY;
  const toMs = Math.max(
    sampleAnchor,
    Number.isFinite(windowAnchor) ? windowAnchor : Number.NEGATIVE_INFINITY,
  );
  const safeToMs = Number.isFinite(toMs) ? toMs : Date.now();
  return { fromMs: safeToMs - HISTORY_RANGE_MS[range], toMs: safeToMs };
}
