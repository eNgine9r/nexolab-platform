import { describe, expect, it } from "vitest";

import { chartSeriesKey } from "@/features/charts/domain";

import { buildLiveChartGroups } from "./live-chart";
import {
  liveIntervalStatistics,
  pruneLiveIntervalSamples,
  recordLiveIntervalSamples,
  type LiveIntervalColumns,
} from "./live-interval-columns";
import { buildLiveStatisticsRows } from "./live-interval-statistics";
import { liveChannelKey } from "./live-telemetry";
import type { TelemetrySample } from "@/lib/telemetry/types";

const T0 = Date.parse("2026-11-22T00:00:00Z");

function sample(
  channel: string,
  index: number,
  value: number | null,
  quality: TelemetrySample["quality"] = "valid",
): TelemetrySample {
  return {
    event_id: `${channel}-${index}`,
    node_id: "edge-1",
    captured_at: new Date(T0 + index * 10_000).toISOString(),
    metric: "temperature",
    value,
    unit: "degC",
    quality,
    source: "test",
    equipment_id: "K106",
    channel_id: channel,
    alarm: null,
    raw_value: value,
    raw_status: null,
  };
}

describe("Live interval statistics (#1660)", () => {
  it("computes exact statistics per channel from raw samples, counting failures separately", () => {
    const store: LiveIntervalColumns = {};
    const samples = [
      ...Array.from({ length: 61 }, (_, index) => sample("a", index, index)),
      sample("a", 100, null, "communication_error"),
      ...Array.from({ length: 61 }, (_, index) => sample("b", index, 5)),
    ];
    recordLiveIntervalSamples(store, samples);
    const key = liveChannelKey(sample("a", 0, 0));
    const stats = liveIntervalStatistics(store, key, T0, T0 + 1_000_000);
    expect(stats).toMatchObject({ min: 0, max: 60, validCount: 61, invalidCount: 1 });
    expect(liveIntervalStatistics(store, liveChannelKey(sample("b", 0, 0)), T0, T0 + 600_000)).toMatchObject({
      min: 5,
      max: 5,
      average: 5,
    });
    expect(liveIntervalStatistics(store, "unknown", T0, T0 + 1)).toBeNull();
  });

  it("ignores duplicate history/live copies and prunes samples that left a rolling window", () => {
    const store: LiveIntervalColumns = {};
    const batch = Array.from({ length: 10 }, (_, index) => sample("a", index, index));
    recordLiveIntervalSamples(store, batch);
    recordLiveIntervalSamples(store, batch);
    const key = liveChannelKey(batch[0]);
    expect(liveIntervalStatistics(store, key, T0, T0 + 1e6)?.validCount).toBe(10);
    pruneLiveIntervalSamples(store, T0 + 50_000);
    expect(liveIntervalStatistics(store, key, T0, T0 + 1e6)?.validCount).toBe(5);
  });

  it("builds one row per visible plotted series and follows hide", () => {
    const a = sample("a", 59, 59);
    const b = sample("b", 59, 5);
    const store: LiveIntervalColumns = {};
    recordLiveIntervalSamples(store, [
      ...Array.from({ length: 60 }, (_, index) => sample("a", index, index)),
      ...Array.from({ length: 60 }, (_, index) => sample("b", index, 5)),
    ]);
    const domain = { fromMs: T0, toMs: T0 + 600_000 };
    const history = [a, b];
    const buildGroups = (hidden: ReadonlySet<string>) =>
      buildLiveChartGroups({
        selectedIdentities: [a, b],
        historySamples: history,
        status: "live",
        xDomain: domain,
        hiddenSeriesKeys: hidden,
      });
    const provider = (key: string, from: number, to: number) => liveIntervalStatistics(store, key, from, to);
    const rows = buildLiveStatisticsRows(buildGroups(new Set()), [a, b], domain, provider);
    expect(rows).toHaveLength(2);
    expect(rows.map((row) => row.unit)).toEqual(["°C", "°C"]);
    expect(rows[0].statistics).toMatchObject({ min: 0, max: 59, validCount: 60 });
    const firstSeries = buildGroups(new Set())[0].scene.series[0];
    const hiddenKey = chartSeriesKey(firstSeries.identity);
    expect(buildLiveStatisticsRows(buildGroups(new Set([hiddenKey])), [a, b], domain, provider)).toHaveLength(
      1,
    );
    expect(
      buildLiveStatisticsRows(buildGroups(new Set()), [a, b], domain, undefined)[0].statistics,
    ).toBeNull();
  });
});
