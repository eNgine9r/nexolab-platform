import { describe, expect, it } from "vitest";

import { chartSeriesKey } from "@/features/charts/domain";
import { buildOverviewChartGroups } from "@/features/dashboard/overview-chart";
import { overviewStatisticsRows } from "@/features/dashboard/overview-statistics";
import { EnergyRawStatistics, energyStatisticsKey } from "@/features/energy/energy-raw-statistics";
import { ENERGY_METERS } from "@/features/energy/energy-telemetry";
import { EMBRACO_METRICS } from "@/features/refrigeration/controller-monitoring";
import {
  buildEmbracoOperatorCelsiusScene,
  buildEmbracoTemperatureStatisticsRows,
} from "@/features/refrigeration/controller-chart";
import type { TelemetrySample } from "@/lib/telemetry/types";

import { buildRawStatisticsRows, columnsFromRawSamples } from "./raw-sample-statistics";

// Well in the past so no sample is rejected as future skew.
const T0 = Date.parse("2026-11-10T00:00:00Z");
const DOMAIN = { fromMs: T0, toMs: T0 + 600_000 };

function sample(
  channel: string,
  index: number,
  value: number | null,
  quality: TelemetrySample["quality"] = "valid",
  extra: Partial<TelemetrySample> = {},
): TelemetrySample {
  return {
    event_id: `${channel}-${index}`,
    node_id: "edge-1",
    captured_at: new Date(T0 + index * 10_000).toISOString(),
    metric: "temperature.probe",
    value,
    unit: "degC",
    quality,
    source: "test",
    equipment_id: "K106",
    channel_id: channel,
    alarm: null,
    raw_value: value,
    raw_status: null,
    ...extra,
  };
}

describe("raw sample statistics helpers (#1675)", () => {
  it("counts non-valid samples separately and never as zero", () => {
    const columns = columnsFromRawSamples([
      sample("106-01", 0, 5),
      sample("106-01", 1, null, "communication_error"),
      sample("106-01", 2, 7),
    ]);
    expect(columns.validValues).toEqual([5, 7]);
    expect(columns.invalidTimestamps).toHaveLength(1);
  });

  it("reports null statistics for a visible series without raw samples", () => {
    const groups = buildOverviewChartGroups({
      samples: [sample("106-01", 0, 5), sample("106-01", 1, 6)],
      status: "live",
      xDomain: DOMAIN,
      now: DOMAIN.toMs,
    });
    const rows = buildRawStatisticsRows(groups[0].scene.series, () => [], DOMAIN);
    expect(rows[0].statistics).toBeNull();
  });
});

describe("Overview / Session statistics come from RAW samples", () => {
  it("is exact even when the chart reduced the series", () => {
    const raw = Array.from({ length: 3_000 }, (_, index) =>
      sample("106-01", index, index === 1_234 ? 41 : 4),
    );
    const domain = { fromMs: T0, toMs: T0 + 3_000 * 10_000 };
    const groups = buildOverviewChartGroups({
      samples: raw,
      status: "live",
      xDomain: domain,
      now: domain.toMs,
    });
    const plotted = groups[0].scene.series[0].segments.flatMap((segment) => segment.points).length;
    expect(plotted).toBeLessThan(3_000); // chart is reduced…
    const [row] = overviewStatisticsRows(groups, raw, domain);
    expect(row.statistics).toMatchObject({ validCount: 3_000, max: 41, min: 4 }); // …statistics are not
    expect(row.unit).toBe("°C");
  });

  it("respects hidden series and ignores non-temperature samples", () => {
    const samples = [sample("106-01", 0, 5), sample("106-02", 0, 6), sample("106-02", 1, 7)];
    const groups = buildOverviewChartGroups({
      samples,
      status: "live",
      xDomain: DOMAIN,
      hiddenSeriesKeys: new Set([
        chartSeriesKey({
          nodeId: "edge-1",
          equipmentId: "K106",
          channelId: "106-01",
          metric: "temperature.probe",
          nativeUnit: "degC",
        }),
      ]),
      now: DOMAIN.toMs,
    });
    const rows = overviewStatisticsRows(groups, samples, DOMAIN);
    expect(rows).toHaveLength(1);
    expect(rows[0].statistics?.validCount).toBe(2);
  });
});

function power(index: number, value: number | null, quality: TelemetrySample["quality"] = "valid") {
  const meter = ENERGY_METERS[0];
  return {
    event_id: `p-${index}`,
    node_id: "edge-01",
    captured_at: new Date(T0 + index * 10_000).toISOString(),
    metric: "electrical.power.active",
    value,
    unit: "W",
    quality,
    source: "f-and-f-le-01mp",
    equipment_id: meter.equipmentId,
    channel_id: `${meter.unitId}-active-power`,
    alarm: null,
    raw_value: value,
    raw_status: null,
  } as TelemetrySample;
}

describe("EnergyRawStatistics", () => {
  const key = energyStatisticsKey(power(0, 1))!;

  it("answers exactly after a full load and extends with delta and live samples", () => {
    const store = new EnergyRawStatistics();
    const raw = Array.from({ length: 61 }, (_, index) => power(index, index === 30 ? 4_800 : 500));
    store.replace("24h", T0, raw, ["electrical.power.active"]);
    expect(store.statistics("24h", key, "electrical.power.active", T0, T0 + 600_000)).toMatchObject({
      max: 4_800,
      min: 500,
      validCount: 61,
    });
    store.append("24h", [power(61, 900), power(62, null, "communication_error")]);
    expect(store.statistics("24h", key, "electrical.power.active", T0, T0 + 700_000)).toMatchObject({
      validCount: 62,
      invalidCount: 1,
    });
  });

  it("is unavailable (null), never partial, without a base, for uncovered metrics or earlier intervals", () => {
    const store = new EnergyRawStatistics();
    expect(store.statistics("24h", key, "electrical.power.active", T0, T0 + 1)).toBeNull();
    store.append("24h", [power(0, 1)]); // no base → ignored
    expect(store.hasBase("24h")).toBe(false);
    store.replace(
      "24h",
      T0 + 100_000,
      [power(10, 5), power(11, 6), power(12, 7)],
      ["electrical.power.active"],
    );
    expect(store.statistics("24h", key, "electrical.power.active", T0, T0 + 200_000)).toBeNull(); // starts before the base
    expect(store.statistics("24h", key, "electrical.voltage", T0 + 100_000, T0 + 200_000)).toBeNull(); // metric not covered
    store.prune("24h", T0 + 110_000);
    expect(
      store.statistics("24h", key, "electrical.power.active", T0 + 110_000, T0 + 200_000)?.validCount,
    ).toBe(2); // samples at +110 s and +120 s remain after pruning the one at +100 s
  });

  it("ignores samples of metrics that were not part of the base load", () => {
    const store = new EnergyRawStatistics();
    store.replace("24h", T0, [power(0, 1)], ["electrical.voltage"]);
    store.append("24h", [power(1, 2)]);
    expect(store.statistics("24h", key, "electrical.voltage", T0, T0 + 100_000)?.validCount).toBe(0);
  });
});

describe("Embraco KK1 temperature statistics", () => {
  const range = { from: new Date(T0), to: new Date(T0 + 600_000) } as Parameters<
    typeof buildEmbracoOperatorCelsiusScene
  >[1];

  function embraco(index: number, raw: number | null): TelemetrySample {
    return {
      event_id: `k-${index}`,
      node_id: "edge-01",
      captured_at: new Date(T0 + index * 10_000).toISOString(),
      metric: EMBRACO_METRICS.cabinet,
      value: null,
      unit: "degC",
      quality: raw === null ? "communication_error" : "unknown",
      source: "embraco-sync",
      equipment_id: "EMBRACO-2",
      channel_id: "2-cabinet-temperature",
      alarm: null,
      raw_value: raw,
      raw_status: null,
    };
  }

  it("derives the provisional °C rows from RAW history with the operator scale and counts failures separately", () => {
    // Raw 400/410/420 → 4.00/4.10/4.20 °C; one failed poll; -22 counts → -0.22 °C.
    const history = new Map([
      [
        EMBRACO_METRICS.cabinet,
        [embraco(0, 400), embraco(1, 410), embraco(2, null), embraco(3, 65514), embraco(4, 420)],
      ],
    ]);
    const scene = buildEmbracoOperatorCelsiusScene(history, range, true, "EMBRACO-2", 5_000);
    const rows = buildEmbracoTemperatureStatisticsRows(history, scene, { fromMs: T0, toMs: T0 + 600_000 });
    const provisional = rows.find((row) => row.name.includes("попередня шкала"));
    expect(provisional?.statistics).toMatchObject({ validCount: 4, invalidCount: 1, min: -0.22, max: 4.2 });
    // The source quality stays unknown: the calibrated row has no valid measurement at all.
    const calibrated = rows.find((row) => !row.name.includes("попередня шкала"));
    if (calibrated) expect(calibrated.statistics?.validCount ?? 0).toBe(0);
  });

  it("produces no rows for another controller", () => {
    const history = new Map([[EMBRACO_METRICS.cabinet, [embraco(0, 400)]]]);
    const scene = buildEmbracoOperatorCelsiusScene(history, range, true, "OTHER");
    expect(buildEmbracoTemperatureStatisticsRows(history, scene, { fromMs: T0, toMs: T0 + 1000 })).toEqual(
      [],
    );
  });
});
