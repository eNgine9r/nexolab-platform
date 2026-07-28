import { describe, expect, it, vi } from "vitest";

import {
  createBrowserLayoutDraftStorage,
  createLayoutDraftPayload,
  layoutDraftStorageKey,
  LAYOUT_DRAFT_MAX_AGE_MS,
  parseLayoutDraft,
  serializeLayoutDraft,
} from "./layout-draft-storage";

const allowedSensorIds = new Set(["sensor-1", "sensor-2"]);
const placements = [
  { sensorId: "sensor-1", x: 0.25, y: 0.4 },
  { sensorId: "sensor-2", x: 0.75, y: 0.6 },
];
const nowMs = Date.parse("2026-07-28T20:00:00.000Z");

function validPayload(savedAt = "2026-07-28T19:59:00.000Z") {
  return createLayoutDraftPayload("equipment-1", placements, savedAt);
}

describe("layout draft storage", () => {
  it("round-trips a valid equipment-scoped placement draft", () => {
    const serialized = serializeLayoutDraft(validPayload());

    expect(parseLayoutDraft(serialized, "equipment-1", allowedSensorIds, nowMs)).toEqual(
      validPayload(),
    );
  });

  it("stores only normalized placement geometry", () => {
    const serialized = serializeLayoutDraft(validPayload());

    expect(serialized).not.toContain("sourceUrl");
    expect(serialized).not.toContain("blob:");
    expect(serialized).not.toContain("image");
    expect(Object.keys(JSON.parse(serialized)).sort()).toEqual([
      "equipmentId",
      "placements",
      "savedAt",
      "schemaVersion",
    ]);
  });

  it("rejects malformed JSON and unsupported schemas", () => {
    expect(parseLayoutDraft("{broken", "equipment-1", allowedSensorIds, nowMs)).toBeNull();

    const unsupported = { ...validPayload(), schemaVersion: 99 };
    expect(
      parseLayoutDraft(JSON.stringify(unsupported), "equipment-1", allowedSensorIds, nowMs),
    ).toBeNull();
  });

  it("rejects stale and implausibly future drafts", () => {
    const stale = validPayload(new Date(nowMs - LAYOUT_DRAFT_MAX_AGE_MS - 1).toISOString());
    expect(
      parseLayoutDraft(JSON.stringify(stale), "equipment-1", allowedSensorIds, nowMs),
    ).toBeNull();

    const future = validPayload(new Date(nowMs + 10 * 60 * 1000).toISOString());
    expect(
      parseLayoutDraft(JSON.stringify(future), "equipment-1", allowedSensorIds, nowMs),
    ).toBeNull();
  });

  it("rejects equipment mismatches, missing sensors and duplicate sensors", () => {
    const serialized = serializeLayoutDraft(validPayload());
    expect(parseLayoutDraft(serialized, "equipment-2", allowedSensorIds, nowMs)).toBeNull();

    const missing = { ...validPayload(), placements: placements.slice(0, 1) };
    expect(
      parseLayoutDraft(JSON.stringify(missing), "equipment-1", allowedSensorIds, nowMs),
    ).toBeNull();

    const duplicate = {
      ...validPayload(),
      placements: [placements[0], { ...placements[0] }],
    };
    expect(
      parseLayoutDraft(JSON.stringify(duplicate), "equipment-1", allowedSensorIds, nowMs),
    ).toBeNull();
  });

  it("rejects non-finite and out-of-range normalized coordinates", () => {
    const invalid = {
      ...validPayload(),
      placements: [placements[0], { sensorId: "sensor-2", x: 1.01, y: 0.5 }],
    };

    expect(
      parseLayoutDraft(JSON.stringify(invalid), "equipment-1", allowedSensorIds, nowMs),
    ).toBeNull();
  });

  it("fails open when browser storage operations throw", () => {
    const storage = {
      getItem: vi.fn(() => {
        throw new DOMException("blocked", "SecurityError");
      }),
      setItem: vi.fn(() => {
        throw new DOMException("quota", "QuotaExceededError");
      }),
      removeItem: vi.fn(() => {
        throw new DOMException("blocked", "SecurityError");
      }),
    } as unknown as Storage;
    const adapter = createBrowserLayoutDraftStorage(storage);

    expect(adapter.load("equipment-1")).toBeNull();
    expect(adapter.save("equipment-1", "{}")).toBe(false);
    expect(adapter.remove("equipment-1")).toBe(false);
  });

  it("uses an encoded equipment-scoped key", () => {
    expect(layoutDraftStorageKey("equipment/1 test")).toBe(
      "nexolab:refrigeration:layout-draft:equipment%2F1%20test",
    );
  });
});
