import { describe, expect, it, vi } from "vitest";

import {
  HttpChannelNameRepository,
  type CommissionedChannel,
  type ChannelNameRepository,
} from "./channel-name-repository";
import {
  isActiveCommissionedControllerAsset,
  isCommissionedInputAsset,
  loadEquipmentRegistry,
} from "./asset-registry";
import type { RefrigerationEquipmentRepository } from "@/features/refrigeration/equipment-repository";
import type { ClimateCatalogRepository } from "@/features/refrigeration/climate-catalog-repository";

const channel = (unit: number, input: number): CommissionedChannel => ({
  nodeId: "edge-01",
  equipmentId: "XJP60D-S:rs485-sdm120:" + unit,
  channelId: "rs485-sdm120:" + unit + "-S0" + input,
  controllerLabel: "Dixell №" + unit + " · rs485-sdm120",
  inputNumber: input,
  displayName: "Dixell №" + unit + " · Вхід " + input,
  customName: null,
});

const active = [
  ...Array.from({ length: 6 }, (_, i) => channel(1, i + 1)),
  ...Array.from({ length: 2 }, (_, i) => channel(7, i + 1)),
];

describe("Commissioned input inventory", () => {
  it("uses canonical commissioned 6+2 inputs without any climate-chamber assignment", async () => {
    const equipmentRepository = {
      list: vi.fn(async () => []),
    } as unknown as RefrigerationEquipmentRepository;
    const climateCatalogRepository = {
      listChambers: vi.fn(async () => []),
    } as unknown as ClimateCatalogRepository;
    const channelNameRepository = {
      list: vi.fn(async () => ({ state: "available", nodeId: "edge-01", items: active })),
      setName: vi.fn(),
    } as unknown as ChannelNameRepository;
    const result = await loadEquipmentRegistry({
      equipmentRepository,
      climateCatalogRepository,
      channelNameRepository,
    });
    expect(result.commissionedState).toBe("available");
    expect(result.failures).toEqual([]);
    expect(result.assets.filter(isActiveCommissionedControllerAsset)).toHaveLength(2);
    expect(result.assets.filter(isCommissionedInputAsset)).toHaveLength(8);
    expect(result.assets.filter(isCommissionedInputAsset).every((item) => item.chamberId === null)).toBe(
      true,
    );
    expect(result.assets.filter(isCommissionedInputAsset).map((item) => item.primaryIdentifier)).toContain(
      "rs485-sdm120:1-S01",
    );
  });

  it("reports missing canonical source as unavailable, not inactive", async () => {
    const result = await loadEquipmentRegistry({
      equipmentRepository: { list: async () => [] } as unknown as RefrigerationEquipmentRepository,
      climateCatalogRepository: { listChambers: async () => [] } as unknown as ClimateCatalogRepository,
      channelNameRepository: {
        list: async () => ({ state: "unavailable", nodeId: null, items: [] }),
      } as unknown as ChannelNameRepository,
    });
    expect(result.commissionedState).toBe("unavailable");
    expect(result.failures.some((failure) => failure.chamberId === "active-dixell")).toBe(true);
    expect(result.assets.filter(isActiveCommissionedControllerAsset)).toHaveLength(0);
  });

  it("persists only display name in the API payload, not canonical identity", async () => {
    const fetchImpl = vi.fn(async (_url, init?: RequestInit) => {
      if (init?.method === "PUT") {
        const body = JSON.parse(String(init.body));
        expect(body).toEqual({ node_id: "edge-01", display_name: "Продукт зліва" });
      }
      return new Response(
        JSON.stringify({
          node_id: "edge-01",
          equipment_id: active[0].equipmentId,
          channel_id: active[0].channelId,
          controller_label: active[0].controllerLabel,
          input_number: 1,
          display_name: "Продукт зліва",
          custom_name: "Продукт зліва",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    const repository = new HttpChannelNameRepository("http://127.0.0.1:8082", fetchImpl as typeof fetch);
    const saved = await repository.setName("edge-01", active[0].channelId, "Продукт зліва");
    expect(saved.channelId).toBe(active[0].channelId);
    expect(saved.displayName).toBe("Продукт зліва");
    expect(fetchImpl).toHaveBeenCalledOnce();
    expect(String(fetchImpl.mock.calls[0][0])).toContain(encodeURIComponent(active[0].channelId));
  });
});
