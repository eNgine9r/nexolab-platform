import { digitalLanesForMetric } from "@/features/charts/digital-channels";
import type { IntervalSampleColumns } from "@/features/charts/interval-statistics";
import {
  buildStateLane,
  summarizeLane,
  type LaneInterval,
  type LaneSummary,
} from "@/features/charts/state-lanes";
import { savedDashboardChannelLabel } from "@/features/live-dashboards/embraco-series";
import { dashboardItemIdentity } from "@/features/live-dashboards/model";
import type { LiveDashboardSeries } from "@/features/live-dashboards/types";

export interface DashboardStateLane {
  key: string;
  label: string;
  onMeaning: string;
  intervals: LaneInterval[];
  summary: LaneSummary;
}

/**
 * Digital state lanes of a Saved Dashboard (#1679): one lane per decoded state of every item whose
 * metric is a known digital channel, built from the RAW measurement columns (not the reduced chart
 * history) for exactly the visible interval, so zoom and the shared cursor stay in sync.
 */
export function buildDashboardStateLanes(
  series: readonly LiveDashboardSeries[],
  columnsFor: ((itemIdentity: string) => IntervalSampleColumns | undefined) | undefined,
  domain: { fromMs: number; toMs: number },
): DashboardStateLane[] {
  return series.flatMap((entry) => {
    const specs = digitalLanesForMetric(entry.item.metric);
    if (specs.length === 0) return [];
    const identity = dashboardItemIdentity(entry.item);
    const columns = columnsFor?.(identity);
    const channel = savedDashboardChannelLabel(entry.item);
    return specs.map((spec) => {
      const intervals = columns ? buildStateLane(columns, domain.fromMs, domain.toMs, spec.decode) : [];
      return {
        key: `${identity}:${spec.id}`,
        label: `${spec.label} · ${channel}`,
        onMeaning: spec.onMeaning,
        intervals,
        summary: summarizeLane(intervals),
      };
    });
  });
}
