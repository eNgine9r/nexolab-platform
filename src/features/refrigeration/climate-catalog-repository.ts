export type ClimateChamber = {
  id: string;
  code: string;
  nodeId: string;
  busId: string;
  busKey: string;
  name: string;
  displayOrder: number;
  status: "active" | "inactive";
  version: number;
  createdAt: string;
  updatedAt: string;
};

export type MeasurementDevice = {
  id: string;
  businessKey: string;
  deviceType: "temperature_controller" | "energy_meter";
  manufacturer: string;
  model: string;
  unitId: number;
  displayName: string;
  designation: string | null;
  connectionStatus: "unknown" | "connected" | "disconnected";
  status: string;
  measuredParameters: Array<{ metric: string; unit: string }>;
};

export type PhysicalSensor = {
  id: string;
  sensorPosition: "A" | "B";
  inventoryNumber: string;
  serialNumber: string | null;
  calibrationStatus: "untracked" | "current" | "due" | "expired";
  status: string;
};

export type MeasurementChannel = {
  id: string;
  channelId: string;
  sourceChannelId: string;
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

export class HttpClimateCatalogRepository implements ClimateCatalogRepository {
  private readonly apiBaseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: { apiBaseUrl: string; fetchImpl?: typeof fetch }) {
    this.apiBaseUrl = normalizeBaseUrl(options.apiBaseUrl);
    this.fetchImpl = options.fetchImpl ?? fetch.bind(globalThis);
  }

  async listChambers(): Promise<ClimateChamber[]> {
    const payload = asRecord(await this.json("/api/v1/climate-chambers"));
    if (!payload || !Array.isArray(payload.items)) throw invalidResponse();
    return payload.items.map(parseChamber).sort(compareChambers);
  }

  async getEquipment(chamberId: string): Promise<ClimateChamberEquipment> {
    const payload = asRecord(
      await this.json(`/api/v1/climate-chambers/${encodeURIComponent(chamberId)}/equipment`),
    );
    if (!payload) throw invalidResponse();
    const chamber = parseChamber(payload.climateChamber ?? payload.climate_chamber);
    const controllers = readArray(
      payload.temperatureControllers ?? payload.temperature_controllers,
    ).map(parseDevice);
    const channels = readArray(payload.temperatureChannels ?? payload.temperature_channels).map(
      parseChannel,
    );
    const energyMeters = readArray(payload.energyMeters ?? payload.energy_meters).map(parseDevice);
    return {
      climateChamber: chamber,
      temperatureControllers: controllers.sort((left, right) => left.unitId - right.unitId),
      temperatureChannels: channels.sort(
        (left, right) =>
          left.controllerUnitId - right.controllerUnitId || left.channelNumber - right.channelNumber,
      ),
      energyMeters: energyMeters.sort(
        (left, right) =>
          (left.designation ?? "").localeCompare(right.designation ?? "", "uk-UA", {
            numeric: true,
          }) || left.unitId - right.unitId,
      ),
      energyMeterEmptyMessage: readOptionalString(
        payload.energyMeterEmptyMessage ?? payload.energy_meter_empty_message,
      ),
    };
  }

  private async json(path: string): Promise<unknown> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.apiBaseUrl}${path}`, {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
    } catch {
      throw new Error("Не вдалося з’єднатися з каталогом кліматичних камер.");
    }
    const payload = await readJson(response);
    if (!response.ok) {
      const detail = asRecord(asRecord(payload)?.detail);
      throw new Error(readString(detail?.message) ?? "Каталог кліматичних камер недоступний.");
    }
    return payload;
  }
}

function parseChamber(value: unknown): ClimateChamber {
  const record = asRecord(value);
  const id = readString(record?.id);
  const code = readString(record?.code);
  const nodeId = readString(record?.node_id);
  const busId = readString(record?.bus_id);
  const busKey = readString(record?.bus_key);
  const name = readString(record?.name);
  const displayOrder = readPositiveInteger(record?.display_order);
  const status = record?.status;
  const version = readPositiveInteger(record?.version);
  const createdAt = readString(record?.created_at);
  const updatedAt = readString(record?.updated_at);
  if (
    !id ||
    !code ||
    !nodeId ||
    !busId ||
    !busKey ||
    !name ||
    displayOrder === null ||
    (status !== "active" && status !== "inactive") ||
    version === null ||
    !createdAt ||
    !updatedAt
  ) {
    throw invalidResponse();
  }
  return { id, code, nodeId, busId, busKey, name, displayOrder, status, version, createdAt, updatedAt };
}

function parseDevice(value: unknown): MeasurementDevice {
  const record = asRecord(value);
  const id = readString(record?.id);
  const businessKey = readString(record?.business_key);
  const deviceType = record?.device_type;
  const manufacturer = readString(record?.manufacturer);
  const model = readString(record?.model);
  const unitId = readPositiveInteger(record?.unit_id);
  const displayName = readString(record?.display_name);
  const connectionStatus = record?.connection_status;
  const status = readString(record?.status);
  if (
    !id ||
    !businessKey ||
    (deviceType !== "temperature_controller" && deviceType !== "energy_meter") ||
    !manufacturer ||
    !model ||
    unitId === null ||
    !displayName ||
    (connectionStatus !== "unknown" && connectionStatus !== "connected" && connectionStatus !== "disconnected") ||
    !status
  ) {
    throw invalidResponse();
  }
  return {
    id,
    businessKey,
    deviceType,
    manufacturer,
    model,
    unitId,
    displayName,
    designation: readOptionalString(record?.designation),
    connectionStatus,
    status,
    measuredParameters: readArray(record?.measured_parameters).map((parameter) => {
      const item = asRecord(parameter);
      const metric = readString(item?.metric);
      const unit = readString(item?.unit);
      if (!metric || !unit) throw invalidResponse();
      return { metric, unit };
    }),
  };
}

function parseChannel(value: unknown): MeasurementChannel {
  const record = asRecord(value);
  const id = readString(record?.id);
  const channelId = readString(record?.channel_id);
  const sourceChannelId = readString(record?.source_channel_id);
  const deviceId = readString(record?.device_id);
  const controllerUnitId = readPositiveInteger(record?.controller_unit_id);
  const channelNumber = readPositiveInteger(record?.channel_number);
  const logicalSensorNumber = readPositiveInteger(record?.logical_sensor_number);
  const displayName = readString(record?.display_name);
  const physicalSensorCount = readPositiveInteger(record?.physical_sensor_count);
  const metricType = readString(record?.metric_type);
  const unit = readString(record?.unit);
  const status = readString(record?.status);
  if (
    !id ||
    !channelId ||
    !sourceChannelId ||
    !deviceId ||
    controllerUnitId === null ||
    channelNumber === null ||
    logicalSensorNumber === null ||
    !displayName ||
    physicalSensorCount === null ||
    !metricType ||
    !unit ||
    !status
  ) {
    throw invalidResponse();
  }
  return {
    id,
    channelId,
    sourceChannelId,
    deviceId,
    controllerUnitId,
    channelNumber,
    logicalSensorNumber,
    displayName,
    physicalSensorCount,
    physicalSensors: readArray(record?.physical_sensors).map(parsePhysicalSensor),
    metricType,
    unit,
    status,
  };
}

function parsePhysicalSensor(value: unknown): PhysicalSensor {
  const record = asRecord(value);
  const id = readString(record?.id);
  const sensorPosition = record?.sensor_position;
  const inventoryNumber = readString(record?.inventory_number);
  const calibrationStatus = record?.calibration_status;
  const status = readString(record?.status);
  if (
    !id ||
    (sensorPosition !== "A" && sensorPosition !== "B") ||
    !inventoryNumber ||
    (calibrationStatus !== "untracked" && calibrationStatus !== "current" && calibrationStatus !== "due" && calibrationStatus !== "expired") ||
    !status
  ) {
    throw invalidResponse();
  }
  return {
    id,
    sensorPosition,
    inventoryNumber,
    serialNumber: readOptionalString(record?.serial_number),
    calibrationStatus,
    status,
  };
}

function compareChambers(left: ClimateChamber, right: ClimateChamber): number {
  return left.displayOrder - right.displayOrder || left.code.localeCompare(right.code, "uk-UA", { numeric: true });
}

function invalidResponse(): Error {
  return new Error("Сервер повернув некоректний каталог кліматичних камер.");
}

function normalizeBaseUrl(value: string): string {
  const parsed = new URL(value);
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("NEXOLAB API URL must use HTTP or HTTPS.");
  }
  parsed.hash = "";
  parsed.search = "";
  return parsed.toString().replace(/\/$/, "");
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readArray(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw invalidResponse();
  return value;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readOptionalString(value: unknown): string | null {
  return value === null || value === undefined ? null : readString(value);
}

function readPositiveInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 1 ? value : null;
}
