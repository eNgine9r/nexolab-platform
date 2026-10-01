import { describe, expect, it } from "vitest";
import { formatOperationalTimestamp } from "./format";

describe("operational timestamp presentation", () => {
  it("shows the same instant in UTC and Kyiv with explicit timezone", () => {
    const instant = "2026-07-01T10:20:30Z";
    expect(formatOperationalTimestamp(instant, "UTC")).toContain("10:20:30 (UTC)");
    expect(formatOperationalTimestamp(instant, "Europe/Kyiv")).toContain("13:20:30 (Europe/Kyiv)");
    expect(instant).toBe("2026-07-01T10:20:30Z");
  });
  it("uses the correct local DST offset without moving the underlying instant", () => {
    expect(formatOperationalTimestamp("2026-01-01T10:20:30Z", "Europe/Kyiv")).toContain("12:20:30");
    expect(formatOperationalTimestamp("2026-07-01T10:20:30Z", "Europe/Kyiv")).toContain("13:20:30");
  });
  it("fails truthfully for missing, invalid or unsupported timestamps/timezones", () => {
    for (const value of [null, undefined, "", "bad", Number.NaN]) {
      expect(formatOperationalTimestamp(value, "UTC")).toBe("—");
    }
    expect(formatOperationalTimestamp("2026-07-01T10:20:30Z", "unknown/zone")).toBe("—");
  });
});
