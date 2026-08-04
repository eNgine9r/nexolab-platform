import { describe, expect, it } from "vitest";

import type { RefrigerationEquipment } from "@/data/refrigeration";
import type {
  PublishedLayoutRevision,
  RefrigerationLayoutDraft,
  RefrigerationLayoutRepository,
  RepositoryResult,
} from "@/features/refrigeration/layout-repository";
import type { RefrigerationEquipmentRepository } from "@/features/refrigeration/equipment-repository";

import {
  defaultLayoutCatalogFilters,
  deriveLayoutCatalogState,
  filterLayoutCatalog,
  isLayoutCatalogAbort,
  loadLayoutCatalog,
  type LayoutCatalogItem,
} from "./layout-catalog";

function equipment(id: string, overrides: Partial<RefrigerationEquipment> = {}): RefrigerationEquipment {
  return {
    id,
    code: id.toUpperCase(),
    name: `Обладнання ${id}`,
    location: "Лабораторія 1 · Зона A",
    laboratory: "Лабораторія 1",
    zone: "Зона A",
    climateChamberId: "kk1",
    nodeId: "kk1",
    transportNodeId: "edge-01",
    type: "Холодильна вітрина",
    manufacturer: "NEXOLAB",
    model: "M1",
    serialNumber: `SN-${id}`,
    temperatureClass: "3M1",
    installedAt: "2026-01-01",
    servicedAt: "2026-07-01",
    lifecycleStatus: "active",
    status: "normal",
    averageTemperatureC: 3,
    minTemperatureC: 2,
    maxTemperatureC: 4,
    onlineSensors: 1,
    totalSensors: 1,
    activeAlarms: 0,
    lastSeenAt: "2026-08-04T00:00:00Z",
    version: 1,
    image: null,
    sensors: [],
    ...overrides,
  };
}

function draft(
  equipmentId: string,
  overrides: Partial<RefrigerationLayoutDraft> = {},
): RefrigerationLayoutDraft {
  return {
    id: `draft-${equipmentId}`,
    equipmentId,
    version: 2,
    etag: 'W/"layout-2"',
    imageId: "image-1",
    image: null,
    placements: [{ sensorId: "sensor-1", x: 0.25, y: 0.5 }],
    createdAt: "2026-08-04T00:00:00Z",
    updatedAt: "2026-08-04T00:00:00Z",
    ...overrides,
  };
}

function published(
  equipmentId: string,
  overrides: Partial<PublishedLayoutRevision> = {},
): PublishedLayoutRevision {
  return {
    id: `published-${equipmentId}`,
    equipmentId,
    revision: 1,
    sourceDraftVersion: 1,
    imageId: "image-1",
    image: {
      id: "image-1",
      fileName: "layout.png",
      mimeType: "image/png",
      widthPx: 1200,
      heightPx: 800,
      sizeBytes: 100,
      sourceUrl: "http://127.0.0.1/layout.png",
      alt: "Схема",
      updatedAt: "2026-08-04T00:00:00Z",
    },
    placements: [{ sensorId: "sensor-1", x: 0.25, y: 0.5 }],
    publishedBy: "operator@nexolab.local",
    publishedAt: "2026-08-04T00:00:00Z",
    ...overrides,
  };
}

describe("equipment layout catalog state", () => {
  it("derives explicit current, changed, draft-only, no-image and empty states", () => {
    const currentDraft = draft("eq-1");
    const currentPublished = published("eq-1");

    expect(deriveLayoutCatalogState(currentDraft, currentPublished)).toBe("published-current");
    expect(
      deriveLayoutCatalogState(
        draft("eq-1", { placements: [{ sensorId: "sensor-1", x: 0.4, y: 0.5 }] }),
        currentPublished,
      ),
    ).toBe("published-with-draft");
    expect(deriveLayoutCatalogState(currentDraft, null)).toBe("draft-only");
    expect(deriveLayoutCatalogState(draft("eq-1", { imageId: null }), null)).toBe("no-image");
    expect(
      deriveLayoutCatalogState(draft("eq-1", { imageId: null, placements: [] }), null),
    ).toBe("empty");
  });

  it("applies search and all structured filters together", () => {
    const item: LayoutCatalogItem = {
      kind: "ready",
      equipment: equipment("eq-1"),
      draft: draft("eq-1"),
      published: published("eq-1"),
      layoutState: "published-current",
    };
    const other: LayoutCatalogItem = {
      kind: "ready",
      equipment: equipment("eq-2", {
        laboratory: "Лабораторія 2",
        zone: "Зона B",
        climateChamberId: "kk2",
        lifecycleStatus: "maintenance",
      }),
      draft: draft("eq-2", { imageId: null, placements: [] }),
      published: null,
      layoutState: "empty",
    };

    expect(
      filterLayoutCatalog([other, item], {
        ...defaultLayoutCatalogFilters(),
        search: "EQ-1",
        laboratory: "Лабораторія 1",
        zone: "Зона A",
        chamber: "kk1",
        lifecycle: "active",
        layout: "published-current",
      }),
    ).toEqual([item]);
  });
});

describe("equipment layout catalog loader", () => {
  it("bounds concurrency and preserves successful items when one summary fails", async () => {
    const equipmentItems = Array.from({ length: 5 }, (_, index) => equipment(`eq-${index + 1}`));
    let active = 0;
    let maximumActive = 0;
    const equipmentRepository = equipmentRepositoryWith(equipmentItems);
    const layoutRepository = layoutRepositoryWith(async (equipmentId) => {
      active += 1;
      maximumActive = Math.max(maximumActive, active);
      await Promise.resolve();
      active -= 1;
      if (equipmentId === "eq-3") {
        return {
          ok: false,
          error: {
            code: "LAYOUT_NOT_FOUND",
            equipmentId,
          },
        };
      }
      return { ok: true, value: draft(equipmentId) };
    });

    const items = await loadLayoutCatalog({
      equipmentRepository,
      layoutRepository,
      concurrency: 2,
    });

    expect(maximumActive).toBeLessThanOrEqual(2);
    expect(items).toHaveLength(5);
    expect(items.find((item) => item.equipment.id === "eq-3")?.kind).toBe("failed");
    expect(items.filter((item) => item.kind === "ready")).toHaveLength(4);
  });

  it("stops scheduling stale work when aborted", async () => {
    const controller = new AbortController();
    const equipmentRepository = equipmentRepositoryWith([equipment("eq-1"), equipment("eq-2")]);
    const layoutRepository = layoutRepositoryWith(async (equipmentId) => {
      controller.abort();
      return { ok: true, value: draft(equipmentId) };
    });

    await expect(
      loadLayoutCatalog({ equipmentRepository, layoutRepository, concurrency: 1, signal: controller.signal }),
    ).rejects.toSatisfy(isLayoutCatalogAbort);
  });
});

function equipmentRepositoryWith(
  items: RefrigerationEquipment[],
): RefrigerationEquipmentRepository {
  return {
    list: async () => items,
    get: async (equipmentId) => items.find((item) => item.id === equipmentId) ?? items[0],
    create: async () => items[0],
    update: async () => items[0],
    remove: async () => undefined,
  };
}

function layoutRepositoryWith(
  getDraft: (equipmentId: string) => Promise<RepositoryResult<RefrigerationLayoutDraft>>,
): RefrigerationLayoutRepository {
  return {
    getDraft,
    getPublished: async (equipmentId) => ({ ok: true, value: published(equipmentId) }),
    saveDraft: async (input) => ({ ok: true, value: draft(input.equipmentId) }),
    publishDraft: async (input) => ({
      ok: true,
      value: { draft: draft(input.equipmentId), published: published(input.equipmentId) },
    }),
    listHistory: async (equipmentId) => ({ ok: true, value: [published(equipmentId)] }),
    restoreRevision: async (input) => ({ ok: true, value: draft(input.equipmentId) }),
    uploadImage: async (input) => ({
      ok: true,
      value: published(input.equipmentId).image,
    }),
  };
}
