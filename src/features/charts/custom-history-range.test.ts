import { describe, expect, it } from "vitest";

import {
  CUSTOM_HISTORY_MAX_RANGE_DAYS,
  customHistoryRangeKey,
  resolveCustomHistoryWindow,
} from "./custom-history-range";

const NOW = Date.parse("2026-11-22T12:00:00.000Z");
const HOUR = 60 * 60 * 1000;

describe("custom history period (#1683)", () => {
  it("returns the requested past window unchanged", () => {
    expect(resolveCustomHistoryWindow(NOW - 5 * HOUR, NOW - 2 * HOUR, NOW)).toEqual({
      from: "2026-11-22T07:00:00.000Z",
      to: "2026-11-22T10:00:00.000Z",
    });
  });

  it("clamps a future end to the moment the period is applied", () => {
    expect(resolveCustomHistoryWindow(NOW - HOUR, NOW + 3 * HOUR, NOW).to).toBe("2026-11-22T12:00:00.000Z");
  });

  it("rejects a start that is not before the end", () => {
    expect(() => resolveCustomHistoryWindow(NOW - HOUR, NOW - HOUR, NOW)).toThrow(
      "Початок діапазону має бути раніше завершення.",
    );
    expect(() => resolveCustomHistoryWindow(NOW - HOUR, NOW - 2 * HOUR, NOW)).toThrow(
      "Початок діапазону має бути раніше завершення.",
    );
  });

  it("rejects a start in the future and empty inputs", () => {
    expect(() => resolveCustomHistoryWindow(NOW + HOUR, NOW + 2 * HOUR, NOW)).toThrow(
      "Початок періоду має бути в минулому.",
    );
    expect(() => resolveCustomHistoryWindow(null, NOW, NOW)).toThrow(
      "Вкажіть коректні дату й час початку та завершення.",
    );
  });

  it("allows exactly 31 days and rejects anything longer, like Saved Dashboards", () => {
    expect(CUSTOM_HISTORY_MAX_RANGE_DAYS).toBe(31);
    const limit = 31 * 24 * HOUR;
    expect(() => resolveCustomHistoryWindow(NOW - limit, NOW, NOW)).not.toThrow();
    expect(() => resolveCustomHistoryWindow(NOW - limit - 1, NOW, NOW)).toThrow(
      "Діапазон не може перевищувати 31 день.",
    );
  });

  it("keys a custom window by its bounds so it never shares a preset cache entry", () => {
    expect(customHistoryRangeKey({ from: "2026-11-01T00:00:00.000Z", to: "2026-11-02T00:00:00.000Z" })).toBe(
      "custom:2026-11-01T00:00:00.000Z:2026-11-02T00:00:00.000Z",
    );
  });
});
