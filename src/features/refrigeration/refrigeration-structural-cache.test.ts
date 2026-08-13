import { beforeEach, describe, expect, it, vi } from "vitest";

import { refrigerationEquipment, type RefrigerationEquipment } from "@/data/refrigeration";

import type { RefrigerationEquipmentRepository } from "./equipment-repository";
import type {
  RefrigerationLayoutDraft,
  RefrigerationLayoutRepository,
  RepositoryResult,
} from "./layout-repository";
import {
  clearAllRefrigerationStructuralCaches,
  createCachedLayoutRepository,
  createCachedRefrigerationEquipmentRepository,
} from "./refrigeration-structural-cache";

const scope = "http://nexolab.local|org-a";
const equipment = refrigerationEquipment[0];

beforeEach(() => {
  clearAllRefrigerationStructuralCaches();
});

describe("refrigeration structural cache sharing", () => {
  it("deduplicates the equipment catalog across separately created runtime repositories", async () => {
    const firstRaw = equipmentRepository([equipment]);
    const secondRaw = equipmentRepository([equipment]);
    const first = createCachedRefrigerationEquipmentRepository(firstRaw, scope);
    const second = createCachedRefrigerationEquipmentRepository(secondRaw, scope);

    const [firstResult, secondResult] = await Promise.all([first.list(), second.list()]);

    expect(firstResult).toEqual([equipment]);
    expect(secondResult).toEqual([equipment]);
    expect(firstRaw.list).toHaveBeenCalledTimes(1);
    expect(secondRaw.list).not.toHaveBeenCalled();
  });

  it("invalidates the shared equipment catalog after a mutation", async () => {
    const firstRaw = equipmentRepository([equipment]);
    const secondRaw = equipmentRepository([equipment]);
    const first = createCachedRefrigerationEquipmentRepository(firstRaw, scope);
    const second = createCachedRefrigerationEquipmentRepository(secondRaw, scope);

    await first.list();
    await second.update(equipment.id, equipmentInput(equipment), equipment.version);
    await first.list();

    expect(secondRaw.update).toHaveBeenCalledTimes(1);
    expect(firstRaw.list).toHaveBeenCalledTimes(2);
  });

  it("deduplicates layout reads across runtime repositories and invalidates after save", async () => {
    const draft = layoutDraft(equipment.id);
    const firstRaw = layoutRepository(draft);
    const secondRaw = layoutRepository(draft);
    const first = createCachedLayoutRepository(firstRaw, scope);
    const second = createCachedLayoutRepository(secondRaw, scope);

    const [firstPublished, secondPublished] = await Promise.all([
      first.getPublished(equipment.id),
      second.getPublished(equipment.id),
    ]);

    expect(firstPublished).toEqual({ ok: true, value: null });
    expect(secondPublished).toEqual({ ok: true, value: null });
    expect(firstRaw.getPublished).toHaveBeenCalledTimes(1);
    expect(secondRaw.getPublished).not.toHaveBeenCalled();

    await second.saveDraft({
      equipmentId: equipment.id,
      expectedVersion: draft.version,
      imageId: null,
      placements: [],
    });
    await first.getPublished(equipment.id);

    expect(secondRaw.saveDraft).toHaveBeenCalledTimes(1);
    expect(firstRaw.getPublished).toHaveBeenCalledTimes(2);
  });
});

function equipmentRepository(items: RefrigerationEquipment[]): RefrigerationEquipmentRepository {
  const list = vi.fn(async () => items);
  const get = vi.fn(async (equipmentId: string) => {
    const found = items.find((item) => item.id === equipmentId);
    if (!found) throw new Error("not found");
    return found;
  });
  const create = vi.fn(async () => items[0]);
  const update = vi.fn(async () => ({ ...items[0], version: items[0].version + 1 }));
  const remove = vi.fn(async () => undefined);
  return { list, get, create, update, remove };
}

function layoutRepository(draft: RefrigerationLayoutDraft): RefrigerationLayoutRepository {
  const success = <T>(value: T): RepositoryResult<T> => ({ ok: true, value });
  return {
    getDraft: vi.fn(async () => success(draft)),
    getPublished: vi.fn(async () => success(null)),
    saveDraft: vi.fn(async () => success({ ...draft, version: draft.version + 1 })),
    publishDraft: vi.fn(async () => ({
      ok: false,
      error: { code: "LAYOUT_NOT_FOUND", equipmentId: draft.equipmentId },
    })),
    listHistory: vi.fn(async () => success([])),
    restoreRevision: vi.fn(async () => success(draft)),
    uploadImage: vi.fn(async () => ({
      ok: false,
      error: { code: "LAYOUT_NOT_FOUND", equipmentId: draft.equipmentId },
    })),
  };
}

function layoutDraft(equipmentId: string): RefrigerationLayoutDraft {
  return {
    id: "draft-1",
    equipmentId,
    version: 1,
    etag: 'W/"layout-draft-v1"',
    imageId: null,
    image: null,
    placements: [],
    createdAt: "2026-08-13T06:00:00Z",
    updatedAt: "2026-08-13T06:00:00Z",
  };
}

function equipmentInput(item: RefrigerationEquipment) {
  return {
    code: item.code,
    name: item.name,
    location: item.location,
    laboratory: item.laboratory ?? "",
    zone: item.zone ?? "",
    climateChamberId: item.climateChamberId ?? undefined,
    nodeId: item.nodeId ?? "",
    type: item.type,
    manufacturer: item.manufacturer,
    model: item.model,
    serialNumber: item.serialNumber,
    temperatureClass: item.temperatureClass,
    installedAt: item.installedAt,
    servicedAt: item.servicedAt,
    lifecycleStatus: item.lifecycleStatus,
    totalSensors: item.totalSensors,
  };
}
