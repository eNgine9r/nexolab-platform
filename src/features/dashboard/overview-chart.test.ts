import { describe, expect, it } from "vitest";

import { chartSeriesKey } from "@/features/charts";
import type { TelemetrySample } from "@/lib/telemetry/types";

import { buildOverviewChartGroups, overviewResetDomain } from "./overview-chart";

const BASE = Date.parse("2026-08-12T10:00:00.000Z");

function sample(
  eventId: string,
  offsetMs: number,
  value: number | null,
  quality: TelemetrySample["quality"] = "valid",
  channelId = "104-03",
  overrides: Partial<TelemetrySample> = {},
): TelemetrySample {
  return {
    event_id: eventId,
    node_id: "edge-01",
    captured_at: new Date(BASE + offsetMs).toISOString(),
    metric: "temperature.probe",
    value,
    unit: "degC",
    quality,
    source: "dixell-xjp60d",
    equipment_id: "K104",
    channel_id: channelId,
    alarm: null,
    raw_value: value === null ? null : Math.round(value * 10),
    raw_status: null,
    ...overrides,
  };
}

function onlySeries(samples: TelemetrySample[]) {
  const groups = buildOverviewChartGroups({
    samples,
    status: "live",
    xDomain: { fromMs: BASE, toMs: BASE + 60_000 },
  });
  expect(groups).toHaveLength(1);
  expect(groups[0].scene.series).toHaveLength(1);
  return groups[0].scene.series[0];
}

describe("Overview canonical chart mapping", () => {
  it("breaks continuity across communication errors instead of connecting valid points", () => {
    const series = onlySeries([
      sample("before", 0, 4.1),
      sample("error", 5_000, null, "communication_error"),
      sample("after", 10_000, 4.3),
    ]);

    expect(series.segments).toHaveLength(2);
    expect(series.segments[0].points.map((point) => point.id)).toEqual(["before"]);
    expect(series.segments[1].precedingBreak?.reason).toBe("invalid_quality");
    expect(series.segments[1].points.map((point) => point.id)).toEqual(["after"]);
  });

  it("does not create a false gap for a stable 30-second source with small scheduler jitter", () => {
    const series = onlySeries([
      sample("a", 0, 4.1),
      sample("b", 30_000, 4.2),
      sample("c", 61_000, 4.3),
      sample("d", 91_000, 4.4),
    ]);

    expect(series.segments).toHaveLength(1);
  });

  it("breaks a silent timestamp outage after the normal source cadence is established", () => {
    const series = onlySeries([
      sample("a", 0, 4.1),
      sample("b", 5_000, 4.2),
      sample("c", 10_000, 4.3),
      sample("d", 15_000, 4.4),
      sample("after", 120_000, 4.5),
    ]);

    expect(series.segments).toHaveLength(2);
    expect(series.segments[1].precedingBreak?.reason).toBe("source_gap");
  });

  it("deduplicates the same event when history and the latest tail overlap", () => {
    const duplicate = sample("same-event", 10_000, 4.2);
    const series = onlySeries([sample("before", 0, 4.1), duplicate, { ...duplicate }]);

    expect(series.segments.flatMap((segment) => segment.points).map((point) => point.id)).toEqual([
      "before",
      "same-event",
    ]);
  });

  it("never creates chart alarm annotations from telemetry sample alarm context", () => {
    const samples = [
      sample("normal", 0, 4.1),
      sample("alarm", 5_000, 9.5, "valid", "104-03", { alarm: "high" }),
      sample("recovery", 10_000, 4.2),
    ];
    const groups = buildOverviewChartGroups({
      samples,
      status: "live",
      xDomain: { fromMs: BASE, toMs: BASE + 60_000 },
    });

    expect(groups[0].scene.events).toBeUndefined();
    expect(
      groups[0].scene.series[0].segments
        .flatMap((segment) => segment.points)
        .some((point) => point.pinReasons?.includes("alarm")),
    ).toBe(false);
  });

  it("keeps stable series identity and visual tokens regardless of input order", () => {
    const first = buildOverviewChartGroups({
      samples: [sample("b", 0, 6.2, "valid", "106-03"), sample("a", 0, 4.2, "valid", "104-03")],
      status: "live",
      xDomain: { fromMs: BASE, toMs: BASE + 60_000 },
    });
    const second = buildOverviewChartGroups({
      samples: [sample("a", 0, 4.2, "valid", "104-03"), sample("b", 0, 6.2, "valid", "106-03")],
      status: "live",
      xDomain: { fromMs: BASE, toMs: BASE + 60_000 },
    });

    const identityAndColor = (groups: typeof first) =>
      groups.flatMap((group) =>
        group.scene.series.map((series) => ({
          key: chartSeriesKey(series.identity),
          color: series.colorToken,
          name: series.name,
        })),
      );

    expect(identityAndColor(second)).toEqual(identityAndColor(first));
  });

  it("uses canonical bounded reduction while preserving local extrema", () => {
    const samples = Array.from({ length: 300 }, (_, index) =>
      sample(`p-${index}`, index * 1_000, index === 140 ? -50 : index === 160 ? 100 : 4 + (index % 5) / 10),
    );
    const series = onlySeries(samples);
    const points = series.segments.flatMap((segment) => segment.points);

    expect(points.length).toBeLessThanOrEqual(240);
    expect(points.some((point) => point.value === -50)).toBe(true);
    expect(points.some((point) => point.value === 100)).toBe(true);
    expect(points[0].id).toBe("p-0");
    expect(points.at(-1)?.id).toBe("p-299");
  });

  it("anchors reset range to the newest real sample while preserving range duration", () => {
    const domain = overviewResetDomain(
      "1h",
      {
        from: new Date(BASE - 60 * 60 * 1_000).toISOString(),
        to: new Date(BASE).toISOString(),
      },
      [sample("tail", 15_000, 4.3)],
    );

    expect(domain.toMs).toBe(BASE + 15_000);
    expect(domain.toMs - domain.fromMs).toBe(60 * 60 * 1_000);
  });
});
