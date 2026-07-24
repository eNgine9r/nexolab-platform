export type EquipmentStatus = "normal" | "warning" | "alarm" | "offline";
export type SensorSide = "front" | "rear";
export type SensorStatus = "normal" | "warning" | "alarm" | "no-data";

export type EquipmentImageMimeType = "image/jpeg" | "image/png" | "image/webp";

export interface EquipmentImageMetadata {
  id: string;
  fileName: string;
  mimeType: EquipmentImageMimeType;
  widthPx: number;
  heightPx: number;
  sizeBytes: number;
  sourceUrl: string | null;
  alt: string;
  updatedAt: string;
}

export interface RefrigerationSensor {
  id: string;
  label: string;
  name: string;
  side: SensorSide;
  shelf: number;
  position: number;
  x: number;
  y: number;
  temperatureC: number | null;
  status: SensorStatus;
  updatedAt: string;
  trend: number[];
}

export interface RefrigerationEquipment {
  id: string;
  code: string;
  name: string;
  location: string;
  type: string;
  manufacturer: string;
  model: string;
  serialNumber: string;
  temperatureClass: string;
  installedAt: string;
  servicedAt: string;
  status: EquipmentStatus;
  averageTemperatureC: number;
  minTemperatureC: number;
  maxTemperatureC: number;
  onlineSensors: number;
  totalSensors: number;
  activeAlarms: number;
  lastSeenAt: string;
  image: EquipmentImageMetadata | null;
  sensors: RefrigerationSensor[];
}

const statusFor = (index: number): SensorStatus => {
  if (index === 17 || index === 41) return "warning";
  if (index === 29) return "alarm";
  return "normal";
};

function buildSensors(): RefrigerationSensor[] {
  return Array.from({ length: 48 }, (_, index) => {
    const side: SensorSide = index < 24 ? "front" : "rear";
    const localIndex = index % 24;
    const shelf = Math.floor(localIndex / 6) + 1;
    const position = (localIndex % 6) + 1;
    const column = position - 1;
    const xBase = 0.17 + column * 0.13;
    const yBase = 0.21 + (shelf - 1) * 0.205;
    const rearOffset = side === "rear" ? 0.032 : -0.032;
    const temperature = Number((1.4 + ((index * 7) % 29) / 10).toFixed(1));
    const label = `${String(localIndex + 1).padStart(2, "0")}${side === "front" ? "F" : "R"}`;

    return {
      id: `sensor-${index + 1}`,
      label,
      name: `${side === "front" ? "Передній" : "Задній"} фронт ${String(localIndex + 1).padStart(2, "0")}`,
      side,
      shelf,
      position,
      x: Math.min(0.94, xBase + rearOffset),
      y: Math.min(0.91, yBase + (side === "rear" ? 0.055 : 0)),
      temperatureC: temperature,
      status: statusFor(index),
      updatedAt: "2026-07-24T14:23:45Z",
      trend: Array.from({ length: 12 }, (_, point) =>
        Number((temperature + Math.sin((point + index) / 2.2) * 0.24).toFixed(2)),
      ),
    };
  });
}

const sensors = buildSensors();

export const refrigerationEquipment: RefrigerationEquipment[] = [
  {
    id: "showcase-106-01",
    code: "CS-P1250-2024-106-01",
    name: "Вітрина №106-01",
    location: "Лабораторія 1 · Зона A",
    type: "Холодильна вітрина",
    manufacturer: "ColdStream",
    model: "Premium 1250",
    serialNumber: "X-PROD-10601",
    temperatureClass: "3M1 (0…+5 °C)",
    installedAt: "2025-05-15",
    servicedAt: "2026-07-12",
    status: "normal",
    averageTemperatureC: 2.2,
    minTemperatureC: 1.1,
    maxTemperatureC: 6.4,
    onlineSensors: 48,
    totalSensors: 48,
    activeAlarms: 1,
    lastSeenAt: "2026-07-24T14:23:45Z",
    image: null,
    sensors,
  },
  {
    id: "showcase-107-02",
    code: "CS-P900-2024-107-02",
    name: "Вітрина №107-02",
    location: "Лабораторія 1 · Зона B",
    type: "Холодильна вітрина",
    manufacturer: "ColdStream",
    model: "Compact 900",
    serialNumber: "X-PROD-10702",
    temperatureClass: "3M2 (-1…+7 °C)",
    installedAt: "2025-06-02",
    servicedAt: "2026-06-28",
    status: "warning",
    averageTemperatureC: 4.8,
    minTemperatureC: 2.4,
    maxTemperatureC: 8.1,
    onlineSensors: 22,
    totalSensors: 24,
    activeAlarms: 2,
    lastSeenAt: "2026-07-24T14:21:19Z",
    image: null,
    sensors: sensors.slice(0, 24),
  },
  {
    id: "cold-room-201",
    code: "CR-2024-201",
    name: "Холодильна камера №201",
    location: "Лабораторія 2 · Північна стіна",
    type: "Холодильна камера",
    manufacturer: "NEXOTHERM",
    model: "CR-12",
    serialNumber: "NX-CR-00201",
    temperatureClass: "2L1 (-18…-15 °C)",
    installedAt: "2025-08-09",
    servicedAt: "2026-07-03",
    status: "normal",
    averageTemperatureC: -17.2,
    minTemperatureC: -18.4,
    maxTemperatureC: -15.9,
    onlineSensors: 16,
    totalSensors: 16,
    activeAlarms: 0,
    lastSeenAt: "2026-07-24T14:23:30Z",
    image: null,
    sensors: sensors.slice(0, 16).map((sensor, index) => ({
      ...sensor,
      id: `cold-room-sensor-${index + 1}`,
      temperatureC: Number((-18.4 + (index % 8) * 0.34).toFixed(1)),
    })),
  },
];

export function getRefrigerationEquipment(id: string): RefrigerationEquipment | undefined {
  return refrigerationEquipment.find((equipment) => equipment.id === id);
}
