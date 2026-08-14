import { describe, expect, it } from "vitest";

import { chartDisplayPrecision, formatChartValue } from "./format";

describe("chart value formatting", () => {
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
});
