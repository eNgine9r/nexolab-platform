import { describe, expect, it } from "vitest";

import { chartSeriesKey } from "@/features/charts/domain";
import type { TelemetrySample } from "@/lib/telemetry/types";

import {
  buildLiveChartGroups,
  liveSampleChartIdentity,
  liveStatusChartFreshness,
} from "./live-chart";

function sample(
  eventId: string,
  capturedAt: string,
  value: number | null,
  unit = "°C",
  overrides: Partial<TelemetrySample> = {},
): TelemetrySample {
  return {
    event_id: eventId,
    node_id: "edge-01",
    equipment_id: "case-01",
    channel_id: "t1",
    metric: "temperature",
    value,
    unit,
    quality: "valid",
    source: "modbus",
    alarm: null,
    raw_value: value,
    raw_status: null,
    captured_at: capturedAt,
    ...overrides,
  };
}

const domain = {
  fromMs: Date.parse("2026-08-11T12:00:00Z"),
  toMs: Date.parse("2026-08-11T13:00:00Z"),
};

describe("Live Data canonical chart mapping", () => {
  it("keeps quality and freshness as separate concepts", () => {
    const identity = sample("latest", "2026-08-11T12:59:00Z", 5);
    const groups = buildLiveChartGroups({
      selectedIdentities: [identity],
      historySamples: [identity],
      status: "reconnecting",
      xDomain: domain,
    });

    expect(groups[0].scene.series[0].freshness).toBe("reconnecting");
    expect(groups[0].scene.series[0].segments[0].points[0].quality).toBe("valid");
    expect(liveStatusChartFreshness("forbidden")).toBe("offline");
  });

  it("preserves explicit history gaps as separate chart segments", () => {
    const identity = sample("latest", "2026-08-11T12:30:00Z", 5);
    const history = [
      sample("a", "2026-08-11T12:00:00Z", 1),
      sample("nexolab-live-segment:b", "2026-08-11T12:10:00Z", 2),
    ];
    const groups = buildLiveChartGroups({
      selectedIdentities: [identity],
      historySamples: history,
      status: "live",
      xDomain: domain,
    });

    const segments = groups[0].scene.series[0].segments;
    expect(segments).toHaveLength(2);
    expect(segments[1].precedingBreak?.reason).toBe("explicit_gap");
  });

  it("groups only compatible native units into the same plot", () => {
    const temperature = sample("t", "2026-08-11T12:30:00Z", 5, "°C");
    const voltage = sample("v", "2026-08-11T12:30:00Z", 230, "V", {
      channel_id: "voltage",
      metric: "voltage",
    });
    const groups = buildLiveChartGroups({
      selectedIdentities: [temperature, voltage],
      historySamples: [temperature, voltage],
      status: "live",
      xDomain: domain,
    });

    expect(groups).toHaveLength(2);
    expect(groups.map((group) => group.nativeUnit).sort()).toEqual(["V", "°C"]);
  });

  it("never invents chart events or alarm pins from telemetry-sample alarm context", () => {
    const identity = sample("latest", "2026-08-11T12:30:00Z", 5);
    const history = [
      sample("a", "2026-08-11T12:00:00Z", 1),
      sample("b", "2026-08-11T12:05:00Z", 9, "°C", { alarm: "high" }),
      sample("c", "2026-08-11T12:10:00Z", 4),
    ];
    const groups = buildLiveChartGroups({
      selectedIdentities: [identity],
      historySamples: history,
      status: "live",
      xDomain: domain,
    });

    expect(groups[0].scene.events).toBeUndefined();
    expect(
      groups[0].scene.series[0].segments
        .flatMap((segment) => segment.points)
        .some((point) => point.pinReasons?.includes("alarm")),
    ).toBe(false);
  });

  it("applies show-hide and solo state without changing series identity", () => {
    const first = sample("a", "2026-08-11T12:00:00Z", 1);
    const second = sample("b", "2026-08-11T12:00:00Z", 2, "°C", { channel_id: "t2" });
    const firstKey = chartSeriesKey(liveSampleChartIdentity(first));
    const secondKey = chartSeriesKey(liveSampleChartIdentity(second));

    const hidden = buildLiveChartGroups({
      selectedIdentities: [first, second],
      historySamples: [first, second],
      status: "live",
      xDomain: domain,
      hiddenSeriesKeys: new Set([secondKey]),
    });
    expect(hidden[0].scene.series.map((series) => series.visible)).toEqual([true, false]);

    const solo = buildLiveChartGroups({
      selectedIdentities: [first, second],
      historySamples: [first, second],
      status: "live",
      xDomain: domain,
      soloSeriesKey: firstKey,
    });
    expect(solo[0].scene.series.map((series) => series.visible)).toEqual([true, false]);
  });

  it("marks cumulative energy series explicitly", () => {
    const energy = sample("e", "2026-08-11T12:00:00Z", 12.3, "kWh", {
      channel_id: "energy",
      metric: "total_energy",
    });
    const groups = buildLiveChartGroups({
      selectedIdentities: [energy],
      historySamples: [energy],
      status: "live",
      xDomain: domain,
    });
    expect(groups[0].scene.series[0].semanticMode).toBe("cumulative_counter");
  });
});
