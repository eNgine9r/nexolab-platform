import { describe, expect, it } from "vitest";

import {
  buildCompressorStartEvents,
  calculateCompressorRuntimeDuty,
} from "@/features/refrigeration/compressor-runtime";

const range = { from: "2026-08-28T00:00:00Z", to: "2026-08-28T00:10:00Z" };
const sample = (second: number, value: number | null, quality = "valid") => ({
  capturedAt: new Date(Date.parse(range.from) + second * 1000).toISOString(),
  value,
  quality,
});

describe("calculateCompressorRuntimeDuty", () => {
  it("returns 100% for continuously running observed intervals", () => {
    const result = calculateCompressorRuntimeDuty(
      [sample(0, 4500), sample(30, 4500), sample(60, 4500)],
      range,
    );
    expect(result.dutyPercent).toBe(100);
    expect(result.runningMs).toBe(60_000);
    expect(result.observedMs).toBe(60_000);
  });

  it("returns 0% for continuously stopped observed intervals", () => {
    const result = calculateCompressorRuntimeDuty([sample(0, 0), sample(30, 0), sample(60, 0)], range);
    expect(result.dutyPercent).toBe(0);
  });

  it("weights intervals by duration instead of sample count", () => {
    const result = calculateCompressorRuntimeDuty([sample(0, 4500), sample(10, 0), sample(70, 0)], range);
    expect(result.dutyPercent).toBeCloseTo((10 / 70) * 100, 6);
  });

  it("excludes continuity gaps from numerator and denominator", () => {
    const result = calculateCompressorRuntimeDuty(
      [sample(0, 4500), sample(30, 4500), sample(300, 0), sample(330, 0)],
      range,
    );
    expect(result.continuityBreaks).toBe(1);
    expect(result.observedMs).toBe(60_000);
    expect(result.runningMs).toBe(30_000);
    expect(result.dutyPercent).toBe(50);
  });

  it("does not treat invalid or unavailable samples as stopped time", () => {
    const result = calculateCompressorRuntimeDuty(
      [
        sample(0, 4500),
        sample(30, null, "communication_error"),
        sample(60, 0),
        sample(90, 0),
        sample(120, 0),
      ],
      range,
    );
    expect(result.dutyPercent).toBe(0);
    expect(result.observedMs).toBe(60_000);
    expect(result.runningMs).toBe(0);
  });

  it("reports partial observation coverage against requested range", () => {
    const result = calculateCompressorRuntimeDuty([sample(0, 4500), sample(30, 4500)], range);
    expect(result.coveragePercent).toBe(5);
  });

  it("clips an analysis range that starts and ends between evidence-backed samples", () => {
    const result = calculateCompressorRuntimeDuty([sample(0, 4500), sample(60, 4500)], {
      from: sample(20, 0).capturedAt,
      to: sample(50, 0).capturedAt,
    });

    expect(result.status).toBe("available");
    expect(result.observedMs).toBe(30_000);
    expect(result.runningMs).toBe(30_000);
    expect(result.coveragePercent).toBe(100);
    expect(result.dutyPercent).toBe(100);
  });

  it("weights clipped running and stopped portions across an analysis boundary", () => {
    const result = calculateCompressorRuntimeDuty([sample(0, 4500), sample(60, 0), sample(120, 0)], {
      from: sample(30, 0).capturedAt,
      to: sample(90, 0).capturedAt,
    });

    expect(result.observedMs).toBe(60_000);
    expect(result.runningMs).toBe(30_000);
    expect(result.dutyPercent).toBe(50);
  });

  it("does not infer a clipped selection across a continuity gap", () => {
    const result = calculateCompressorRuntimeDuty([sample(0, 4500), sample(300, 4500)], {
      from: sample(60, 0).capturedAt,
      to: sample(120, 0).capturedAt,
    });

    expect(result.status).toBe("unavailable");
    expect(result.observedMs).toBe(0);
    expect(result.runningMs).toBe(0);
    expect(result.continuityBreaks).toBe(1);
  });

  it("is unavailable when fewer than two usable timestamps create observed duration", () => {
    const result = calculateCompressorRuntimeDuty([sample(0, 4500)], range);
    expect(result.status).toBe("unavailable");
    expect(result.dutyPercent).toBeNull();
    expect(result.coveragePercent).toBe(0);
  });

  it("counts only confirmed stopped-to-running transitions", () => {
    const samples = [sample(0, 0), sample(60, 4500), sample(120, 4500), sample(180, 0), sample(240, 3200)];
    const starts = buildCompressorStartEvents(samples, range);
    expect(starts.map((item) => item.observedAtMs)).toEqual([
      Date.parse(sample(60, 0).capturedAt),
      Date.parse(sample(240, 0).capturedAt),
    ]);
    expect(calculateCompressorRuntimeDuty(samples, range).startCount).toBe(2);
  });

  it("does not count a first already-running sample as a compressor start", () => {
    expect(buildCompressorStartEvents([sample(0, 4500), sample(60, 4500)], range)).toEqual([]);
  });

  it("does not invent compressor starts across invalid evidence or continuity gaps", () => {
    expect(
      buildCompressorStartEvents(
        [sample(0, 0), sample(30, null, "communication_error"), sample(60, 4500)],
        range,
      ),
    ).toEqual([]);
    expect(buildCompressorStartEvents([sample(0, 0), sample(300, 4500)], range)).toEqual([]);
  });

  it("counts a transition when the first observed running sample is inside the selected range", () => {
    const starts = buildCompressorStartEvents([sample(0, 0), sample(60, 4500)], {
      from: sample(30, 0).capturedAt,
      to: sample(90, 0).capturedAt,
    });
    expect(starts).toHaveLength(1);
    expect(starts[0]?.previousObservedAtMs).toBe(Date.parse(sample(0, 0).capturedAt));
    expect(starts[0]?.observedAtMs).toBe(Date.parse(sample(60, 0).capturedAt));
  });

  it("rejects malformed ranges", () => {
    expect(() => calculateCompressorRuntimeDuty([], { from: range.to, to: range.from })).toThrow(
      "positive interval",
    );
  });
});
