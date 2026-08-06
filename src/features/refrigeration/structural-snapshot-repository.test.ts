import { afterEach, describe, expect, it, vi } from "vitest";

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

    const [first, second] = await Promise.all([
      repository.get(equipmentId),
      repository.get(equipmentId),
    ]);

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
});
