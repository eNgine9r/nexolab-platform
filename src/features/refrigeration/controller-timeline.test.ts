import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import {
  buildControlStateTimeline,
  buildDefrostTimeline,
  buildRelayTimeline,
  buildRelayTransitions,
  summarizeActiveTimeline,
} from "./controller-timeline";

const range = {
  from: new Date("2026-08-28T00:00:00.000Z"),
  to: new Date("2026-08-28T00:10:00.000Z"),
};

function sample(
  id: string,
  minute: number,
  value: number,
  quality: TelemetrySample["quality"] = "valid",
): TelemetrySample {
  return {
    event_id: id,
    node_id: "edge-01",
    captured_at: `2026-08-28T00:${String(minute).padStart(2, "0")}:00.000Z`,
    metric: "state",
    value,
    unit: "state",
    quality,
    source: "embraco-sync",
    equipment_id: "EMBRACO-2",
    channel_id: "2-state",
    alarm: null,
    raw_value: value,
    raw_status: null,
  };
}

describe("controller timelines", () => {
  it("renders state intervals by duration rather than as numeric line values", () => {
    const timeline = buildControlStateTimeline(
      [sample("a", 0, 5), sample("b", 1, 5), sample("c", 2, 1), sample("d", 3, 0)],
      range,
    );
    expect(timeline.map((item) => item.label)).toEqual(["Pulldown", "Pulldown", "Cooling"]);
    expect(timeline.every((item) => item.toMs > item.fromMs)).toBe(true);
  });

  it("counts only the observed active defrost state inside the selected time range", () => {
    const timeline = buildDefrostTimeline(
      [sample("prepare", 0, 2), sample("active", 1, 3), sample("post", 2, 4), sample("cool", 3, 1)],
      range,
    );
    expect(timeline.map((item) => item.label)).toEqual(["OFF", "ON", "OFF"]);
    expect(
      summarizeActiveTimeline(timeline, {
        from: new Date("2026-08-28T00:01:30Z"),
        to: new Date("2026-08-28T00:04:30Z"),
      }),
    ).toEqual({ activeMs: 30_000, coveredMs: 90_000 });
  });

  it("distinguishes a confirmed zero duration from unsupported or interrupted observations", () => {
    const timeline = buildDefrostTimeline(
      [
        sample("bad", 0, 3, "communication_error"),
        sample("unknown", 1, 250),
        sample("prepare", 2, 2),
        sample("cool", 3, 1),
        sample("late", 9, 3),
      ],
      range,
    );
    expect(summarizeActiveTimeline(timeline, range)).toEqual({ activeMs: 0, coveredMs: 60_000 });
    expect(summarizeActiveTimeline([], range)).toEqual({ activeMs: 0, coveredMs: 0 });
  });

  it("decodes relay bitfield into per-relay active intervals", () => {
    const timeline = buildRelayTimeline([sample("a", 0, 11), sample("b", 1, 11)], 2, range);
    expect(timeline).toHaveLength(1);
    expect(timeline[0]?.label).toBe("OFF");
    expect(timeline[0]?.active).toBe(false);
  });

  it("does not bridge large source gaps", () => {
    const timeline = buildControlStateTimeline([sample("a", 0, 5), sample("b", 9, 5)], range);
    expect(timeline).toEqual([]);
  });

  it("does not bridge an invalid sample when building a timeline", () => {
    const timeline = buildRelayTimeline(
      [sample("a", 0, 0), sample("bad", 1, 0, "communication_error"), sample("b", 2, 1)],
      0,
      range,
    );
    expect(timeline).toEqual([]);
  });

  it("records observed relay transitions with previous-sample provenance", () => {
    const transitions = buildRelayTransitions(
      [sample("a", 0, 0), sample("b", 1, 1), sample("c", 2, 1), sample("d", 3, 0)],
      0,
      range,
    );
    expect(transitions).toEqual([
      {
        relayIndex: 0,
        fromState: false,
        toState: true,
        previousObservedAtMs: Date.parse("2026-08-28T00:00:00.000Z"),
        observedAtMs: Date.parse("2026-08-28T00:01:00.000Z"),
        previousEventId: "a",
        eventId: "b",
      },
      {
        relayIndex: 0,
        fromState: true,
        toState: false,
        previousObservedAtMs: Date.parse("2026-08-28T00:02:00.000Z"),
        observedAtMs: Date.parse("2026-08-28T00:03:00.000Z"),
        previousEventId: "c",
        eventId: "d",
      },
    ]);
  });

  it("does not invent relay transitions across invalid evidence", () => {
    const transitions = buildRelayTransitions(
      [sample("a", 0, 0), sample("bad", 1, 0, "communication_error"), sample("b", 2, 1)],
      0,
      range,
    );
    expect(transitions).toEqual([]);
  });

  it("does not invent relay transitions across continuity gaps", () => {
    expect(buildRelayTransitions([sample("a", 0, 0), sample("b", 9, 1)], 0, range)).toEqual([]);
  });

  it("filters transitions by the time the new state was first observed", () => {
    const selected = {
      from: new Date("2026-08-28T00:01:30.000Z"),
      to: new Date("2026-08-28T00:03:00.000Z"),
    };
    const transitions = buildRelayTransitions(
      [sample("a", 0, 0), sample("b", 1, 1), sample("c", 2, 0)],
      0,
      selected,
    );
    expect(transitions.map((item) => item.eventId)).toEqual(["c"]);
  });
});
