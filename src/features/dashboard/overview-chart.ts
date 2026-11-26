import {
  CHART_SERIES_TOKENS,
  buildChartSegments,
  chartSeriesKey,
  reduceChartSegmentsToPointBudget,
  type ChartFreshnessState,
  type ChartRendererScene,
  type ChartSegment,
  type ChartSeries,
  type ChartSeriesIdentity,
  type ChartXDomain,
} from "@/features/charts";
import {
  CADENCE_OBSERVATION_LIMIT,
  observedCadenceMs,
  resolveLiveFreshness,
} from "@/features/live/freshness";
import {
  historicalSeriesFreshness,
  resolveSeriesFreshness,
  type SeriesFreshness,
} from "@/features/charts/series-freshness";
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

export type OverviewHistoryPreset = keyof typeof HISTORY_RANGE_MS;
/** "custom" = a fixed operator-chosen window (#1683); its bounds come from the history window. */
export type OverviewHistoryRange = OverviewHistoryPreset | "custom";

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
  /** A fixed custom period (#1683): series have no liveness and are labelled historical. */
  historical?: boolean;
}

function timestamp(sample: TelemetrySample): number {
  const parsed = Date.parse(sample.captured_at);
  return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
}

interface TimedSample {
  sample: TelemetrySample;
  timestampMs: number;
}

/** Unique by event_id (earliest copy wins), time-ordered; each timestamp parsed once (#1827). */
function orderedUniqueSamples(samples: readonly TelemetrySample[]): TimedSample[] {
  const byEventId = new Map<string, TimedSample>();
  for (const sample of samples) {
    const timestampMs = timestamp(sample);
    const existing = byEventId.get(sample.event_id);
    if (!existing || timestampMs < existing.timestampMs)
      byEventId.set(sample.event_id, { sample, timestampMs });
  }
  return [...byEventId.values()].sort(
    (left, right) =>
      left.timestampMs - right.timestampMs || left.sample.event_id.localeCompare(right.sample.event_id),
  );
}

/** The newest `limit` distinct timestamps, oldest first, from a time-ordered series. */
function recentDistinctTimestamps(samples: readonly TimedSample[], limit: number): number[] {
  const recent: number[] = [];
  for (let index = samples.length - 1; index >= 0 && recent.length < limit; index -= 1) {
    const timestampMs = samples[index].timestampMs;
    if (recent.at(-1) !== timestampMs) recent.push(timestampMs);
  }
  return recent.reverse();
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
  samples: readonly TimedSample[],
  now: number,
  historical: boolean,
): SeriesFreshness {
  const latest = samples.at(-1)?.sample;
  if (historical) {
    return historicalSeriesFreshness(
      latest
        ? { valid: latest.quality === "valid" && latest.value !== null && Number.isFinite(latest.value) }
        : null,
    );
  }
  const recent = recentDistinctTimestamps(samples, CADENCE_OBSERVATION_LIMIT);
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
  historical: boolean,
): OverviewBaseSeries {
  const samples = orderedUniqueSamples(source);
  const firstSample = samples[0]?.sample;
  if (!firstSample) throw new Error("Overview chart series requires at least one sample");
  const identity = overviewChartIdentity(firstSample);
  const key = chartSeriesKey(identity);
  const token = CHART_SERIES_TOKENS[visualIndex % CHART_SERIES_TOKENS.length];
  const segments = buildChartSegments(
    identity,
    samples.map(({ sample, timestampMs }) => ({
      id: sample.event_id,
      timestampMs,
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
    ...overviewSeriesFreshness(status, samples, now, historical),
    segments: reduceTruthfully(segments),
    rawSegments: segments,
    visible: soloSeriesKey ? soloSeriesKey === key : !hiddenSeriesKeys.has(key),
    semanticMode: "instantaneous",
  };
}

/** A built Overview series plus its unreduced segments, for viewport detail (#1827). */
interface OverviewBaseSeries extends ChartSeries {
  rawSegments: readonly ChartSegment[];
}

export interface OverviewChartBaseGroup {
  id: string;
  nativeUnit: string;
  physicalQuantity: ChartUnitGroup["physicalQuantity"];
  series: OverviewBaseSeries[];
}

/**
 * #1827: every Overview series built once per history change — grouped, ordered, segmented from
 * RAW samples and reduced to the full-range budget. The zoom domain is applied separately by
 * `overviewChartGroupsForDomain`, so a zoom/pan no longer rebuilds the series.
 */
export function buildOverviewChartBase(
  options: Omit<OverviewChartBuildOptions, "xDomain">,
): OverviewChartBaseGroup[] {
  const hiddenSeriesKeys = options.hiddenSeriesKeys ?? new Set<string>();
  const soloSeriesKey = options.soloSeriesKey ?? null;
  const groupedSamples = new Map<string, TelemetrySample[]>();
  const identities = new Map<string, ChartSeriesIdentity>();

  // #1827: the probe check and the series key depend only on the identity fields, so they are
  // computed once per distinct identity instead of once per raw sample.
  const keyByIdentity = new Map<string, string | null>();
  for (const sample of options.samples) {
    const composite = `${sample.node_id}\u0000${sample.equipment_id}\u0000${sample.channel_id}\u0000${sample.metric}\u0000${sample.unit}`;
    let key = keyByIdentity.get(composite);
    if (key === undefined) {
      if (isTemperatureProbeSample(sample)) {
        const identity = overviewChartIdentity(sample);
        key = chartSeriesKey(identity);
        identities.set(key, identity);
      } else {
        key = null;
      }
      keyByIdentity.set(composite, key);
    }
    if (key === null) continue;
    const group = groupedSamples.get(key);
    if (group) group.push(sample);
    else groupedSamples.set(key, [sample]);
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
      options.historical ?? false,
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
        series,
      };
    })
    .sort((left, right) => left.firstIndex - right.firstIndex)
    .map(({ id, nativeUnit, physicalQuantity, series }) => ({ id, nativeUnit, physicalQuantity, series }));
}

/** Zoom detail covers the viewport plus this share of its width on each side, for smooth panning. */
export const OVERVIEW_DETAIL_MARGIN_RATIO = 0.5;

function lowerBoundPoint(points: readonly { timestampMs: number }[], targetMs: number): number {
  let low = 0;
  let high = points.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (points[middle].timestampMs < targetMs) low = middle + 1;
    else high = middle;
  }
  return low;
}

/**
 * Full-range points outside the detail range, and the RAW points inside it reduced to the series
 * budget (first/min/max/last per bucket, segment boundaries and pinned evidence kept). Breaks are
 * the raw segments' own, so nothing is joined or interpolated.
 */
function detailSegments(series: OverviewBaseSeries, fromMs: number, toMs: number): readonly ChartSegment[] {
  const inside: ChartSegment[] = [];
  for (const segment of series.rawSegments) {
    const start = lowerBoundPoint(segment.points, fromMs);
    const end = lowerBoundPoint(segment.points, toMs + 1);
    if (end > start) inside.push({ ...segment, points: segment.points.slice(start, end) });
  }
  if (inside.length === 0) return series.segments;
  let reduced: ChartSegment[];
  try {
    reduced = reduceTruthfully(inside);
  } catch {
    // The detail budget cannot hold every evidence boundary: keep the full-range points.
    return series.segments;
  }
  const insideById = new Map(reduced.map((segment) => [segment.id, segment.points]));
  return series.segments.map((segment) => {
    const points = insideById.get(segment.id);
    if (!points) return segment;
    return {
      ...segment,
      points: [
        ...segment.points.filter((point) => point.timestampMs < fromMs),
        ...points,
        ...segment.points.filter((point) => point.timestampMs > toMs),
      ],
    };
  });
}

/**
 * Applies the x-domain to the built series. With a committed zoom/pan (`detailDomain`), each series
 * shows the original measurements of the visible window (±50 %) from its raw segments.
 */
export function overviewChartGroupsForDomain(
  base: readonly OverviewChartBaseGroup[],
  xDomain: ChartXDomain,
  detailDomain: ChartXDomain | null = null,
): OverviewChartGroup[] {
  const span = detailDomain ? detailDomain.toMs - detailDomain.fromMs : 0;
  const detailFrom = detailDomain ? detailDomain.fromMs - span * OVERVIEW_DETAIL_MARGIN_RATIO : 0;
  const detailTo = detailDomain ? detailDomain.toMs + span * OVERVIEW_DETAIL_MARGIN_RATIO : 0;
  return base.map((group) => ({
    id: group.id,
    nativeUnit: group.nativeUnit,
    physicalQuantity: group.physicalQuantity,
    scene: {
      series: group.series.map((entry) => {
        // Raw segments stay out of the renderer scene.
        const series: Partial<OverviewBaseSeries> & ChartSeries = { ...entry };
        delete series.rawSegments;
        return detailDomain && span > 0
          ? { ...series, segments: detailSegments(entry, detailFrom, detailTo) }
          : series;
      }),
      xDomain,
    },
  }));
}

export function buildOverviewChartGroups(options: OverviewChartBuildOptions): OverviewChartGroup[] {
  return overviewChartGroupsForDomain(buildOverviewChartBase(options), options.xDomain);
}

export function overviewResetDomain(
  range: OverviewHistoryRange,
  historyWindow: { from: string; to: string } | null,
  samples: readonly TelemetrySample[],
): ChartXDomain {
  if (range === "custom") {
    // A fixed period is shown exactly as requested: no sample may stretch or shift it.
    const fromMs = historyWindow ? Date.parse(historyWindow.from) : Number.NaN;
    const toMs = historyWindow ? Date.parse(historyWindow.to) : Number.NaN;
    if (Number.isFinite(fromMs) && Number.isFinite(toMs) && toMs > fromMs) return { fromMs, toMs };
    const now = Date.now();
    return { fromMs: now - HISTORY_RANGE_MS["1h"], toMs: now };
  }
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
