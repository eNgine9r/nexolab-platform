import { describe, expect, it } from "vitest";

import { sessionChartDomain } from "./session-chart-domain";

describe("session history chart domain (#1662)", () => {
  it("uses the requested window so silent edges remain visible as gaps", () => {
    expect(sessionChartDomain([5_000, 9_000], { fromMs: 0, toMs: 60_000 })).toEqual({
      fromMs: 0,
      toMs: 60_000,
    });
  });

  it("falls back to the sample span without a usable window", () => {
    expect(sessionChartDomain([5_000, 9_000], null)).toEqual({ fromMs: 5_000, toMs: 9_000 });
    expect(sessionChartDomain([5_000, 9_000], { fromMs: 10, toMs: 10 })).toEqual({
      fromMs: 5_000,
      toMs: 9_000,
    });
    expect(sessionChartDomain([5_000], undefined)).toEqual({ fromMs: 5_000, toMs: 65_000 });
    expect(sessionChartDomain([], undefined)).toBeNull();
    expect(sessionChartDomain([Number.NaN], undefined)).toBeNull();
  });
});
