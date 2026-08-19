import { describe, expect, it } from "vitest";

import {
  defaultLiveDashboardHistoryPreset,
  liveDashboardCustomRange,
  liveDashboardPresetRange,
} from "./history-range";

describe("Saved Dashboard view history ranges", () => {
  it("uses a saved compatible window as the initial view without mutating the definition", () => {
    expect(defaultLiveDashboardHistoryPreset("5m")).toBe("1h");
    expect(defaultLiveDashboardHistoryPreset("15m")).toBe("1h");
    expect(defaultLiveDashboardHistoryPreset("30m")).toBe("1h");
    expect(defaultLiveDashboardHistoryPreset("1h")).toBe("1h");
    expect(defaultLiveDashboardHistoryPreset("6h")).toBe("6h");
    expect(defaultLiveDashboardHistoryPreset("12h")).toBe("24h");
    expect(defaultLiveDashboardHistoryPreset("24h")).toBe("24h");
    expect(defaultLiveDashboardHistoryPreset("7d")).toBe("7d");
  });

  it("builds deterministic preset windows", () => {
    const range = liveDashboardPresetRange("30d", new Date("2026-08-18T20:00:00.000Z"));
    expect(range).toEqual({
      kind: "30d",
      from: "2026-07-19T20:00:00.000Z",
      to: "2026-08-18T20:00:00.000Z",
      label: "30d",
    });
  });

  it("accepts a timezone-aware custom range and canonicalizes UTC", () => {
    const range = liveDashboardCustomRange("2026-08-18T10:00:00+03:00", "2026-08-18T12:30:00+03:00");
    expect(range.from).toBe("2026-08-18T07:00:00.000Z");
    expect(range.to).toBe("2026-08-18T09:30:00.000Z");
  });

  it("rejects reversed and over-31-day custom ranges", () => {
    expect(() => liveDashboardCustomRange("2026-08-18T12:00:00Z", "2026-08-18T11:00:00Z")).toThrow("раніше");
    expect(() => liveDashboardCustomRange("2026-07-01T00:00:00Z", "2026-08-18T00:00:00Z")).toThrow("31");
  });
});
