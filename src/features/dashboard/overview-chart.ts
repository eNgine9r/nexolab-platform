import {
  CHART_SERIES_TOKENS,
  buildChartSegments,
  chartPointBudget,
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
import {
  historicalSeriesFreshness,
  resolveSeriesFreshness,
  type SeriesFreshness,
} from "@/features/charts/series-freshness";
import { groupCompatibleChartUnits, type ChartUnitGroup } from "@/features/charts/units";
import { liveHistorySegments } from "@/features/live/live-history";
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
  /**
   * P0 charts: `samples` is continuity-annotated display history (breaks already decided on RAW
   * data) and this source answers freshness from the RAW columns. Without it, `samples` are RAW.
   */
  rawSource?: OverviewRawSource;
}

export interface OverviewRawSource {
  /** Newest RAW sample of a series (valid or not), by its columns key. */
  latestFor: (columnsKey: string) => TelemetrySample | undefined;
  /** Newest distinct RAW timestamps of a series, oldest first. */
  recentTimestampsFor: (columnsKey: string) => number[];
}

function columnsKeyOf(identity: ChartSeriesIdentity): string {
  return [identity.nodeId, identity.equipmentId, identity.channelId, identity.metric, identity.nativeUnit]
    .map((part) => encodeURIComponent(part))
    .join("|");
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
  raw?: { latest: TelemetrySample | undefined; recent: number[] },
): SeriesFreshness {
  const latest = raw ? (raw.latest ?? samples.at(-1)?.sample) : samples.at(-1)?.sample;
  if (historical) {
    return historicalSeriesFreshness(
      latest
        ? { valid: latest.quality === "valid" && latest.value !== null && Number.isFinite(latest.value) }
        : null,
    );
  }
  const recent = raw ? raw.recent : recentDistinctTimestamps(samples, CADENCE_OBSERVATION_LIMIT);
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

function reduceTruthfully(
  segments: ChartSeries["segments"],
  maximumPoints?: number,
): ChartSeries["segments"] {
  return reduceChartSegmentsToPointBudget(segments, "overview", { maximumPoints });
}

/**
 * Display history is already reduced (full range plus, after a zoom, viewport detail within its own
 * budget); reducing it again over the whole span would discard the detail, so it is only bounded.
 */
const ANNOTATED_BUDGET_FACTOR = 3;

function buildSeries(
  source: readonly TelemetrySample[],
  status: DashboardTelemetryStatus,
  visualIndex: number,
  hiddenSeriesKeys: ReadonlySet<string>,
  soloSeriesKey: string | null,
  now: number,
  historical: boolean,
  rawSource?: OverviewRawSource,
): ChartSeries {
  const samples = orderedUniqueSamples(source);
  const firstSample = samples[0]?.sample;
  if (!firstSample) throw new Error("Overview chart series requires at least one sample");
  const identity = overviewChartIdentity(firstSample);
  const key = chartSeriesKey(identity);
  const token = CHART_SERIES_TOKENS[visualIndex % CHART_SERIES_TOKENS.length];
  const toPoint = (sample: TelemetrySample) => ({
    id: sample.event_id,
    timestampMs: timestamp(sample),
    value: sample.value,
    quality: sample.quality,
    sourceEventId: sample.event_id,
  });
  const segments = rawSource
    ? // Breaks were decided on RAW data (segment markers); never re-derived from display spacing.
      liveHistorySegments(samples.map((entry) => entry.sample)).flatMap((part, partIndex) =>
        buildChartSegments(identity, part.map(toPoint), { maximumSourceGapMs: Number.MAX_SAFE_INTEGER }).map(
          (segment, index) =>
            partIndex > 0 && index === 0 && segment.points[0]
              ? {
                  ...segment,
                  precedingBreak: { reason: "explicit_gap" as const, atMs: segment.points[0].timestampMs },
                }
              : segment,
        ),
      )
    : buildChartSegments(
        identity,
        samples.map((entry) => toPoint(entry.sample)),
      );
  const columnsKey = columnsKeyOf(identity);
  const raw = rawSource
    ? { latest: rawSource.latestFor(columnsKey), recent: rawSource.recentTimestampsFor(columnsKey) }
    : undefined;

  return {
    identity,
    name: identity.channelId,
    colorToken: token.color,
    dashStyle: token.dashStyle,
    markerShape: token.markerShape,
    ...overviewSeriesFreshness(status, samples, now, historical, raw),
    segments: reduceTruthfully(
      segments,
      rawSource ? chartPointBudget("overview") * ANNOTATED_BUDGET_FACTOR : undefined,
    ),
    visible: soloSeriesKey ? soloSeriesKey === key : !hiddenSeriesKeys.has(key),
    semanticMode: "instantaneous",
  };
}

export interface OverviewChartBaseGroup {
  id: string;
  nativeUnit: string;
  physicalQuantity: ChartUnitGroup["physicalQuantity"];
  series: ChartSeries[];
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
      options.rawSource,
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

/** Applies the x-domain to the built series (viewport detail is merged into the display history). */
export function overviewChartGroupsForDomain(
  base: readonly OverviewChartBaseGroup[],
  xDomain: ChartXDomain,
): OverviewChartGroup[] {
  return base.map((group) => ({
    id: group.id,
    nativeUnit: group.nativeUnit,
    physicalQuantity: group.physicalQuantity,
    scene: { series: group.series, xDomain },
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
