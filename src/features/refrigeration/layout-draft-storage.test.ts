import { describe, expect, it, vi } from "vitest";

import type { LayoutPlacement } from "./layout-editor";
import {
  createBrowserLayoutDraftStorage,
  createLayoutDraftPayload,
  layoutDraftStorageKey,
  parseLayoutDraft,
  serializeLayoutDraft,
} from "./layout-draft-storage";

const placements: LayoutPlacement[] = [
  { sensorId: "sensor-1", x: 0.2, y: 0.3 },
  { sensorId: "sensor-2", x: 0.6, y: 0.7 },
];
const allowedSensorIds = new Set(placements.map((placement) => placement.sensorId));

describe("layout draft storage", () => {
  it("round-trips a versioned equipment-scoped payload", () => {
    const payload = createLayoutDraftPayload("showcase-106-01", placements, "2026-07-24T19:00:00.000Z");

    expect(parseLayoutDraft(serializeLayoutDraft(payload), "showcase-106-01", allowedSensorIds)).toEqual(
      payload,
    );
    expect(layoutDraftStorageKey("showcase-106-01")).toBe(
      "nexolab:refrigeration-layout-draft:v1:showcase-106-01",
    );
  });

  it("rejects malformed, mismatched and out-of-range payloads", () => {
    expect(parseLayoutDraft("not-json", "showcase-106-01", allowedSensorIds)).toBeNull();
    expect(
      parseLayoutDraft(
        JSON.stringify({
          version: 1,
          equipmentId: "other-equipment",
          savedAt: "2026-07-24T19:00:00.000Z",
          placements,
        }),
        "showcase-106-01",
        allowedSensorIds,
      ),
    ).toBeNull();
    expect(
      parseLayoutDraft(
        JSON.stringify({
          version: 1,
          equipmentId: "showcase-106-01",
          savedAt: "2026-07-24T19:00:00.000Z",
          placements: [{ sensorId: "sensor-1", x: 1.2, y: 0.3 }, placements[1]],
        }),
        "showcase-106-01",
        allowedSensorIds,
      ),
    ).toBeNull();
  });

  it("rejects duplicate, missing and unknown sensor identifiers", () => {
    expect(
      parseLayoutDraft(
        JSON.stringify({
          version: 1,
          equipmentId: "showcase-106-01",
          savedAt: "2026-07-24T19:00:00.000Z",
          placements: [placements[0], placements[0]],
        }),
        "showcase-106-01",
        allowedSensorIds,
      ),
    ).toBeNull();
    expect(
      parseLayoutDraft(
        JSON.stringify({
          version: 1,
          equipmentId: "showcase-106-01",
          savedAt: "2026-07-24T19:00:00.000Z",
          placements: [placements[0]],
        }),
        "showcase-106-01",
        allowedSensorIds,
      ),
    ).toBeNull();
    expect(
      parseLayoutDraft(
        JSON.stringify({
          version: 1,
          equipmentId: "showcase-106-01",
          savedAt: "2026-07-24T19:00:00.000Z",
          placements: [placements[0], { sensorId: "unknown", x: 0.4, y: 0.5 }],
        }),
        "showcase-106-01",
        allowedSensorIds,
      ),
    ).toBeNull();
  });

  it("isolates browser storage failures from editing", () => {
    const storage = {
      getItem: vi.fn(() => {
        throw new Error("blocked");
      }),
      setItem: vi.fn(() => {
        throw new Error("full");
      }),
      removeItem: vi.fn(() => {
        throw new Error("blocked");
      }),
    };
    const adapter = createBrowserLayoutDraftStorage(storage);

    expect(adapter.load("showcase-106-01")).toBeNull();
    expect(() => adapter.save("showcase-106-01", "payload")).not.toThrow();
    expect(() => adapter.remove("showcase-106-01")).not.toThrow();
  });
});
