import { chartSeriesKey } from "@/features/charts/domain";
import type { IntervalStatistics } from "@/features/charts/interval-statistics";
import { buildRawStatisticsRows, type RawStatisticsRow } from "@/features/charts/raw-sample-statistics";
import { displayUnit } from "@/features/charts/units";
import { overviewColumnsKey } from "@/features/dashboard/overview-history";
import { overviewChartIdentity, type OverviewChartGroup } from "@/features/dashboard/overview-chart";
import { isTemperatureProbeSample } from "@/lib/telemetry/temperature-channel";
import type { TelemetrySample } from "@/lib/telemetry/types";

/** Exact statistics for the visible Overview/Session temperature series, from the RAW samples (#1675). */
export function overviewStatisticsRows(
  groups: readonly OverviewChartGroup[],
  samples: readonly TelemetrySample[],
  domain: { fromMs: number; toMs: number },
): RawStatisticsRow[] {
  const bySeries = new Map<string, TelemetrySample[]>();
  for (const sample of samples) {
    if (!isTemperatureProbeSample(sample)) continue;
    const key = chartSeriesKey(overviewChartIdentity(sample));
    const list = bySeries.get(key);
    if (list) list.push(sample);
    else bySeries.set(key, [sample]);
  }
  return groups.flatMap((group) =>
    buildRawStatisticsRows(
      group.scene.series,
      (identity) => bySeries.get(chartSeriesKey(identity)) ?? [],
      domain,
    ),
  );
}

/**
 * Exact statistics rows from the RAW history columns (P0 charts): the same numbers as
 * `overviewStatisticsRows`, without raw sample objects or a rebuild per render.
 */
export function overviewColumnStatisticsRows(
  groups: readonly OverviewChartGroup[],
  statisticsFor: (columnsKey: string, fromMs: number, toMs: number) => IntervalStatistics | null,
  domain: { fromMs: number; toMs: number },
): RawStatisticsRow[] {
  return groups.flatMap((group) =>
    group.scene.series
      .filter((entry) => entry.visible)
      .map((entry) => ({
        seriesKey: chartSeriesKey(entry.identity),
        color: entry.colorToken,
        name: entry.name,
        unit: displayUnit(entry.identity.nativeUnit),
        statistics: statisticsFor(overviewColumnsKey(entry.identity), domain.fromMs, domain.toMs),
      })),
  );
}
