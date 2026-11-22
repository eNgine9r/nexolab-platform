import {
  CHART_SERIES_TOKENS,
  buildChartSegments,
  chartSeriesKey,
  reduceChartSegmentsToPointBudget,
  type ChartFreshnessState,
  type ChartRendererScene,
  type ChartSeries,
  type ChartSeriesIdentity,
  type ChartXDomain,
} from "@/features/charts";
import {
  CADENCE_OBSERVATION_LIMIT,
  observedCadenceMs,
  resolveLiveFreshness,
} from "@/features/live/freshness";
import { resolveSeriesFreshness, type SeriesFreshness } from "@/features/charts/series-freshness";
import { groupCompatibleChartUnits, type ChartUnitGroup } from "@/features/charts/units";
import type { DashboardTelemetryStatus } from "@/lib/telemetry/dashboard-state";
import { isTemperatureProbeSample } from "@/lib/telemetry/temperature-channel";
import type { TelemetrySample } from "@/lib/telemetry/types";

const HISTORY_RANGE_MS = {
  "1h": 60 * 60 * 1_000,
  "6h": 6 * 60 * 60 * 1_000,
  "24h": 24 * 60 * 60 * 1_000,
  "7d": 7 * 24 * 60 * 60 * 1_000,
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
  /** Evaluation clock for per-series freshness (epoch ms). Defaults to `Date.now()` at build. */
  now?: number;
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

/**
 * Per-series freshness from the series' own newest RAW sample (history is not reduced before
 * this builder). The stale threshold is cadence-aware (#1522): server `stale_after_seconds`, else
 * the shortest recent spacing of this series' distinct timestamps, else 30 s. Page connectivity
 * (connecting/reconnecting/offline) always wins.
 */
function overviewSeriesFreshness(
  status: DashboardTelemetryStatus,
  samples: readonly TelemetrySample[],
  now: number,
): SeriesFreshness {
  const latest = samples.at(-1);
  const recent = [...new Set(samples.map(timestamp))].slice(-CADENCE_OBSERVATION_LIMIT);
  return resolveSeriesFreshness({
    page: overviewChartFreshness(status),
    latest: latest
      ? {
          timestampMs: timestamp(latest),
          valid: latest.quality === "valid" && latest.value !== null && Number.isFinite(latest.value),
        }
      : null,
    staleAfterMs: latest ? resolveLiveFreshness(latest, observedCadenceMs(recent)).staleAfterMs : 0,
    now,
  });
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

function reduceTruthfully(segments: ChartSeries["segments"]): ChartSeries["segments"] {
  return reduceChartSegmentsToPointBudget(segments, "overview");
}

function buildSeries(
  source: readonly TelemetrySample[],
  status: DashboardTelemetryStatus,
  visualIndex: number,
  hiddenSeriesKeys: ReadonlySet<string>,
  soloSeriesKey: string | null,
  now: number,
): ChartSeries {
  const samples = orderedUniqueSamples(source);
  const firstSample = samples[0];
  if (!firstSample) throw new Error("Overview chart series requires at least one sample");
  const identity = overviewChartIdentity(firstSample);
  const key = chartSeriesKey(identity);
  const token = CHART_SERIES_TOKENS[visualIndex % CHART_SERIES_TOKENS.length];
  const segments = buildChartSegments(
    identity,
    samples.map((sample) => ({
      id: sample.event_id,
      timestampMs: timestamp(sample),
      value: sample.value,
      quality: sample.quality,
      sourceEventId: sample.event_id,
    })),
  );

  return {
    identity,
    name: identity.channelId,
    colorToken: token.color,
    dashStyle: token.dashStyle,
    markerShape: token.markerShape,
    ...overviewSeriesFreshness(status, samples, now),
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
    const group = groupedSamples.get(key);
    if (group) group.push(sample);
    else groupedSamples.set(key, [sample]);
    identities.set(key, identity);
  }

  const orderedKeys = [...groupedSamples.keys()].sort((left, right) => left.localeCompare(right, "en"));
  // The same channel id can exist on several nodes/controllers; a bare channel id
  // would then label two different lines identically in the legend and inspector.
  const channelIdCounts = new Map<string, number>();
  for (const identity of identities.values()) {
    channelIdCounts.set(identity.channelId, (channelIdCounts.get(identity.channelId) ?? 0) + 1);
  }
  const evaluationNow = options.now ?? Date.now();
  const entries = orderedKeys.map((key, index) => {
    const built = buildSeries(
      groupedSamples.get(key) ?? [],
      options.status,
      index,
      hiddenSeriesKeys,
      soloSeriesKey,
      evaluationNow,
    );
    const { channelId, nodeId, equipmentId } = built.identity;
    const ambiguous = (channelIdCounts.get(channelId) ?? 0) > 1;
    return {
      key,
      index,
      chartSeries: ambiguous ? { ...built, name: `${channelId} · ${nodeId} · ${equipmentId}` } : built,
    };
  });
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
        },
      };
    })
    .sort((left, right) => left.firstIndex - right.firstIndex)
    .map(({ id, nativeUnit, physicalQuantity, scene }) => ({ id, nativeUnit, physicalQuantity, scene }));
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
