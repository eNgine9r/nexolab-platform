import { describe, expect, it } from "vitest";
import { kyivInput, kyivLabel, resolveKyivInput, selectedKyivTime } from "./energy-export-time";

describe("explicit Europe/Kyiv export time", () => {
  it("rejects nonexistent spring time and invalid dates", () => {
    expect(resolveKyivInput("2026-03-29T03:30").kind).toBe("nonexistent");
    expect(resolveKyivInput("2026-02-30T10:00").kind).toBe("invalid");
    expect(selectedKyivTime("2026-03-29T03:30", "")).toBeNull();
    expect(resolveKyivInput("2026-03-29T04:30").occurrences[0].utc).toBe("2026-03-29T01:30:00.000Z");
  });
  it("requires an explicit occurrence for the repeated autumn hour", () => {
    const result = resolveKyivInput("2026-10-25T03:30");
    expect(result.kind).toBe("ambiguous");
    expect(result.occurrences).toEqual([
      { utc: "2026-10-25T00:30:00.000Z", offset: "+03:00" },
      { utc: "2026-10-25T01:30:00.000Z", offset: "+02:00" },
    ]);
    expect(selectedKyivTime("2026-10-25T03:30", "")).toBeNull();
    expect(selectedKyivTime("2026-10-25T03:30", result.occurrences[1].utc)).toBe(result.occurrences[1].utc);
  });
  it("formats Kyiv independently of browser timezone with visible offset", () => {
    expect(kyivInput("2026-10-13T07:00:00Z")).toBe("2026-10-13T10:00:00");
    expect(kyivLabel("2026-10-25T00:30:00Z")).toContain("GMT+03:00");
    expect(kyivLabel("2026-10-25T01:30:00Z")).toContain("GMT+02:00");
  });
});
