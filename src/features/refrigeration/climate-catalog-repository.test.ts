import { describe, expect, it, vi } from "vitest";

import { HttpClimateCatalogRepository } from "./climate-catalog-repository";

const chamber = (code: "KK1" | "KK2", order: number) => ({
  id: `chamber-${code.toLowerCase()}`,
  code,
  node_id: "edge-01",
  bus_id: "bus-rs485-main-01",
  bus_key: "rs485-main-01",
  name: `Кліматична камера №${order}`,
  display_order: order,
  status: "active",
  version: 1,
  created_at: "2026-07-30T08:00:00Z",
  updated_at: "2026-07-30T08:00:00Z",
});

const channel = (code: "KK1" | "KK2", controller: number, input: number, sensor: number) => ({
  id: `${code}-${sensor}`,
  channel_id: `${controller}-${String(input).padStart(2, "0")}`,
  source_channel_id: `${controller}-${String(input).padStart(2, "0")}`,
  device_id: `DIXELL-${controller}`,
  controller_unit_id: controller,
  channel_number: input,
  logical_sensor_number: sensor,
  display_name: `Dixell №${controller}_${input}`,
  physical_sensor_count: code === "KK1" ? 1 : 2,
  physical_sensors: (code === "KK1" ? ["A"] : ["A", "B"]).map((position) => ({
    id: `${code}-${sensor}-${position}`,
    sensor_position: position,
    inventory_number: code === "KK1" ? `${sensor}` : `${sensor}-${position}`,
    serial_number: null,
    calibration_status: "untracked",
    status: "active",
    version: 1,
    created_at: "2026-07-30T08:00:00Z",
    updated_at: "2026-07-30T08:00:00Z",
  })),
  metric_type: "temperature.probe",
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
  it("parses logical chambers sharing one physical edge node and RS485 bus", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(response({ items: [chamber("KK1", 1), chamber("KK2", 2)] }));
    const repository = new HttpClimateCatalogRepository({
      apiBaseUrl: "http://nexolab.test/",
      fetchImpl,
    });

    const items = await repository.listChambers();

    expect(items.map((item) => item.code)).toEqual(["KK1", "KK2"]);
    expect(items.map((item) => item.id)).toEqual(["chamber-kk1", "chamber-kk2"]);
    expect(items.map((item) => item.nodeId)).toEqual(["chamber-kk1", "chamber-kk2"]);
    expect(items.map((item) => item.transportNodeId)).toEqual(["edge-01", "edge-01"]);
    expect(items.map((item) => item.busKey)).toEqual(["rs485-main-01", "rs485-main-01"]);
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
            business_key: "DIXELL-101",
            device_type: "temperature_controller",
            manufacturer: "Dixell",
            model: "XJP60D",
            unit_id: 101,
            display_name: "Dixell №101",
            designation: null,
            connection_status: "unknown",
            status: "active",
            measured_parameters: [{ metric: "temperature.probe", unit: "degC" }],
            version: 1,
            created_at: "2026-07-30T08:00:00Z",
            updated_at: "2026-07-30T08:00:00Z",
          },
        ],
        temperatureChannels: [channel("KK2", 101, 1, 471)],
        energyMeters: [],
        energyMeterEmptyMessage: "До цієї кліматичної камери лічильники електроенергії ще не підключені.",
      }),
    );
    const repository = new HttpClimateCatalogRepository({
      apiBaseUrl: "http://nexolab.test",
      fetchImpl,
    });

    const catalog = await repository.getEquipment("chamber-kk2");

    expect(catalog.climateChamber).toMatchObject({
      id: "chamber-kk2",
      nodeId: "chamber-kk2",
      transportNodeId: "edge-01",
      busKey: "rs485-main-01",
    });
    expect(catalog.temperatureControllers[0]?.unitId).toBe(101);
    expect(catalog.temperatureChannels[0]).toMatchObject({
      channelId: "101-01",
      sourceChannelId: "101-01",
      logicalSensorNumber: 471,
      physicalSensorCount: 2,
    });
    expect(catalog.temperatureChannels[0]?.physicalSensors.map((item) => item.inventoryNumber)).toEqual([
      "471-A",
      "471-B",
    ]);
    expect(catalog.energyMeters).toEqual([]);
    expect(catalog.energyMeterEmptyMessage).toBe(
      "До цієї кліматичної камери лічильники електроенергії ще не підключені.",
    );
  });

  it("sends versioned safe metadata patches without transport fields", async () => {
    const deviceResponse = {
      id: "device-1",
      business_key: "METER-1",
      device_type: "energy_meter",
      manufacturer: "TOMZN",
      model: "DDS238-2",
      unit_id: 12,
      display_name: "Лічильник 1",
      designation: "W1",
      connection_status: "connected",
      status: "active",
      measured_parameters: [{ metric: "energy.total", unit: "kWh" }],
      version: 4,
      created_at: "2026-07-30T08:00:00Z",
      updated_at: "2026-08-19T16:00:00Z",
    };
    const sensorResponse = {
      id: "sensor-1",
      sensor_position: "A",
      inventory_number: "LAB-197",
      serial_number: "SN-197",
      calibration_status: "current",
      status: "active",
      version: 3,
      created_at: "2026-07-30T08:00:00Z",
      updated_at: "2026-08-19T16:00:00Z",
    };
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(response(deviceResponse))
      .mockResolvedValueOnce(response(sensorResponse));
    const repository = new HttpClimateCatalogRepository({
      apiBaseUrl: "http://nexolab.test",
      fetchImpl,
    });

    await expect(
      repository.updateMeasurementDevice(
        "chamber-kk1",
        "device-1",
        {
          displayName: "Лічильник 1",
          designation: "W1",
          manufacturer: "TOMZN",
          model: "DDS238-2",
        },
        3,
      ),
    ).resolves.toMatchObject({ id: "device-1", unitId: 12, version: 4 });
    await expect(
      repository.updatePhysicalSensor(
        "chamber-kk1",
        "sensor-1",
        { inventoryNumber: "LAB-197", serialNumber: "SN-197", calibrationStatus: "current" },
        2,
      ),
    ).resolves.toMatchObject({ id: "sensor-1", sensorPosition: "A", version: 3 });

    const deviceInit = fetchImpl.mock.calls[0]?.[1] as RequestInit;
    expect(deviceInit.method).toBe("PATCH");
    expect(deviceInit.headers).toMatchObject({
      "If-Match": 'W/"measurement-device-v3"',
      "X-Audit-Reason": "Updated measurement device administrative metadata",
    });
    expect(JSON.parse(String(deviceInit.body))).toEqual({
      display_name: "Лічильник 1",
      designation: "W1",
      manufacturer: "TOMZN",
      model: "DDS238-2",
    });
    expect(String(deviceInit.body)).not.toContain("unit_id");

    const sensorInit = fetchImpl.mock.calls[1]?.[1] as RequestInit;
    expect(sensorInit.headers).toMatchObject({
      "If-Match": 'W/"physical-sensor-v2"',
      "X-Audit-Reason": "Updated physical sensor administrative metadata",
    });
    expect(JSON.parse(String(sensorInit.body))).toEqual({
      inventory_number: "LAB-197",
      serial_number: "SN-197",
      calibration_status: "current",
    });
    expect(String(sensorInit.body)).not.toContain("sensor_position");
  });
});
