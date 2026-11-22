/**
 * Exact statistics rows for surfaces whose chart receives RAW samples and reduces them later
 * (Overview, Session history, Refrigeration) — #1675. The reduced chart series are used only for
 * names/colours/visibility; every number comes from the raw samples.
 */

import { chartSeriesKey, type ChartSeries, type ChartSeriesIdentity } from "./domain";
import {
  appendIntervalSample,
  computeIntervalStatistics,
  createIntervalSampleColumns,
  type IntervalSampleColumns,
  type IntervalStatistics,
} from "./interval-statistics";
import { displayUnit } from "./units";

export interface RawStatisticsRow {
  seriesKey: string;
  color: string;
  name: string;
  unit: string;
  statistics: IntervalStatistics | null;
}

interface RawSampleLike {
  captured_at: string;
  quality: string;
  value: number | null;
}

/** Valid = quality valid with a finite value; everything else is recorded as a non-valid poll. */
export function columnsFromRawSamples(samples: readonly RawSampleLike[]): IntervalSampleColumns {
  const columns = createIntervalSampleColumns();
  for (const sample of samples) {
    const valid = sample.quality === "valid" && sample.value !== null && Number.isFinite(sample.value);
    appendIntervalSample(columns, Date.parse(sample.captured_at), valid ? sample.value : null);
  }
  return columns;
}

/**
 * One row per visible series. `samplesFor` returns the RAW samples of a series identity (or an
 * empty list); series with no raw samples at all report null statistics instead of zeros.
 */
export function buildRawStatisticsRows(
  series: readonly ChartSeries[],
  samplesFor: (identity: ChartSeriesIdentity, series: ChartSeries) => readonly RawSampleLike[],
  domain: { fromMs: number; toMs: number },
): RawStatisticsRow[] {
  return series
    .filter((entry) => entry.visible)
    .map((entry) => {
      const samples = samplesFor(entry.identity, entry);
      return {
        seriesKey: chartSeriesKey(entry.identity),
        color: entry.colorToken,
        name: entry.name,
        unit: displayUnit(entry.identity.nativeUnit),
        statistics:
          samples.length === 0
            ? null
            : computeIntervalStatistics(columnsFromRawSamples(samples), domain.fromMs, domain.toMs),
      };
    });
}
