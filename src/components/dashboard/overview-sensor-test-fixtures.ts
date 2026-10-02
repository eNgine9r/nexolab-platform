import type { ClimateChamberEquipment } from "@/features/refrigeration/climate-catalog-repository";

export function overviewCatalogFixture(): ClimateChamberEquipment {
  return {
    climateChamber: {
      id: "camera-2",
      code: "KK2",
      nodeId: "camera-2",
      transportNodeId: "edge-01",
      busId: "bus-1",
      busKey: "main",
      name: "Камера №2",
      displayOrder: 2,
      status: "active",
      version: 1,
      createdAt: "2026-10-01",
      updatedAt: "2026-10-01",
    },
    temperatureControllers: [
      {
        id: "device-106",
        businessKey: "DIXELL-106",
        deviceType: "temperature_controller",
        manufacturer: "Dixell",
        model: "XJP60D",
        unitId: 106,
        displayName: "Контролер К106",
        designation: null,
        connectionStatus: "unknown",
        status: "active",
        measuredParameters: [],
        version: 1,
      },
    ],
    temperatureChannels: [3, 4].map((channel) => ({
      id: `channel-${channel}`,
      channelId: `106-0${channel}`,
      sourceChannelId: `106-0${channel}`,
      deviceId: "device-106",
      controllerUnitId: 106,
      channelNumber: channel,
      logicalSensorNumber: 500 + channel,
      displayName: channel === 3 ? "Повітря" : "Продукт",
      physicalSensorCount: 1,
      physicalSensors: [],
      metricType: "temperature.probe",
      unit: "degC",
      status: "active",
    })),
    energyMeters: [],
    energyMeterEmptyMessage: null,
  };
}
