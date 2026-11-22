import { chartSeriesKey } from "@/features/charts/domain";
import type { ChartRendererScene } from "@/features/charts/renderer-adapter";
import type { IntervalStatistics } from "@/features/charts/interval-statistics";
import { displayUnit } from "@/features/charts/units";
import { liveChannelKey } from "@/features/live/live-telemetry";
import { liveSampleChartIdentity } from "@/features/live/live-chart";
import type { TelemetrySample } from "@/lib/telemetry/types";

/** The only part of a chart group the statistics rows need. */
export interface SceneGroup {
  scene: Pick<ChartRendererScene, "series">;
}

export interface LiveStatisticsRow {
  seriesKey: string;
  color: string;
  name: string;
  unit: string;
  statistics: IntervalStatistics | null;
}

/** One row per currently visible plotted series of the Live chart scenes. */
export function buildLiveStatisticsRows(
  groups: readonly SceneGroup[],
  selected: readonly TelemetrySample[],
  domain: { fromMs: number; toMs: number },
  provider: ((channelKey: string, fromMs: number, toMs: number) => IntervalStatistics | null) | undefined,
): LiveStatisticsRow[] {
  const channelByChartKey = new Map(
    selected.map((sample) => [chartSeriesKey(liveSampleChartIdentity(sample)), liveChannelKey(sample)]),
  );
  return groups.flatMap((group) =>
    group.scene.series.flatMap((series) => {
      if (!series.visible) return [];
      const key = chartSeriesKey(series.identity);
      const channelKey = channelByChartKey.get(key);
      return [
        {
          seriesKey: key,
          color: series.colorToken,
          name: series.name,
          unit: displayUnit(series.identity.nativeUnit),
          statistics: provider && channelKey ? provider(channelKey, domain.fromMs, domain.toMs) : null,
        },
      ];
    }),
  );
}
