import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import {
  operatorHistoryPreview,
  reduceSavedDashboardHistory,
  restoreOperatorEvidence,
} from "./operator-history";
import type { LiveDashboardItem } from "./types";

const item: LiveDashboardItem = {
  id: "cabinet",
  position: 1,
  channel_ref_id: null,
  node_id: "edge-01",
  equipment_id: "EMBRACO-2",
  channel_id: "2-cabinet-temperature",
  metric: "temperature.cabinet",
  native_unit: "degC",
  visualization: "line",
  color: "#00C6E0",
  display_unit: "degC",
};

function raw(
  eventId: string,
  offset: number,
  rawValue: number | null,
  quality: TelemetrySample["quality"] = "unknown",
): TelemetrySample {
  return {
    event_id: eventId,
    node_id: "edge-01",
    equipment_id: "EMBRACO-2",
    channel_id: "2-cabinet-temperature",
    metric: "temperature.cabinet",
    captured_at: new Date(Date.parse("2026-11-19T18:00:00Z") + offset).toISOString(),
    value: null,
    raw_value: rawValue,
    quality,
    unit: "degC",
    source: "embraco-sync",
    alarm: null,
    raw_status: null,
  };
}

const window = { from: new Date("2026-11-19T17:59:00Z"), to: new Date("2026-11-19T18:10:00Z") };

describe("selected dashboard operator history reduction", () => {
  it("keeps selected unknown/null Embraco samples for chart without altering source evidence", () => {
    const originals = [raw("a", 0, 65507), raw("b", 10_000, 65468), raw("c", 20_000, 65516)];
    const preview = operatorHistoryPreview(item, originals[0]);
    expect(preview).toMatchObject({ quality: "valid", value: -0.29, unit: "°C" });
    expect(originals[0]).toMatchObject({ quality: "unknown", value: null, raw_value: 65507 });
    const reduced = reduceSavedDashboardHistory(item, originals, window);
    expect(reduced.map((s) => s.raw_value)).toEqual([65507, 65468, 65516]);
    expect(reduced.every((s) => s.value === null && s.quality === "unknown")).toBe(true);
  });

  it("does not bridge communication failures and safely restores segment markers", () => {
    const originals = [
      raw("first", 0, 65507),
      raw("bad", 10_000, 65508, "communication_error"),
      raw("after", 20_000, 65510),
    ];
    const reduced = reduceSavedDashboardHistory(item, originals, window);
    expect(reduced).toHaveLength(2);
    expect(reduced[1]?.event_id).toMatch(/^nexolab-live-segment:/);
    expect(reduced[1]?.quality).toBe("unknown");
    const roundtrip = restoreOperatorEvidence([operatorHistoryPreview(item, originals[0])], originals);
    expect(roundtrip[0]).toEqual(originals[0]);
  });

  it("never promotes other controller or metric unknown samples", () => {
    expect(
      reduceSavedDashboardHistory({ ...item, equipment_id: "EMBRACO-3" }, [raw("wrong", 0, 65507)], window),
    ).toEqual([]);
    expect(reduceSavedDashboardHistory(item, [raw("missing", 0, null)], window)).toEqual([]);
  });
});
