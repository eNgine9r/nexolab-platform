import { chartSeriesKey } from "@/features/charts";
import type { IntervalStatistics } from "@/features/charts/interval-statistics";
import { savedDashboardChartIdentity, type SavedDashboardChartGroup } from "@/features/live-dashboards/chart";
import {
  savedDashboardSeriesLabel,
  savedDashboardSeriesUnit,
} from "@/features/live-dashboards/embraco-series";
import { dashboardItemIdentity } from "@/features/live-dashboards/model";
import type { LiveDashboardSeries } from "@/features/live-dashboards/types";

export interface DashboardStatisticsRow {
  seriesKey: string;
  color: string;
  name: string;
  unit: string;
  statistics: IntervalStatistics | null;
}

export type DashboardStatisticsProvider = (
  itemIdentity: string,
  fromMs: number,
  toMs: number,
) => IntervalStatistics | null;

/**
 * One row per currently VISIBLE plotted series (hide/solo respected), in chart order.
 * Statistics come from raw persisted samples, never from reduced chart points.
 */
export function buildDashboardStatisticsRows(
  dashboardId: string,
  series: readonly LiveDashboardSeries[],
  groups: readonly SavedDashboardChartGroup[],
  domain: { fromMs: number; toMs: number },
  provider: DashboardStatisticsProvider | undefined,
): DashboardStatisticsRow[] {
  const byChartKey = new Map(
    series.map((source) => [chartSeriesKey(savedDashboardChartIdentity(dashboardId, source)), source]),
  );
  return groups.flatMap((group) =>
    group.scene.series.flatMap((chartSeries) => {
      if (!chartSeries.visible) return [];
      const key = chartSeriesKey(chartSeries.identity);
      const source = byChartKey.get(key);
      if (!source) return [];
      return [
        {
          seriesKey: key,
          color: chartSeries.colorToken,
          name: savedDashboardSeriesLabel(source.item),
          unit: savedDashboardSeriesUnit(source.item),
          statistics: provider
            ? provider(dashboardItemIdentity(source.item), domain.fromMs, domain.toMs)
            : null,
        },
      ];
    }),
  );
}
