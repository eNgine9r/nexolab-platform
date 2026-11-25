import { chartSeriesKey } from "@/features/charts/domain";
import { buildRawStatisticsRows, type RawStatisticsRow } from "@/features/charts/raw-sample-statistics";
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
