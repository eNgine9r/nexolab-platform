import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import {
  buildCompressorTimeline,
  buildControlStateTimeline,
  buildDefrostTimeline,
  buildRelayTimeline,
  buildUnknownTimeline,
  clipTimeline,
} from "./controller-timeline";

const T0 = Date.parse("2026-11-25T00:00:00Z");
const STEP = 10_000;

/** 24 h of a 10 s controller value with state changes, communication errors and a silent gap. */
function history(metric: string, valueAt: (index: number) => number): TelemetrySample[] {
  const samples: TelemetrySample[] = [];
  for (let index = 0; index < 8_640; index += 1) {
    if (index >= 3_000 && index < 3_040) continue; // 400 s silent gap → NO DATA
    const failed = index % 613 === 7;
    samples.push({
      event_id: `${metric}-${index}`,
      node_id: "edge-01",
      captured_at: new Date(T0 + index * STEP).toISOString(),
      metric,
      value: failed ? null : valueAt(index),
      unit: "",
      quality: failed ? "communication_error" : "valid",
      source: "embraco-sync",
      equipment_id: "EMBRACO-2",
      channel_id: metric,
      alarm: null,
      raw_value: null,
      raw_status: null,
    });
  }
  return samples;
}

const loaded = { from: new Date(T0), to: new Date(T0 + 8_640 * STEP) };
const viewports = [
  { from: new Date(T0 + 2_990 * STEP + 3_000), to: new Date(T0 + 3_100 * STEP + 7_000) },
  { from: new Date(T0 + 612 * STEP), to: new Date(T0 + 1_300 * STEP) },
  { from: new Date(T0 + 5 * STEP + 1), to: new Date(T0 + 5 * STEP + 2) },
  loaded,
];

describe("clipTimeline (#1829)", () => {
  const state = history("state", (index) => Math.floor(index / 97) % 6);
  const relays = history("relays", (index) => (index * 7) % 16);
  const speed = history("speed", (index) => (index % 300 < 180 ? 2_400 : 0));
  const builders: Array<[string, (range: { from: Date; to: Date }) => ReturnType<typeof clipTimeline>]> = [
    ["control state", (range) => buildControlStateTimeline(state, range)],
    ["defrost", (range) => buildDefrostTimeline(state, range)],
    ["compressor", (range) => buildCompressorTimeline(speed, range)],
    ["relay 2", (range) => buildRelayTimeline(relays, 2, range)],
    ["unknown", (range) => buildUnknownTimeline(relays, range)],
  ];

  for (const [name, build] of builders) {
    it(`clipping the loaded-range ${name} timeline equals building it for the viewport`, () => {
      const full = build(loaded);
      for (const viewport of viewports) expect(clipTimeline(full, viewport)).toEqual(build(viewport));
    });
  }

  it("keeps sorted merged lanes sorted and identical after clipping", () => {
    const merged = (range: { from: Date; to: Date }) =>
      [...buildControlStateTimeline(state, range), ...buildUnknownTimeline(state, range)].sort(
        (left, right) => left.fromMs - right.fromMs,
      );
    const full = merged(loaded);
    for (const viewport of viewports) expect(clipTimeline(full, viewport)).toEqual(merged(viewport));
  });
});
