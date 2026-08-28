import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import { buildControlStateTimeline, buildRelayTimeline } from "./controller-timeline";

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
});
