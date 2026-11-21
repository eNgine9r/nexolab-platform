import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import {
  CADENCE_OBSERVATION_LIMIT,
  DEFAULT_LIVE_STALE_AFTER_MS,
  EMPTY_CADENCE_OBSERVATIONS,
  MAX_ACQUISITION_CADENCE_MS,
  formatFreshnessBasis,
  isLiveSampleFresh,
  liveFreshnessFor,
  observedCadenceMs,
  recordCadenceObservation,
  resolveLiveFreshness,
  staleAfterForCadenceMs,
  type CadenceObservations,
} from "./freshness";
import { liveChannelKey, liveTelemetryState } from "./live-telemetry";

const T0 = Date.parse("2026-11-21T10:00:00.000Z");
const SECOND = 1_000;

function sample(overrides: Partial<TelemetrySample> = {}): TelemetrySample {
  return {
    event_id: "waveshare-ch3-0",
    node_id: "edge-01",
    captured_at: new Date(T0).toISOString(),
    metric: "current",
    value: 12.4,
    unit: "mA",
    quality: "valid",
    source: "waveshare-8ai",
    equipment_id: "WAVESHARE-8AI-1",
    channel_id: "ch3",
    alarm: null,
    raw_value: 12400,
    raw_status: null,
    ...overrides,
  };
}

function observe(key: string, timestamps: number[], start: CadenceObservations = EMPTY_CADENCE_OBSERVATIONS) {
  return timestamps.reduce((current, value) => recordCadenceObservation(current, key, value), start);
}

/** Simulates the 5 s UI clock between two on-time 60 s polls. */
function statesBetweenPolls(
  latest: TelemetrySample,
  staleAfterMs: number,
  intervalMs = 60 * SECOND,
  propagationMs = 2 * SECOND,
) {
  const captured = Date.parse(latest.captured_at);
  const states = new Set<string>();
  for (let now = captured + propagationMs; now < captured + intervalMs + propagationMs; now += 5 * SECOND) {
    states.add(liveTelemetryState(latest, now, staleAfterMs));
  }
  return states;
}

describe("#1522 regression: fixed 30 s threshold vs 60 s Waveshare cadence", () => {
  it("reproduces the false Live→stale oscillation with the legacy fixed threshold", () => {
    const states = statesBetweenPolls(sample(), DEFAULT_LIVE_STALE_AFTER_MS);
    expect(states).toEqual(new Set(["live", "stale"]));
  });

  it("keeps on-time 60 s samples Live once the cadence has been observed", () => {
    const latest = sample({ captured_at: new Date(T0 + 120 * SECOND).toISOString() });
    const key = liveChannelKey(latest);
    const observations = observe(key, [T0, T0 + 60 * SECOND, T0 + 120 * SECOND]);
    const freshness = liveFreshnessFor(latest, key, observations);

    expect(freshness).toEqual({
      staleAfterMs: 105 * SECOND,
      basis: "observed_cadence",
      cadenceMs: 60 * SECOND,
    });
    expect(statesBetweenPolls(latest, freshness.staleAfterMs)).toEqual(new Set(["live"]));
  });

  it("tolerates scheduler jitter around the nominal interval", () => {
    const key = "jitter";
    const observations = observe(key, [T0, T0 + 61_300, T0 + 119_200, T0 + 180_400]);
    expect(observedCadenceMs(observations[key])).toBe(57_900);
    expect(staleAfterForCadenceMs(57_900)).toBeGreaterThan(62 * SECOND);
  });
});

describe("genuinely overdue or disconnected data", () => {
  it("becomes stale after one fully missed 60 s poll (bounded threshold)", () => {
    const latest = sample();
    const key = liveChannelKey(latest);
    const observations = observe(key, [T0 - 120 * SECOND, T0 - 60 * SECOND, T0]);
    const freshness = liveFreshnessFor(latest, key, observations);

    expect(liveTelemetryState(latest, T0 + 100 * SECOND, freshness.staleAfterMs)).toBe("live");
    expect(liveTelemetryState(latest, T0 + 106 * SECOND, freshness.staleAfterMs)).toBe("stale");
    expect(liveTelemetryState(latest, T0 + 120 * SECOND + 1, freshness.staleAfterMs)).toBe("stale");
  });

  it("does not let a communication gap stretch the cadence and hide stale data", () => {
    const key = "gap";
    // 60 s cadence, then a 20 min outage, then recovery.
    const observations = observe(key, [T0, T0 + 60 * SECOND, T0 + 1_260 * SECOND, T0 + 1_320 * SECOND]);
    expect(observedCadenceMs(observations[key])).toBe(60 * SECOND);
  });

  it("ignores outage spacings longer than the maximum acquisition cadence", () => {
    const key = "outage";
    const observations = observe(key, [
      T0,
      T0 + MAX_ACQUISITION_CADENCE_MS + 1,
      T0 + 2 * MAX_ACQUISITION_CADENCE_MS + 2,
    ]);
    expect(observedCadenceMs(observations[key])).toBeNull();
  });

  it("caps the derived threshold for the slowest configurable cadence", () => {
    expect(staleAfterForCadenceMs(10 * MAX_ACQUISITION_CADENCE_MS)).toBe(
      staleAfterForCadenceMs(MAX_ACQUISITION_CADENCE_MS),
    );
  });
});

describe("quality is never masked by freshness", () => {
  it.each(["unknown", "sensor_error", "communication_error"] as const)(
    "preserves explicit %s quality even when the sample is fresh",
    (quality) => {
      const latest = sample({ quality, value: null });
      const key = liveChannelKey(latest);
      const observations = observe(key, [T0 - 120 * SECOND, T0 - 60 * SECOND, T0]);
      const freshness = liveFreshnessFor(latest, key, observations);
      expect(liveTelemetryState(latest, T0 + SECOND, freshness.staleAfterMs)).toBe(quality);
    },
  );
});

describe("bootstrap, server contract and backward compatibility", () => {
  it("falls back to the conservative default until two spacings are observed", () => {
    const latest = sample();
    const key = liveChannelKey(latest);
    expect(liveFreshnessFor(latest, key, observe(key, [T0]))).toEqual({
      staleAfterMs: DEFAULT_LIVE_STALE_AFTER_MS,
      basis: "default",
      cadenceMs: null,
    });
    expect(liveFreshnessFor(latest, key, observe(key, [T0 - 60 * SECOND, T0])).basis).toBe("default");
    expect(liveFreshnessFor(latest, key).basis).toBe("default");
  });

  it("never relaxes fast channels below the historical 30 s threshold", () => {
    expect(staleAfterForCadenceMs(5 * SECOND)).toBe(DEFAULT_LIVE_STALE_AFTER_MS);
    expect(staleAfterForCadenceMs(10 * SECOND)).toBe(DEFAULT_LIVE_STALE_AFTER_MS);
  });

  it("prefers an authoritative server stale_after_seconds over observed cadence", () => {
    const latest = sample({ stale_after_seconds: 150 });
    const key = liveChannelKey(latest);
    const freshness = liveFreshnessFor(latest, key, observe(key, [T0 - 20 * SECOND, T0 - 10 * SECOND, T0]));
    expect(freshness).toEqual({ staleAfterMs: 150 * SECOND, basis: "server_contract", cadenceMs: null });
    expect(liveTelemetryState(latest, T0 + 140 * SECOND)).toBe("live");
    expect(liveTelemetryState(latest, T0 + 151 * SECOND)).toBe("stale");
  });

  it.each([null, 0, -5, Number.NaN, Number.POSITIVE_INFINITY])(
    "ignores an invalid server threshold %s",
    (value) => {
      expect(resolveLiveFreshness({ stale_after_seconds: value }).basis).toBe("default");
    },
  );

  it("keeps the legacy liveTelemetryState default for samples without metadata", () => {
    expect(liveTelemetryState(sample(), T0 + 30 * SECOND)).toBe("live");
    expect(liveTelemetryState(sample(), T0 + 31 * SECOND)).toBe("stale");
    expect(liveTelemetryState(sample({ captured_at: "not-a-date" }), T0)).toBe("stale");
  });
});

describe("observation bookkeeping", () => {
  it("keeps independent channels independent", () => {
    const slow = liveChannelKey(sample());
    const fast = liveChannelKey(sample({ equipment_id: "DIXELL-106", channel_id: "106-03" }));
    let observations = observe(slow, [T0, T0 + 60 * SECOND, T0 + 120 * SECOND]);
    observations = observe(fast, [T0, T0 + 10 * SECOND, T0 + 20 * SECOND], observations);
    expect(observedCadenceMs(observations[slow])).toBe(60 * SECOND);
    expect(observedCadenceMs(observations[fast])).toBe(10 * SECOND);
  });

  it("deduplicates repeated timestamps and returns the same object when unchanged", () => {
    const first = observe("k", [T0, T0 + 60 * SECOND]);
    expect(recordCadenceObservation(first, "k", T0)).toBe(first);
    expect(recordCadenceObservation(first, "k", Number.NaN)).toBe(first);
  });

  it("orders out-of-order replayed samples and stays bounded", () => {
    const timestamps = Array.from({ length: 12 }, (_, index) => T0 + index * 60 * SECOND).reverse();
    const observations = observe("replay", timestamps);
    expect(observations.replay).toHaveLength(CADENCE_OBSERVATION_LIMIT);
    expect([...observations.replay]).toEqual([...observations.replay].sort((left, right) => left - right));
    expect(observedCadenceMs(observations.replay)).toBe(60 * SECOND);
  });

  it("adapts to a faster cadence immediately and to a slower one after old spacings age out", () => {
    let observations = observe("change", [T0, T0 + 60 * SECOND, T0 + 120 * SECOND]);
    observations = observe("change", [T0 + 130 * SECOND, T0 + 140 * SECOND], observations);
    expect(observedCadenceMs(observations.change)).toBe(10 * SECOND);

    const slower = Array.from(
      { length: CADENCE_OBSERVATION_LIMIT },
      (_, index) => T0 + 200 * SECOND + index * 60 * SECOND,
    );
    observations = observe("change", slower, observations);
    expect(observedCadenceMs(observations.change)).toBe(60 * SECOND);
  });

  it("explains the basis to the operator in Ukrainian", () => {
    expect(
      formatFreshnessBasis({ staleAfterMs: 105_000, basis: "observed_cadence", cadenceMs: 60_000 }),
    ).toBe("Поріг свіжості 105 с · спостережений інтервал опитування ≈60 с");
    expect(formatFreshnessBasis({ staleAfterMs: 30_000, basis: "default", cadenceMs: null })).toContain(
      "ще не визначено",
    );
  });

  it("evaluates freshness from captured_at, not from the arrival time", () => {
    const replayed = sample({ received_at: new Date(T0 + 600 * SECOND).toISOString() });
    const freshness = resolveLiveFreshness(replayed);
    expect(isLiveSampleFresh(replayed, T0 + 600 * SECOND, freshness)).toBe(false);
  });
});
