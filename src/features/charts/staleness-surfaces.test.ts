import { describe, expect, it } from "vitest";

import type { EnergyCadenceAuthority } from "@/features/energy/energy-cadence-authority";
import { buildEnergyChartScene } from "@/features/energy/energy-chart";
import { ENERGY_METERS } from "@/features/energy/energy-telemetry";
import { EMBRACO_METRICS } from "@/features/refrigeration/controller-monitoring";
import { buildEmbracoCompressorScene } from "@/features/refrigeration/controller-chart";
import type { TelemetrySample } from "@/lib/telemetry/types";

import { applyFreshnessClock } from "./series-freshness";

const T0 = Date.parse("2026-11-10T00:00:00Z");

function energy(
  metric: string,
  unit: string,
  index: number,
  quality: TelemetrySample["quality"] = "valid",
): TelemetrySample {
  const meter = ENERGY_METERS[0];
  return {
    event_id: `${metric}-${index}`,
    node_id: "edge-01",
    captured_at: new Date(T0 + index * 10_000).toISOString(),
    metric,
    value: quality === "valid" ? 100 + index : null,
    unit,
    quality,
    source: "f-and-f-le-01mp",
    equipment_id: meter.equipmentId,
    channel_id: `${meter.unitId}-${metric}`,
    alarm: null,
    raw_value: 1,
    raw_status: null,
  };
}

describe("Energy per-series staleness (#1677)", () => {
  const meter = ENERGY_METERS[0];
  const window = { from: new Date(T0).toISOString(), to: new Date(T0 + 3_600_000).toISOString() };
  const build = (now: number, authority: EnergyCadenceAuthority | null = null) =>
    buildEnergyChartScene({
      samples: [
        energy("electrical.power.active", "W", 359), // newest at +3590 s
        energy("electrical.voltage", "V", 100), // silent since +1000 s
        energy("electrical.current", "A", 350), // older valid poll
        energy("electrical.current", "A", 358, "communication_error"), // newest poll failed
      ],
      selectedMetrics: ["electrical.power.active", "electrical.voltage", "electrical.current"],
      selectedUnitIds: [meter.unitId],
      status: "live",
      historyWindow: window,
      cadenceAuthority: authority,
      now,
    });
  const byMetric = (scene: ReturnType<typeof build>) =>
    Object.fromEntries(scene.series.map((series) => [series.identity.metric, series]));

  it("marks fresh, silent and failing meters live / stale / invalid on one chart", () => {
    const series = byMetric(build(T0 + 3_600_000));
    expect(series["electrical.power.active"].freshness).toBe("live");
    expect(series["electrical.voltage"].freshness).toBe("stale");
    expect(series["electrical.current"].freshness).toBe("invalid");
    expect(series["electrical.power.active"].freshUntilMs).toBe(T0 + 3_590_000 + 30_000);
  });

  it("uses the cadence authority's per-meter threshold instead of the 30 s default", () => {
    const authority = {
      maximumSourceGapMs: () => 120_000,
    } as unknown as EnergyCadenceAuthority;
    const slow = byMetric(build(T0 + 3_590_000 + 100_000, authority));
    expect(slow["electrical.power.active"].freshness).toBe("live"); // 100 s < 120 s
    const defaultThreshold = byMetric(build(T0 + 3_590_000 + 100_000));
    expect(defaultThreshold["electrical.power.active"].freshness).toBe("stale");
  });

  it("lets page connectivity win and flips an expired series on a clock tick without a rebuild", () => {
    const offline = buildEnergyChartScene({
      samples: [energy("electrical.power.active", "W", 359)],
      selectedMetrics: ["electrical.power.active"],
      selectedUnitIds: [meter.unitId],
      status: "offline",
      historyWindow: window,
      now: T0 + 3_600_000,
    });
    expect(offline.series[0].freshness).toBe("offline");
    const live = build(T0 + 3_600_000);
    const groups = [{ scene: { series: live.series, xDomain: live.xDomain } }];
    expect(applyFreshnessClock(groups, T0 + 3_600_000)).toBe(groups);
    const later = applyFreshnessClock(groups, T0 + 3_700_000);
    expect(
      later[0].scene.series.find((entry) => entry.identity.metric === "electrical.power.active")?.freshness,
    ).toBe("stale");
  });
});

describe("Refrigeration per-series staleness (#1677)", () => {
  function speed(index: number, atMs: number): TelemetrySample {
    return {
      event_id: `speed-${index}`,
      node_id: "edge-01",
      captured_at: new Date(atMs).toISOString(),
      metric: EMBRACO_METRICS.compressorSpeed,
      value: 2400,
      unit: "rpm",
      quality: "valid",
      source: "embraco-sync",
      equipment_id: "EMBRACO-2",
      channel_id: "2-compressor-speed",
      alarm: null,
      raw_value: 2400,
      raw_status: null,
    };
  }
  const range = { from: new Date(T0), to: new Date(T0 + 3_600_000) } as Parameters<
    typeof buildEmbracoCompressorScene
  >[1];

  it("derives the threshold from the series' own raw cadence (60 s channel: 105 s)", () => {
    const history = new Map([
      [
        EMBRACO_METRICS.compressorSpeed,
        [0, 60_000, 120_000].map((offset, index) => speed(index, T0 + offset)),
      ],
    ]);
    const scene = buildEmbracoCompressorScene(history, range, true, undefined, T0 + 130_000);
    const series = scene.series[0];
    expect(series.freshUntilMs).toBe(T0 + 120_000 + 105_000);
  });

  it("reports offline for an offline controller regardless of the newest sample", () => {
    const history = new Map([[EMBRACO_METRICS.compressorSpeed, [speed(0, T0)]]]);
    expect(
      buildEmbracoCompressorScene(history, range, false, undefined, T0 + 5_000).series[0].freshness,
    ).toBe("offline");
  });
});
