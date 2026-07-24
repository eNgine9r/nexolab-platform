import { describe, expect, it } from "vitest";

import type { LayoutPlacement } from "./layout-editor";
import {
  createLayoutDraft,
  InMemoryRefrigerationLayoutRepository,
  validatePlacements,
} from "./layout-repository";

const placements: LayoutPlacement[] = [
  { sensorId: "sensor-1", x: 0.2, y: 0.3 },
  { sensorId: "sensor-2", x: 0.7, y: 0.8 },
];

function repository() {
  let id = 0;
  let timestamp = 0;

  return new InMemoryRefrigerationLayoutRepository({
    drafts: [
      createLayoutDraft({
        id: "draft-1",
        equipmentId: "equipment-1",
        imageId: "image-1",
        placements,
        createdAt: "2026-07-24T00:00:00.000Z",
      }),
    ],
    createId: () => `revision-${++id}`,
    now: () => `2026-07-24T00:00:0${++timestamp}.000Z`,
  });
}

describe("InMemoryRefrigerationLayoutRepository", () => {
  it("increments the draft version after a successful save", async () => {
    const result = await repository().saveDraft({
      equipmentId: "equipment-1",
      expectedVersion: 1,
      imageId: "image-1",
      placements: [{ ...placements[0], x: 0.4 }, placements[1]],
    });

    expect(result).toMatchObject({
      ok: true,
      value: {
        version: 2,
        placements: [{ sensorId: "sensor-1", x: 0.4, y: 0.3 }, placements[1]],
      },
    });
  });

  it("returns a typed conflict without overwriting the current draft", async () => {
    const store = repository();

    const firstSave = await store.saveDraft({
      equipmentId: "equipment-1",
      expectedVersion: 1,
      imageId: "image-1",
      placements: [{ ...placements[0], x: 0.4 }, placements[1]],
    });
    expect(firstSave.ok).toBe(true);

    const staleSave = await store.saveDraft({
      equipmentId: "equipment-1",
      expectedVersion: 1,
      imageId: "image-1",
      placements: [{ ...placements[0], x: 0.9 }, placements[1]],
    });

    expect(staleSave).toEqual({
      ok: false,
      error: {
        code: "LAYOUT_VERSION_CONFLICT",
        equipmentId: "equipment-1",
        expectedVersion: 1,
        actualVersion: 2,
      },
    });

    const current = await store.getDraft("equipment-1");
    expect(current).toMatchObject({
      ok: true,
      value: {
        version: 2,
        placements: [{ sensorId: "sensor-1", x: 0.4, y: 0.3 }, placements[1]],
      },
    });
  });

  it("publishes immutable revisions and preserves history", async () => {
    const store = repository();

    const firstPublish = await store.publishDraft({
      equipmentId: "equipment-1",
      expectedVersion: 1,
    });
    expect(firstPublish).toMatchObject({
      ok: true,
      value: {
        draft: { version: 2 },
        published: { id: "revision-1", revision: 1, sourceDraftVersion: 1 },
      },
    });

    const saved = await store.saveDraft({
      equipmentId: "equipment-1",
      expectedVersion: 2,
      imageId: "image-2",
      placements: [{ ...placements[0], y: 0.6 }, placements[1]],
    });
    expect(saved).toMatchObject({ ok: true, value: { version: 3 } });

    const secondPublish = await store.publishDraft({
      equipmentId: "equipment-1",
      expectedVersion: 3,
    });
    expect(secondPublish).toMatchObject({
      ok: true,
      value: {
        draft: { version: 4 },
        published: { id: "revision-2", revision: 2, imageId: "image-2" },
      },
    });

    const history = await store.listHistory("equipment-1");
    expect(history).toMatchObject({
      ok: true,
      value: [
        { id: "revision-2", revision: 2 },
        { id: "revision-1", revision: 1, imageId: "image-1" },
      ],
    });

    const published = await store.getPublished("equipment-1");
    expect(published).toMatchObject({
      ok: true,
      value: { id: "revision-2", revision: 2 },
    });
  });

  it("restores a historical revision into a new draft version", async () => {
    const store = repository();

    await store.publishDraft({ equipmentId: "equipment-1", expectedVersion: 1 });
    await store.saveDraft({
      equipmentId: "equipment-1",
      expectedVersion: 2,
      imageId: "image-2",
      placements: [{ ...placements[0], x: 0.9 }, placements[1]],
    });

    const restored = await store.restoreRevision({
      equipmentId: "equipment-1",
      revisionId: "revision-1",
      expectedVersion: 3,
    });

    expect(restored).toMatchObject({
      ok: true,
      value: {
        version: 4,
        imageId: "image-1",
        placements,
      },
    });
  });

  it("rejects publish when the image, placements or coordinates are invalid", async () => {
    const store = new InMemoryRefrigerationLayoutRepository({
      drafts: [
        createLayoutDraft({
          id: "draft-invalid",
          equipmentId: "equipment-invalid",
          imageId: null,
          placements: [
            { sensorId: "sensor-1", x: 1.2, y: 0.2 },
            { sensorId: "sensor-1", x: 0.4, y: 0.5 },
          ],
          createdAt: "2026-07-24T00:00:00.000Z",
        }),
      ],
    });

    const result = await store.publishDraft({
      equipmentId: "equipment-invalid",
      expectedVersion: 1,
    });

    expect(result).toMatchObject({
      ok: false,
      error: {
        code: "LAYOUT_VALIDATION_FAILED",
        issues: expect.arrayContaining([
          expect.objectContaining({ code: "IMAGE_REQUIRED" }),
          expect.objectContaining({ code: "INVALID_COORDINATE" }),
          expect.objectContaining({ code: "DUPLICATE_SENSOR" }),
        ]),
      },
    });
  });
});

describe("validatePlacements", () => {
  it("accepts a complete normalized layout", () => {
    expect(validatePlacements(placements, true, "image-1")).toEqual([]);
  });

  it("requires at least one placement", () => {
    expect(validatePlacements([], false, null)).toEqual([
      {
        code: "PLACEMENTS_REQUIRED",
        message: "A layout must contain at least one sensor placement.",
      },
    ]);
  });
});
