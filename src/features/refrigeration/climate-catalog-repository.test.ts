import { describe, expect, it, vi } from "vitest";

import { HttpClimateCatalogRepository } from "./climate-catalog-repository";

const chamber = (code: "KK1" | "KK2", order: number) => ({
  id: `chamber-${code.toLowerCase()}`,
  code,
  node_id: code.toLowerCase(),
  name: `Кліматична камера №${order}`,
  display_order: order,
  status: "active",
  version: 1,
  created_at: "2026-07-30T08:00:00Z",
  updated_at: "2026-07-30T08:00:00Z",
});

const channel = (code: "KK1" | "KK2", controller: number, input: number, sensor: number) => ({
  id: `${code}-${sensor}`,
  channel_id: `${code}-DIXELL-${controller}-CH${input}`,
  device_id: `${code}-DIXELL-${controller}`,
  controller_unit_id: controller,
  channel_number: input,
  logical_sensor_number: sensor,
  display_name: `Dixell №${controller}_${input}`,
  physical_sensor_count: code === "KK1" ? 1 : 2,
  physical_sensors: (code === "KK1" ? ["A"] : ["A", "B"]).map((position) => ({
    id: `${code}-${sensor}-${position}`,
    sensor_position: position,
    inventory_number: `${sensor}-${position}`,
    serial_number: null,
    calibration_status: "untracked",
    status: "active",
    created_at: "2026-07-30T08:00:00Z",
    updated_at: "2026-07-30T08:00:00Z",
  })),
  metric_type: "temperature",
  unit: "degC",
  status: "active",
  created_at: "2026-07-30T08:00:00Z",
  updated_at: "2026-07-30T08:00:00Z",
});

function response(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("HttpClimateCatalogRepository", () => {
  it("parses chambers in server order and uses the versioned endpoint", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      response({ items: [chamber("KK1", 1), chamber("KK2", 2)] }),
    );
    const repository = new HttpClimateCatalogRepository({
      apiBaseUrl: "http://nexolab.test/",
      fetchImpl,
    });

    const items = await repository.listChambers();

    expect(items.map((item) => item.code)).toEqual(["KK1", "KK2"]);
    expect(items.map((item) => item.nodeId)).toEqual(["kk1", "kk2"]);
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://nexolab.test/api/v1/climate-chambers",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("parses KK2 physical A/B sensors and the neutral energy-meter empty state", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      response({
        climateChamber: chamber("KK2", 2),
        temperatureControllers: [
          {
            id: "kk2-controller-101",
            business_key: "KK2-DIXELL-101",
            device_type: "temperature_controller",
            manufacturer: "Dixell",
            model: "Dixell temperature controller",
            unit_id: 101,
            display_name: "Dixell №101",
            designation: null,
            connection_status: "unknown",
            status: "active",
            measured_parameters: [{ metric: "temperature", unit: "degC" }],
            created_at: "2026-07-30T08:00:00Z",
            updated_at: "2026-07-30T08:00:00Z",
          },
        ],
        temperatureChannels: [channel("KK2", 101, 1, 471)],
        energyMeters: [],
        energyMeterEmptyMessage:
          "До цієї кліматичної камери лічильники електроенергії ще не підключені.",
      }),
    );
    const repository = new HttpClimateCatalogRepository({
      apiBaseUrl: "http://nexolab.test",
      fetchImpl,
    });

    const catalog = await repository.getEquipment("chamber-kk2");

    expect(catalog.temperatureControllers[0]?.unitId).toBe(101);
    expect(catalog.temperatureChannels[0]).toMatchObject({
      channelId: "KK2-DIXELL-101-CH1",
      logicalSensorNumber: 471,
      physicalSensorCount: 2,
    });
    expect(
      catalog.temperatureChannels[0]?.physicalSensors.map((item) => item.inventoryNumber),
    ).toEqual(["471-A", "471-B"]);
    expect(catalog.energyMeters).toEqual([]);
    expect(catalog.energyMeterEmptyMessage).toBe(
      "До цієї кліматичної камери лічильники електроенергії ще не підключені.",
    );
  });
});
