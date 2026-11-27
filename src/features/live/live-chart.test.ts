import { describe, expect, it } from "vitest";

import { buildChartYAxisModel, chartSeriesKey } from "@/features/charts";
import type { TelemetrySample } from "@/lib/telemetry/types";

import {
  buildLiveChartGroups,
  liveSampleChartIdentity,
  liveSeriesFreshness,
  liveStatusChartFreshness,
} from "./live-chart";
import { LIVE_SELECTION_LIMIT, liveChannelKey } from "./live-telemetry";

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

  it("shows authorized channel names in chart legend without changing history or keys", () => {
    const identity = sample("latest", "2026-08-11T12:59:00Z", 5);
    const named = buildLiveChartGroups({
      selectedIdentities: [identity],
      historySamples: [identity],
      status: "live",
      xDomain: domain,
      displayNames: { "edge-01/t1": "Подача повітря" },
    });
    const unnamed = buildLiveChartGroups({
      selectedIdentities: [identity],
      historySamples: [identity],
      status: "live",
      xDomain: domain,
      displayNames: { "other-node/t1": "Інший датчик" },
    });
    // #1852: the operator name stands alone; the unnamed channel keeps its technical identity.
    expect(named[0].scene.series[0].name).toBe("Подача повітря");
    expect(unnamed[0].scene.series[0].name).toContain("t1");
    expect(named[0].scene.series[0].identity).toEqual(unnamed[0].scene.series[0].identity);
    expect(named[0].scene.series[0].segments).toEqual(unnamed[0].scene.series[0].segments);
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

  it("renders V/A/W from one equipment context on one synchronized canvas", () => {
    const voltage = sample("v", "2026-08-11T12:30:00Z", 230, "V", {
      channel_id: "voltage",
      metric: "electrical.voltage",
    });
    const current = sample("a", "2026-08-11T12:30:00Z", 2.4, "A", {
      channel_id: "current",
      metric: "electrical.current",
    });
    const power = sample("w", "2026-08-11T12:30:00Z", 540, "W", {
      channel_id: "power",
      metric: "electrical.active_power",
    });
    const groups = buildLiveChartGroups({
      selectedIdentities: [voltage, current, power],
      historySamples: [voltage, current, power],
      status: "live",
      xDomain: domain,
    });

    expect(groups).toHaveLength(1);
    expect(groups[0].equipmentId).toBe("case-01");
    expect(new Set(groups[0].nativeUnits)).toEqual(new Set(["V", "A", "W"]));
    expect(groups[0].scene.series).toHaveLength(3);
    expect(buildChartYAxisModel(groups[0].scene.series).visibleAxes).toHaveLength(3);
  });

  it("keeps different equipment contexts isolated", () => {
    const temperature = sample("t", "2026-08-11T12:30:00Z", 5, "°C");
    const voltage = sample("v", "2026-08-11T12:30:00Z", 230, "V", {
      equipment_id: "meter-02",
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
    expect(groups.map((group) => group.equipmentId).sort()).toEqual(["case-01", "meter-02"]);
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

  it("applies multi-axis hide and solo without changing series identity", () => {
    const voltage = sample("a", "2026-08-11T12:00:00Z", 230, "V", {
      channel_id: "voltage",
      metric: "voltage",
    });
    const current = sample("b", "2026-08-11T12:00:00Z", 2, "A", {
      channel_id: "current",
      metric: "current",
    });
    const voltageKey = chartSeriesKey(liveSampleChartIdentity(voltage));
    const currentKey = chartSeriesKey(liveSampleChartIdentity(current));

    const hidden = buildLiveChartGroups({
      selectedIdentities: [voltage, current],
      historySamples: [voltage, current],
      status: "live",
      xDomain: domain,
      hiddenSeriesKeys: new Set([currentKey]),
    });
    expect(hidden[0].scene.series.map((series) => series.visible)).toEqual([true, false]);
    expect(buildChartYAxisModel(hidden[0].scene.series).visibleAxes).toHaveLength(1);

    const solo = buildLiveChartGroups({
      selectedIdentities: [voltage, current],
      historySamples: [voltage, current],
      status: "live",
      xDomain: domain,
      soloSeriesKey: voltageKey,
    });
    expect(solo[0].scene.series.map((series) => series.visible)).toEqual([true, false]);
    expect(buildChartYAxisModel(solo[0].scene.series).visibleAxes).toHaveLength(1);
    expect(chartSeriesKey(solo[0].scene.series[0].identity)).toBe(voltageKey);
    expect(chartSeriesKey(solo[0].scene.series[1].identity)).toBe(currentKey);
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

describe("per-series freshness (chart audit 2026-11-21)", () => {
  const now = Date.parse("2026-08-11T13:00:00Z");
  const fresh = sample("fresh", "2026-08-11T12:59:50Z", 4.2, "°C", { channel_id: "t1" });
  const silent = sample("silent", "2026-08-11T12:40:00Z", 3.9, "°C", { channel_id: "t2" });
  const unknown = sample("unknown", "2026-08-11T12:59:55Z", null, "°C", {
    channel_id: "t3",
    quality: "unknown",
  });
  const latest = Object.fromEntries([fresh, silent, unknown].map((item) => [liveChannelKey(item), item]));

  it("never lets one live channel mark a silent or invalid channel as live", () => {
    const [group] = buildLiveChartGroups({
      selectedIdentities: [fresh, silent, unknown],
      historySamples: [fresh, silent],
      status: "live", // page-wide status is live because t1 is fresh
      xDomain: domain,
      latestSamples: latest,
      now,
    });
    const byChannel = Object.fromEntries(group.scene.series.map((item) => [item.identity.channelId, item]));
    expect(byChannel.t1.freshness).toBe("live");
    expect(byChannel.t2.freshness).toBe("stale");
    expect(byChannel.t3.freshness).toBe("invalid");
    expect(byChannel.t3.latest).toEqual({
      timestampMs: Date.parse(unknown.captured_at),
      value: null,
      quality: "unknown",
    });
  });

  it("keeps connectivity states and the legacy page-wide behaviour when no latest samples are supplied", () => {
    expect(liveSeriesFreshness("reconnecting", fresh, liveChannelKey(fresh), undefined, now)).toBe(
      "reconnecting",
    );
    expect(liveSeriesFreshness("offline", fresh, liveChannelKey(fresh), undefined, now)).toBe("offline");
    const [legacy] = buildLiveChartGroups({
      selectedIdentities: [silent],
      historySamples: [silent],
      status: "live",
      xDomain: domain,
    });
    expect(legacy.scene.series[0].freshness).toBe("live");
    expect(legacy.scene.series[0].latest).toBeUndefined();
  });
});

describe("Live Data with the full comparison limit (#1654)", () => {
  it("plots every one of the maximum selected channels across equipment and keeps each scene within five Y axes", () => {
    const units = ["°C", "%", "V", "A", "W", "Hz"];
    const identities = Array.from({ length: LIVE_SELECTION_LIMIT }, (_, index) =>
      sample(`id-${index}`, "2026-08-11T12:59:00Z", index, units[index % units.length], {
        equipment_id: `device-${index % 4}`,
        channel_id: `ch-${index}`,
        metric: `metric-${index % units.length}`,
      }),
    );
    const groups = buildLiveChartGroups({
      selectedIdentities: identities,
      historySamples: identities,
      status: "live",
      xDomain: domain,
    });
    expect(groups.flatMap((group) => group.scene.series)).toHaveLength(LIVE_SELECTION_LIMIT);
    for (const group of groups) {
      expect(buildChartYAxisModel(group.scene.series).allAxes.length).toBeLessThanOrEqual(5);
    }
  });
});
