import { describe, expect, it } from "vitest";

import { buildOverviewChartGroups } from "@/features/dashboard/overview-chart";
import type { TelemetrySample } from "@/lib/telemetry/types";

import type { ChartSeries } from "./domain";
import {
  applyFreshnessClock,
  newestSampleValidity,
  resolveSeriesFreshness,
  withInvalidNewestSample,
} from "./series-freshness";

const T0 = Date.parse("2026-11-22T00:00:00Z");

describe("resolveSeriesFreshness", () => {
  it("lets page connectivity win", () => {
    for (const page of ["connecting", "reconnecting", "offline"] as const) {
      expect(
        resolveSeriesFreshness({
          page,
          latest: { timestampMs: T0, valid: true },
          staleAfterMs: 1e6,
          now: T0,
        }),
      ).toEqual({ freshness: page });
    }
  });

  it("is live with a deadline for a recent valid sample, stale after it, invalid for a bad newest sample", () => {
    const live = resolveSeriesFreshness({
      page: "live",
      latest: { timestampMs: T0, valid: true },
      staleAfterMs: 105_000,
      now: T0 + 50_000,
    });
    expect(live).toEqual({ freshness: "live", freshUntilMs: T0 + 105_000 });
    expect(
      resolveSeriesFreshness({
        page: "live",
        latest: { timestampMs: T0, valid: true },
        staleAfterMs: 105_000,
        now: T0 + 106_000,
      }),
    ).toEqual({ freshness: "stale" });
    expect(
      resolveSeriesFreshness({
        page: "live",
        latest: { timestampMs: T0, valid: false },
        staleAfterMs: 105_000,
        now: T0,
      }).freshness,
    ).toBe("invalid");
    expect(resolveSeriesFreshness({ page: "live", latest: null, staleAfterMs: 0, now: T0 }).freshness).toBe(
      "stale",
    );
  });
});

describe("applyFreshnessClock", () => {
  function group(freshUntilMs: number | undefined, freshness: ChartSeries["freshness"] = "live") {
    const series = { freshness, freshUntilMs, segments: [] } as unknown as ChartSeries;
    return { id: "g", scene: { series: [series], xDomain: { fromMs: 0, toMs: 1 } } };
  }

  it("flips only expired live series and keeps identity when nothing changes", () => {
    const groups = [group(T0 + 1_000)];
    expect(applyFreshnessClock(groups, T0)).toBe(groups);
    const flipped = applyFreshnessClock(groups, T0 + 2_000);
    expect(flipped).not.toBe(groups);
    expect(flipped[0].scene.series[0].freshness).toBe("stale");
    expect(groups[0].scene.series[0].freshness).toBe("live");
  });

  it("never touches series without a deadline or non-live series", () => {
    const groups = [group(undefined), group(T0 - 1, "invalid"), group(T0 - 1, "offline")];
    expect(applyFreshnessClock(groups, T0 + 1e9)).toBe(groups);
  });
});

describe("invalid newest sample helpers", () => {
  it("reports invalid only for a live/stale page whose newest sample is not a valid measurement", () => {
    expect(withInvalidNewestSample("live", { valid: false })).toBe("invalid");
    expect(withInvalidNewestSample("stale", { valid: false })).toBe("invalid");
    expect(withInvalidNewestSample("live", { valid: true })).toBe("live");
    expect(withInvalidNewestSample("offline", { valid: false })).toBe("offline");
    expect(withInvalidNewestSample("live", null)).toBe("live");
  });

  it("judges validity by the newest sample regardless of array order", () => {
    const samples = [
      { captured_at: new Date(T0 + 20_000).toISOString(), quality: "communication_error", value: null },
      { captured_at: new Date(T0).toISOString(), quality: "valid", value: 4 },
    ];
    expect(newestSampleValidity(samples)).toEqual({ valid: false });
    expect(newestSampleValidity([])).toBeNull();
  });
});

function overviewSample(channel: string, offsetMs: number, quality: TelemetrySample["quality"] = "valid") {
  return {
    event_id: `${channel}-${offsetMs}`,
    node_id: "edge-1",
    captured_at: new Date(T0 + offsetMs).toISOString(),
    metric: "temperature.probe",
    value: quality === "valid" ? 4 : null,
    unit: "degC",
    quality,
    source: "test",
    equipment_id: "K106",
    channel_id: channel,
    alarm: null,
    raw_value: 4,
    raw_status: null,
  } satisfies TelemetrySample;
}

describe("Overview per-series freshness", () => {
  it("marks a silent channel stale and a failing channel invalid while a fresh channel stays live", () => {
    const now = T0 + 600_000;
    const samples = [
      overviewSample("106-01", 590_000),
      overviewSample("106-02", 100_000),
      overviewSample("106-03", 595_000, "communication_error"),
    ];
    const groups = buildOverviewChartGroups({
      samples,
      status: "live",
      xDomain: { fromMs: T0, toMs: now },
      now,
    });
    const byChannel = Object.fromEntries(
      groups.flatMap((group) => group.scene.series.map((entry) => [entry.identity.channelId, entry])),
    );
    expect(byChannel["106-01"].freshness).toBe("live");
    expect(byChannel["106-01"].freshUntilMs).toBeGreaterThan(now);
    expect(byChannel["106-02"].freshness).toBe("stale");
    expect(byChannel["106-03"].freshness).toBe("invalid");
  });

  it("uses the observed 60 s cadence from raw timestamps (live at 100 s, stale after 105 s)", () => {
    const samples = [0, 60_000, 120_000].map((offset) => overviewSample("106-04", offset));
    const stateAt = (now: number) =>
      buildOverviewChartGroups({ samples, status: "live", xDomain: { fromMs: T0, toMs: now }, now }).flatMap(
        (group) => group.scene.series,
      )[0].freshness;
    expect(stateAt(T0 + 120_000 + 100_000)).toBe("live");
    expect(stateAt(T0 + 120_000 + 110_000)).toBe("stale");
  });
});
