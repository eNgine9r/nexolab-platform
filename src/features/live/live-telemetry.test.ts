import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import {
  defaultLiveTelemetryFilters,
  filterLiveTelemetry,
  groupLiveSamplesByUnit,
  liveChannelKey,
  liveTelemetryState,
  reconcileLiveSelection,
  selectLatestLiveSamples,
  toggleLiveSelection,
} from "./live-telemetry";

function sample(overrides: Partial<TelemetrySample> = {}): TelemetrySample {
  return {
    event_id: "event-1",
    node_id: "edge-01",
    captured_at: "2026-08-04T00:00:00.000Z",
    metric: "temperature",
    value: 4.2,
    unit: "degC",
    quality: "valid",
    source: "xjp60d",
    equipment_id: "DIXELL-106",
    channel_id: "106-03",
    alarm: null,
    raw_value: 42,
    raw_status: null,
    ...overrides,
  };
}

describe("live telemetry inventory", () => {
  it("uses unit as part of the stable channel identity", () => {
    expect(liveChannelKey(sample())).not.toBe(liveChannelKey(sample({ unit: "K" })));
  });

  it("keeps the newest captured sample for every stable identity", () => {
    const older = sample({ event_id: "older", captured_at: "2026-08-04T00:00:00.000Z" });
    const newer = sample({ event_id: "newer", captured_at: "2026-08-04T00:00:05.000Z", value: 4.8 });

    expect(selectLatestLiveSamples([newer, older])).toEqual([newer]);
  });

  it("applies search and all structured filters together", () => {
    const temperature = sample({ alarm: "high" });
    const power = sample({
      event_id: "power",
      equipment_id: "LE01MP-200",
      channel_id: "200-active-power",
      metric: "electrical.power.active",
      value: 720,
      unit: "W",
      source: "f-and-f-le-01mp",
    });
    const filters = {
      ...defaultLiveTelemetryFilters(),
      search: "106",
      nodeId: "edge-01",
      equipmentId: "DIXELL-106",
      channelId: "106-03",
      metric: "temperature",
      quality: "valid" as const,
      alarm: "active" as const,
    };

    expect(filterLiveTelemetry([power, temperature], filters)).toEqual([temperature]);
  });

  it("retains stale values but classifies them separately from live", () => {
    const value = sample({ captured_at: "2026-08-03T23:59:00.000Z" });

    expect(liveTelemetryState(value, Date.parse("2026-08-04T00:00:00.000Z"))).toBe("stale");
  });
});

describe("live telemetry selection", () => {
  it("prevents duplicates and reports the configured capacity limit", () => {
    const available = new Set(Array.from({ length: 9 }, (_, index) => `key-${index}`));
    const selected = Array.from({ length: 8 }, (_, index) => `key-${index}`);

    expect(toggleLiveSelection(selected, "key-8", available)).toEqual({
      selected,
      changed: false,
      reason: "limit",
    });
    expect(toggleLiveSelection(selected, "key-1", available).selected).not.toContain("key-1");
  });

  it("removes missing identities and limits restored URL selection", () => {
    const first = sample();
    const second = sample({
      event_id: "power",
      equipment_id: "LE01MP-200",
      channel_id: "200-active-power",
      metric: "electrical.power.active",
      unit: "W",
    });

    expect(
      reconcileLiveSelection(
        [liveChannelKey(first), "missing", liveChannelKey(second), liveChannelKey(first)],
        [first, second],
      ),
    ).toEqual([liveChannelKey(first), liveChannelKey(second)]);
  });

  it("groups incompatible units into separate comparison groups", () => {
    const temperature = sample();
    const power = sample({
      event_id: "power",
      equipment_id: "LE01MP-200",
      channel_id: "200-active-power",
      metric: "electrical.power.active",
      unit: "W",
    });

    expect([...groupLiveSamplesByUnit([power, temperature]).keys()]).toEqual(["degC", "W"]);
  });
});
