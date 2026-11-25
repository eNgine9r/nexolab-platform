import { describe, expect, it } from "vitest";

import { fromZonedInputValue, toZonedInputValue } from "./zoned-input";

describe("zoned datetime-local conversion", () => {
  it("interprets custom range input in the display time zone, not the browser zone", () => {
    expect(fromZonedInputValue("2026-11-21T10:00", "Europe/Kyiv")).toBe(Date.parse("2026-11-21T08:00:00Z"));
    expect(fromZonedInputValue("2026-07-01T10:00", "Europe/Kyiv")).toBe(Date.parse("2026-07-01T07:00:00Z"));
    expect(fromZonedInputValue("2026-11-21T10:00", "UTC")).toBe(Date.parse("2026-11-21T10:00:00Z"));
  });

  it("formats an instant as the display-zone wall clock", () => {
    expect(toZonedInputValue(Date.parse("2026-11-21T08:00:00Z"), "Europe/Kyiv")).toBe("2026-11-21T10:00");
    expect(toZonedInputValue(Date.parse("2026-11-21T08:00:00Z"), "UTC")).toBe("2026-11-21T08:00");
  });

  it("round-trips across a DST change and rejects skipped or malformed values", () => {
    const instant = Date.parse("2026-10-25T00:30:00Z");
    expect(fromZonedInputValue(toZonedInputValue(instant, "Europe/Kyiv"), "Europe/Kyiv")).toBe(instant);
    // 2026-03-29 03:30 does not exist in Kyiv (clocks jump 03:00 → 04:00).
    expect(fromZonedInputValue("2026-03-29T03:30", "Europe/Kyiv")).toBeNull();
    expect(fromZonedInputValue("not a date", "Europe/Kyiv")).toBeNull();
  });
});
