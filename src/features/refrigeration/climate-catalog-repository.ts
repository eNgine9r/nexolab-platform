export type ClimateChamber = {
  id: string;
  code: string;
  /** @deprecated Compatibility alias for id in legacy chamber selectors. */
  nodeId: string;
  /** Physical telemetry source, currently edge-01 for both chambers. */
  transportNodeId: string;
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
  version: number;
};

export type PhysicalSensor = {
  id: string;
  sensorPosition: "A" | "B";
  inventoryNumber: string;
  serialNumber: string | null;
  calibrationStatus: "untracked" | "current" | "due" | "expired";
  status: string;
  version: number;
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

export type MeasurementDeviceMetadataUpdate = {
  displayName: string;
  designation: string | null;
  manufacturer: string;
  model: string;
};

export type PhysicalSensorMetadataUpdate = {
  inventoryNumber: string;
  serialNumber: string | null;
  calibrationStatus: PhysicalSensor["calibrationStatus"];
};

export interface ClimateCatalogRepository {
  listChambers(): Promise<ClimateChamber[]>;
  getEquipment(chamberId: string): Promise<ClimateChamberEquipment>;
  updateMeasurementDevice(
    chamberId: string,
    deviceId: string,
    input: MeasurementDeviceMetadataUpdate,
    expectedVersion: number,
  ): Promise<MeasurementDevice>;
  updatePhysicalSensor(
    chamberId: string,
    sensorId: string,
    input: PhysicalSensorMetadataUpdate,
    expectedVersion: number,
  ): Promise<PhysicalSensor>;
}

export class ClimateCatalogRepositoryError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number | null = null,
  ) {
    super(message);
    this.name = "ClimateCatalogRepositoryError";
  }
}

export class HttpClimateCatalogRepository implements ClimateCatalogRepository {
  private readonly apiBaseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: { apiBaseUrl: string; fetchImpl?: typeof fetch }) {
    this.apiBaseUrl = normalizeBaseUrl(options.apiBaseUrl);
    this.fetchImpl = options.fetchImpl ?? fetch.bind(globalThis);
  }

  async listChambers(): Promise<ClimateChamber[]> {
    const payload = asRecord(await this.request("/api/v1/climate-chambers", { method: "GET" }));
    if (!payload || !Array.isArray(payload.items)) throw invalidResponse();
    return payload.items.map(parseChamber).sort(compareChambers);
  }

  async getEquipment(chamberId: string): Promise<ClimateChamberEquipment> {
    const payload = asRecord(
      await this.request(`/api/v1/climate-chambers/${encodeURIComponent(chamberId)}/equipment`, {
        method: "GET",
      }),
    );
    if (!payload) throw invalidResponse();
    const chamber = parseChamber(payload.climateChamber ?? payload.climate_chamber);
    const controllers = readArray(payload.temperatureControllers ?? payload.temperature_controllers).map(
      parseDevice,
    );
    const channels = readArray(payload.temperatureChannels ?? payload.temperature_channels).map(parseChannel);
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

  async updateMeasurementDevice(
    chamberId: string,
    deviceId: string,
    input: MeasurementDeviceMetadataUpdate,
    expectedVersion: number,
  ): Promise<MeasurementDevice> {
    const payload = await this.request(
      `/api/v1/climate-chambers/${encodeURIComponent(chamberId)}/measurement-devices/${encodeURIComponent(deviceId)}`,
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "If-Match": `W/"measurement-device-v${expectedVersion}"`,
          "X-Audit-Reason": "Updated measurement device administrative metadata",
        },
        body: JSON.stringify({
          display_name: input.displayName,
          designation: input.designation,
          manufacturer: input.manufacturer,
          model: input.model,
        }),
      },
    );
    return parseDevice(payload);
  }

  async updatePhysicalSensor(
    chamberId: string,
    sensorId: string,
    input: PhysicalSensorMetadataUpdate,
    expectedVersion: number,
  ): Promise<PhysicalSensor> {
    const payload = await this.request(
      `/api/v1/climate-chambers/${encodeURIComponent(chamberId)}/physical-sensors/${encodeURIComponent(sensorId)}`,
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "If-Match": `W/"physical-sensor-v${expectedVersion}"`,
          "X-Audit-Reason": "Updated physical sensor administrative metadata",
        },
        body: JSON.stringify({
          inventory_number: input.inventoryNumber,
          serial_number: input.serialNumber,
          calibration_status: input.calibrationStatus,
        }),
      },
    );
    return parsePhysicalSensor(payload);
  }

  private async request(path: string, init: RequestInit): Promise<unknown> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.apiBaseUrl}${path}`, {
        ...init,
        credentials: init.credentials ?? "same-origin",
        headers: { Accept: "application/json", ...init.headers },
      });
    } catch {
      throw new ClimateCatalogRepositoryError(
        "Не вдалося з’єднатися з каталогом кліматичних камер.",
        "request_failed",
      );
    }
    const payload = await readJson(response);
    if (!response.ok) {
      const detail = asRecord(asRecord(payload)?.detail);
      throw new ClimateCatalogRepositoryError(
        readString(detail?.message) ?? "Каталог кліматичних камер недоступний.",
        readString(detail?.code) ?? "request_failed",
        response.status,
      );
    }
    return payload;
  }
}

function parseChamber(value: unknown): ClimateChamber {
  const record = asRecord(value);
  const id = readString(record?.id);
  const code = readString(record?.code);
  const transportNodeId = readString(record?.node_id);
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
    !transportNodeId ||
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
  return {
    id,
    code,
    nodeId: id,
    transportNodeId,
    busId,
    busKey,
    name,
    displayOrder,
    status,
    version,
    createdAt,
    updatedAt,
  };
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
  const version = readPositiveInteger(record?.version);
  if (
    !id ||
    !businessKey ||
    (deviceType !== "temperature_controller" && deviceType !== "energy_meter") ||
    !manufacturer ||
    !model ||
    unitId === null ||
    !displayName ||
    (connectionStatus !== "unknown" &&
      connectionStatus !== "connected" &&
      connectionStatus !== "disconnected") ||
    !status ||
    version === null
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
    version,
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
  const version = readPositiveInteger(record?.version);
  if (
    !id ||
    (sensorPosition !== "A" && sensorPosition !== "B") ||
    !inventoryNumber ||
    (calibrationStatus !== "untracked" &&
      calibrationStatus !== "current" &&
      calibrationStatus !== "due" &&
      calibrationStatus !== "expired") ||
    !status ||
    version === null
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
    version,
  };
}

function compareChambers(left: ClimateChamber, right: ClimateChamber): number {
  return (
    left.displayOrder - right.displayOrder || left.code.localeCompare(right.code, "uk-UA", { numeric: true })
  );
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
