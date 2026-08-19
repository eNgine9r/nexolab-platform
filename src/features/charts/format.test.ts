import { describe, expect, it } from "vitest";

import {
  chartDisplayPrecision,
  formatChartAxisTimestamp,
  formatChartExactTimestamp,
  formatChartValue,
} from "./format";

describe("chart formatting", () => {
  it("uses two decimals by default without changing the input value", () => {
    const raw = 25.700000000000003;
    expect(formatChartValue(raw)).toBe("25.70");
    expect(raw).toBe(25.700000000000003);
  });
  it("supports future metric-definition precision overrides", () => {
    expect(formatChartValue(50.12345, 3)).toBe("50.123");
    expect(chartDisplayPrecision(0)).toBe(0);
  });
  it("never exposes non-finite values as operator measurements", () => {
    expect(formatChartValue(Number.NaN)).toBe("—");
    expect(formatChartValue(Number.POSITIVE_INFINITY)).toBe("—");
  });
  it("keeps short ranges time-oriented but adds date context across day boundaries", () => {
    const timestamp = Date.parse("2026-08-19T05:06:00.000Z");
    const short = formatChartAxisTimestamp(
      timestamp,
      { fromMs: timestamp - 60 * 60_000, toMs: timestamp },
      { locale: "en-GB", timeZone: "UTC" },
    );
    const day = formatChartAxisTimestamp(
      timestamp,
      { fromMs: timestamp - 24 * 60 * 60_000, toMs: timestamp },
      { locale: "en-GB", timeZone: "UTC" },
    );
    expect(short).toContain("05:06");
    expect(short).not.toContain("19/08");
    expect(day).toContain("19/08");
    expect(day).toContain("05:06");
  });
  it("formats exact inspection timestamps with date, seconds and timezone context", () => {
    const text = formatChartExactTimestamp(Date.parse("2026-08-19T05:06:07.000Z"), {
      locale: "en-GB",
      timeZone: "UTC",
    });
    expect(text).toContain("19/08/2026");
    expect(text).toContain("05:06:07");
    expect(text).toMatch(/UTC|GMT/);
  });
});
