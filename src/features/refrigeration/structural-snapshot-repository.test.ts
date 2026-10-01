import { afterEach, describe, expect, it, vi } from "vitest";

import type { EquipmentLifecycleRepository } from "./equipment-lifecycle-repository";
import type { RefrigerationLayoutRepository } from "./layout-repository";
import {
  clearAllRefrigerationStructuralCaches,
  createCachedEquipmentLifecycleRepository,
  createCachedLayoutRepository,
} from "./refrigeration-structural-cache";

import {
  clearStructuralSnapshotScope,
  HttpRefrigerationStructuralSnapshotRepository,
  inspectStructuralSnapshotRequests,
} from "./structural-snapshot-repository";

const equipmentId = "showcase-106-01";
const now = "2026-08-06T12:00:00.000Z";

function payload() {
  return {
    equipment: {
      id: equipmentId,
      code: "106-01",
      name: "Вітрина 106-01",
      location: "Лабораторія",
      laboratory: "Лабораторія",
      zone: "Зона A",
      climate_chamber_id: "kk1",
      node_id: "edge-01",
      equipment_type: "Холодильна вітрина",
      manufacturer: "NEXOLAB",
      model: "Demo",
      serial_number: "SN-1",
      temperature_class: "M1",
      installed_at: null,
      serviced_at: null,
      lifecycle_status: "active",
      status: "normal",
      average_temperature_c: 4,
      min_temperature_c: 3,
      max_temperature_c: 5,
      online_sensors: 0,
      total_sensors: 1,
      active_alarms: 0,
      last_seen_at: null,
      version: 1,
      created_at: now,
      updated_at: now,
    },
    active_image: null,
    layout: {
      id: "draft-1",
      equipment_id: equipmentId,
      version: 1,
      image: null,
      placements: [{ sensor_id: "channel-1", x: 0.25, y: 0.5 }],
      created_at: now,
      updated_at: now,
    },
    layout_revision: 1,
    placements_count: 1,
    bindings: [
      {
        id: "binding-1",
        equipment_id: equipmentId,
        node_id: "edge-01",
        channel_id: "channel-1",
        slot_key: "front-1-1",
        label: "106-01",
        side: "front",
        shelf: 1,
        position: 1,
        version: 1,
        bound_by: "operator",
        bound_at: now,
        unbound_by: null,
        unbound_at: null,
      },
    ],
    channels: [
      {
        channel_id: "channel-1",
        metric: "temperature",
        unit: "celsius",
        latest_value: null,
        quality: "no-data",
        captured_at: null,
        sample_state: "unknown",
        is_bound: true,
        bound_equipment_id: equipmentId,
        bound_slot_key: "front-1-1",
      },
    ],
    generated_at: now,
  };
}

afterEach(() => {
  clearAllRefrigerationStructuralCaches();
  clearStructuralSnapshotScope("scope-a");
  clearStructuralSnapshotScope("scope-b");
});

describe("HttpRefrigerationStructuralSnapshotRepository", () => {
  it("deduplicates concurrent equipment reads and preserves no-sample channels", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify(payload()), { status: 200 }));
    const repository = new HttpRefrigerationStructuralSnapshotRepository({
      apiBaseUrl: "http://127.0.0.1:8082",
      scope: "scope-a",
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    const [first, second] = await Promise.all([repository.get(equipmentId), repository.get(equipmentId)]);

    expect(fetchImpl).toHaveBeenCalledOnce();
    expect(first).toEqual(second);
    expect(first.channels[0]).toMatchObject({
      latestValue: null,
      sampleState: "unknown",
    });
    expect(inspectStructuralSnapshotRequests("scope-a", equipmentId)).toBe(1);
  });

  it("isolates caches by organization scope", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify(payload()), { status: 200 }));
    const first = new HttpRefrigerationStructuralSnapshotRepository({
      apiBaseUrl: "http://127.0.0.1:8082",
      scope: "scope-a",
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    const second = new HttpRefrigerationStructuralSnapshotRepository({
      apiBaseUrl: "http://127.0.0.1:8082",
      scope: "scope-b",
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    await first.get(equipmentId);
    await second.get(equipmentId);

    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("refreshes an empty snapshot immediately after a successful configuration save", async () => {
    const empty = { ...payload(), bindings: [], placements_count: 0 };
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(empty)))
      .mockResolvedValueOnce(new Response(JSON.stringify(payload())));
    const snapshot = new HttpRefrigerationStructuralSnapshotRepository({
      apiBaseUrl: "http://127.0.0.1:8082",
      scope: "scope-a",
      fetchImpl,
    });
    expect((await snapshot.get(equipmentId)).bindings).toHaveLength(0);
    const lifecycle = createCachedEquipmentLifecycleRepository(
      {
        replaceSensorConfiguration: vi.fn().mockResolvedValue({}),
      } as unknown as EquipmentLifecycleRepository,
      "scope-a",
    );
    await lifecycle.replaceSensorConfiguration(equipmentId, 1, 1, []);
    expect((await snapshot.get(equipmentId)).bindings).toHaveLength(1);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it.each(["saveDraft", "publishDraft", "restoreRevision", "uploadImage"] as const)(
    "refreshes only the affected snapshot after successful %s",
    async (method) => {
      const fetchImpl = vi.fn(async () => new Response(JSON.stringify(payload())));
      const snapshot = new HttpRefrigerationStructuralSnapshotRepository({
        apiBaseUrl: "http://127.0.0.1:8082",
        scope: "scope-a",
        fetchImpl,
      });
      const otherOrganization = new HttpRefrigerationStructuralSnapshotRepository({
        apiBaseUrl: "http://127.0.0.1:8082",
        scope: "scope-b",
        fetchImpl,
      });
      await snapshot.get(equipmentId);
      await otherOrganization.get(equipmentId);
      const layouts = createCachedLayoutRepository(
        {
          [method]: vi.fn().mockResolvedValue({ ok: true, value: null }),
        } as unknown as RefrigerationLayoutRepository,
        "scope-a",
      );
      const input = {
        equipmentId,
        expectedVersion: 1,
        imageId: null,
        placements: [],
        revisionId: "r1",
        actorId: "operator",
        file: new File([], "photo.png"),
      };
      if (method === "uploadImage") await layouts.uploadImage(input);
      else if (method === "restoreRevision") await layouts.restoreRevision(input);
      else if (method === "saveDraft") await layouts.saveDraft(input);
      else await layouts.publishDraft(input);
      await snapshot.get(equipmentId);
      await otherOrganization.get(equipmentId);
      expect(fetchImpl).toHaveBeenCalledTimes(3);
    },
  );

  it("keeps a usable snapshot when a mutation is rejected", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify(payload())));
    const snapshot = new HttpRefrigerationStructuralSnapshotRepository({
      apiBaseUrl: "http://127.0.0.1:8082",
      scope: "scope-a",
      fetchImpl,
    });
    const before = await snapshot.get(equipmentId);
    const layouts = createCachedLayoutRepository(
      {
        publishDraft: vi.fn().mockResolvedValue({ ok: false, error: {} }),
      } as unknown as RefrigerationLayoutRepository,
      "scope-a",
    );
    await layouts.publishDraft({ equipmentId, expectedVersion: 1 });
    expect(await snapshot.get(equipmentId)).toBe(before);
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it("keeps another equipment snapshot cached in the same organization", async () => {
    const otherId = "other-equipment";
    const other = payload();
    other.equipment.id = otherId;
    other.layout.equipment_id = otherId;
    other.bindings[0]!.equipment_id = otherId;
    other.channels[0]!.bound_equipment_id = otherId;
    const fetchImpl = vi.fn(
      async (url: string | URL | Request) =>
        new Response(JSON.stringify(String(url).includes(otherId) ? other : payload())),
    );
    const snapshot = new HttpRefrigerationStructuralSnapshotRepository({
      apiBaseUrl: "http://127.0.0.1:8082",
      scope: "scope-a",
      fetchImpl,
    });
    await snapshot.get(equipmentId);
    const otherSnapshot = await snapshot.get(otherId);
    const lifecycle = createCachedEquipmentLifecycleRepository(
      {
        replaceSensorConfiguration: vi.fn().mockResolvedValue({}),
      } as unknown as EquipmentLifecycleRepository,
      "scope-a",
    );
    await lifecycle.replaceSensorConfiguration(equipmentId, 1, 1, []);
    await snapshot.get(equipmentId);
    expect(await snapshot.get(otherId)).toBe(otherSnapshot);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });

  it("does not reuse or cache a pre-mutation in-flight response after invalidation", async () => {
    let resolveOld!: (response: Response) => void;
    let resolveFresh!: (response: Response) => void;
    const fetchImpl = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            resolveOld = resolve;
          }),
      )
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            resolveFresh = resolve;
          }),
      );
    const snapshot = new HttpRefrigerationStructuralSnapshotRepository({
      apiBaseUrl: "http://127.0.0.1:8082",
      scope: "scope-a",
      fetchImpl,
    });
    const oldRead = snapshot.get(equipmentId);
    snapshot.invalidate(equipmentId);
    const freshRead = snapshot.get(equipmentId);
    resolveOld(new Response(JSON.stringify({ ...payload(), bindings: [] })));
    expect((await oldRead).bindings).toHaveLength(0);
    expect(snapshot.get(equipmentId)).toBe(freshRead);
    resolveFresh(new Response(JSON.stringify(payload())));
    const fresh = await freshRead;
    expect(await snapshot.get(equipmentId)).toBe(fresh);
    expect(fresh.bindings).toHaveLength(1);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });
});
