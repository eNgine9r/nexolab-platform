export type ClimateChamberStatus = "active" | "inactive";

export type ClimateChamber = {
  id: string;
  code: "KK1" | "KK2" | string;
  nodeId: string;
  name: string;
  displayOrder: number;
  status: ClimateChamberStatus;
  version: number;
  createdAt: string;
  updatedAt: string;
};

export type MeasuredParameter = {
  metric: string;
  unit: string;
};

export type MeasurementDevice = {
  id: string;
  businessKey: string;
  deviceType: "temperature_controller" | "energy_meter" | string;
  manufacturer: string;
  model: string;
  unitId: number;
  displayName: string;
  designation: string | null;
  connectionStatus: string;
  status: string;
  measuredParameters: MeasuredParameter[];
  createdAt: string;
  updatedAt: string;
};

export type PhysicalSensor = {
  id: string;
  sensorPosition: "A" | "B" | string;
  inventoryNumber: string;
  serialNumber: string | null;
  calibrationStatus: string;
  status: string;
  createdAt: string;
  updatedAt: string;
};

export type MeasurementChannel = {
  id: string;
  channelId: string;
  deviceId: string;
  controllerUnitId: number;
  channelNumber: number;
  logicalSensorNumber: number;
  displayName: string;
  physicalSensorCount: number;
  physicalSensors: PhysicalSensor[];
  metricType: string;
  unit: string;
  status: string;
  createdAt: string;
  updatedAt: string;
};

export type ClimateChamberEquipment = {
  climateChamber: ClimateChamber;
  temperatureControllers: MeasurementDevice[];
  temperatureChannels: MeasurementChannel[];
  energyMeters: MeasurementDevice[];
  energyMeterEmptyMessage: string | null;
};

export interface ClimateCatalogRepository {
  listChambers(): Promise<ClimateChamber[]>;
  getEquipment(chamberId: string): Promise<ClimateChamberEquipment>;
}

export type HttpClimateCatalogRepositoryOptions = {
  apiBaseUrl: string;
  fetchImpl?: typeof fetch;
};

export class HttpClimateCatalogRepository implements ClimateCatalogRepository {
  private readonly apiBaseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: HttpClimateCatalogRepositoryOptions) {
    this.apiBaseUrl = options.apiBaseUrl.replace(/\/$/, "");
    this.fetchImpl = options.fetchImpl ?? fetch.bind(globalThis);
  }

  async listChambers(): Promise<ClimateChamber[]> {
    const response = await this.request("/api/v1/climate-chambers");
    const payload = await response.json();
    const record = requiredRecord(payload, "climate chamber list");
    return requiredArray(record.items, "climate chamber items").map(parseClimateChamber);
  }

  async getEquipment(chamberId: string): Promise<ClimateChamberEquipment> {
    const normalized = chamberId.trim();
    if (!normalized) throw new Error("Climate chamber id is required.");
    const response = await this.request(
      `/api/v1/climate-chambers/${encodeURIComponent(normalized)}/equipment`,
    );
    const record = requiredRecord(await response.json(), "climate chamber equipment");
    return {
      climateChamber: parseClimateChamber(record.climateChamber),
      temperatureControllers: requiredArray(
        record.temperatureControllers,
        "temperature controllers",
      ).map(parseMeasurementDevice),
      temperatureChannels: requiredArray(
        record.temperatureChannels,
        "temperature channels",
      ).map(parseMeasurementChannel),
      energyMeters: requiredArray(record.energyMeters, "energy meters").map(
        parseMeasurementDevice,
      ),
      energyMeterEmptyMessage: optionalString(record.energyMeterEmptyMessage),
    };
  }

  private async request(path: string): Promise<Response> {
    const response = await this.fetchImpl(`${this.apiBaseUrl}${path}`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new Error(apiErrorMessage(payload, `Climate catalog request failed (${response.status}).`));
    }
    return response;
  }
}

function parseClimateChamber(value: unknown): ClimateChamber {
  const item = requiredRecord(value, "climate chamber");
  return {
    id: requiredString(item.id, "climate chamber id"),
    code: requiredString(item.code, "climate chamber code"),
    nodeId: requiredString(item.node_id, "climate chamber node id"),
    name: requiredString(item.name, "climate chamber name"),
    displayOrder: requiredNumber(item.display_order, "climate chamber display order"),
    status: requiredString(item.status, "climate chamber status") as ClimateChamberStatus,
    version: requiredNumber(item.version, "climate chamber version"),
    createdAt: requiredString(item.created_at, "climate chamber created at"),
    updatedAt: requiredString(item.updated_at, "climate chamber updated at"),
  };
}

function parseMeasurementDevice(value: unknown): MeasurementDevice {
  const item = requiredRecord(value, "measurement device");
  return {
    id: requiredString(item.id, "measurement device id"),
    businessKey: requiredString(item.business_key, "measurement device business key"),
    deviceType: requiredString(item.device_type, "measurement device type"),
    manufacturer: requiredString(item.manufacturer, "measurement device manufacturer"),
    model: requiredString(item.model, "measurement device model"),
    unitId: requiredNumber(item.unit_id, "measurement device unit id"),
    displayName: requiredString(item.display_name, "measurement device display name"),
    designation: optionalString(item.designation),
    connectionStatus: requiredString(item.connection_status, "measurement device connection status"),
    status: requiredString(item.status, "measurement device status"),
    measuredParameters: requiredArray(
      item.measured_parameters,
      "measurement device parameters",
    ).map((parameter) => {
      const record = requiredRecord(parameter, "measured parameter");
      return {
        metric: requiredString(record.metric, "measured parameter metric"),
        unit: requiredString(record.unit, "measured parameter unit"),
      };
    }),
    createdAt: requiredString(item.created_at, "measurement device created at"),
    updatedAt: requiredString(item.updated_at, "measurement device updated at"),
  };
}

function parseMeasurementChannel(value: unknown): MeasurementChannel {
  const item = requiredRecord(value, "measurement channel");
  return {
    id: requiredString(item.id, "measurement channel id"),
    channelId: requiredString(item.channel_id, "measurement channel identifier"),
    deviceId: requiredString(item.device_id, "measurement channel device id"),
    controllerUnitId: requiredNumber(item.controller_unit_id, "controller unit id"),
    channelNumber: requiredNumber(item.channel_number, "measurement channel number"),
    logicalSensorNumber: requiredNumber(
      item.logical_sensor_number,
      "logical sensor number",
    ),
    displayName: requiredString(item.display_name, "measurement channel display name"),
    physicalSensorCount: requiredNumber(
      item.physical_sensor_count,
      "physical sensor count",
    ),
    physicalSensors: requiredArray(item.physical_sensors, "physical sensors").map(
      parsePhysicalSensor,
    ),
    metricType: requiredString(item.metric_type, "measurement channel metric"),
    unit: requiredString(item.unit, "measurement channel unit"),
    status: requiredString(item.status, "measurement channel status"),
    createdAt: requiredString(item.created_at, "measurement channel created at"),
    updatedAt: requiredString(item.updated_at, "measurement channel updated at"),
  };
}

function parsePhysicalSensor(value: unknown): PhysicalSensor {
  const item = requiredRecord(value, "physical sensor");
  return {
    id: requiredString(item.id, "physical sensor id"),
    sensorPosition: requiredString(item.sensor_position, "physical sensor position"),
    inventoryNumber: requiredString(item.inventory_number, "physical sensor inventory number"),
    serialNumber: optionalString(item.serial_number),
    calibrationStatus: requiredString(item.calibration_status, "physical sensor calibration status"),
    status: requiredString(item.status, "physical sensor status"),
    createdAt: requiredString(item.created_at, "physical sensor created at"),
    updatedAt: requiredString(item.updated_at, "physical sensor updated at"),
  };
}

function requiredRecord(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`Invalid ${label} response.`);
  }
  return value as Record<string, unknown>;
}

function requiredArray(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`Invalid ${label} response.`);
  return value;
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) throw new Error(`Invalid ${label}.`);
  return value;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function requiredNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new Error(`Invalid ${label}.`);
  return value;
}

function apiErrorMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object" && !Array.isArray(payload)) {
    const detail = (payload as Record<string, unknown>).detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      const message = (detail as Record<string, unknown>).message;
      if (typeof message === "string" && message.trim()) return message;
    }
  }
  return fallback;
}
