import {
  TELEMETRY_ALARMS,
  TELEMETRY_QUALITIES,
  type TelemetryAlarm,
  type TelemetryCollection,
  type TelemetryEvent,
  type TelemetryHeartbeat,
  type TelemetryQuality,
  type TelemetrySample,
} from "./types";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const TIMEZONE_PATTERN = /(Z|[+-]\d{2}:\d{2})$/;

export class TelemetryPayloadError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TelemetryPayloadError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredString(
  record: Record<string, unknown>,
  field: string,
  options: { uuid?: boolean; timestamp?: boolean } = {},
): string {
  const value = record[field];
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new TelemetryPayloadError(`${field} must be a non-empty string`);
  }
  if (options.uuid && !UUID_PATTERN.test(value)) {
    throw new TelemetryPayloadError(`${field} must be a UUID`);
  }
  if (options.timestamp && (!TIMEZONE_PATTERN.test(value) || Number.isNaN(Date.parse(value)))) {
    throw new TelemetryPayloadError(`${field} must be a timezone-aware timestamp`);
  }
  return value;
}

function nullableFiniteNumber(record: Record<string, unknown>, field: string): number | null {
  const value = record[field];
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new TelemetryPayloadError(`${field} must be a finite number or null`);
  }
  return value;
}

function enumValue<T extends string>(
  record: Record<string, unknown>,
  field: string,
  allowed: readonly T[],
): T {
  const value = record[field];
  if (typeof value !== "string" || !allowed.includes(value as T)) {
    throw new TelemetryPayloadError(`${field} has an unsupported value`);
  }
  return value as T;
}

function nullableAlarm(record: Record<string, unknown>): TelemetryAlarm | null {
  if (record.alarm === null) return null;
  return enumValue(record, "alarm", TELEMETRY_ALARMS);
}

function nonNegativeInteger(record: Record<string, unknown>, field: string): number {
  const value = record[field];
  if (!Number.isInteger(value) || (value as number) < 0) {
    throw new TelemetryPayloadError(`${field} must be a non-negative integer`);
  }
  return value as number;
}

export function parseTelemetryEvent(input: unknown): TelemetryEvent {
  if (!isRecord(input)) {
    throw new TelemetryPayloadError("telemetry payload must be an object");
  }

  const quality = enumValue<TelemetryQuality>(input, "quality", TELEMETRY_QUALITIES);
  const value = nullableFiniteNumber(input, "value");
  if (quality === "valid" && value === null) {
    throw new TelemetryPayloadError("valid telemetry requires a numeric value");
  }

  return {
    event_id: requiredString(input, "event_id", { uuid: true }),
    node_id: requiredString(input, "node_id"),
    captured_at: requiredString(input, "captured_at", { timestamp: true }),
    metric: requiredString(input, "metric"),
    value,
    unit: requiredString(input, "unit"),
    quality,
    source: requiredString(input, "source"),
    equipment_id: requiredString(input, "equipment_id"),
    channel_id: requiredString(input, "channel_id"),
    alarm: nullableAlarm(input),
    raw_value: nullableFiniteNumber(input, "raw_value"),
    raw_status: nullableFiniteNumber(input, "raw_status"),
  };
}

export function parseTelemetrySample(input: unknown): TelemetrySample {
  if (!isRecord(input)) {
    throw new TelemetryPayloadError("telemetry sample must be an object");
  }
  return {
    ...parseTelemetryEvent(input),
    received_at: requiredString(input, "received_at", { timestamp: true }),
  };
}

export function parseTelemetryCollection(input: unknown): TelemetryCollection {
  if (!isRecord(input) || !Array.isArray(input.items)) {
    throw new TelemetryPayloadError("telemetry collection has an invalid shape");
  }

  const nextOffset = input.next_offset;
  if (
    nextOffset !== null &&
    (typeof nextOffset !== "number" || !Number.isInteger(nextOffset) || nextOffset < 0)
  ) {
    throw new TelemetryPayloadError("next_offset must be a non-negative integer or null");
  }

  return {
    items: input.items.map(parseTelemetrySample),
    count: nonNegativeInteger(input, "count"),
    limit: nonNegativeInteger(input, "limit"),
    offset: nonNegativeInteger(input, "offset"),
    next_offset: nextOffset,
  };
}

export function parseHeartbeat(input: unknown): TelemetryHeartbeat {
  if (!isRecord(input) || input.type !== "heartbeat") {
    throw new TelemetryPayloadError("message is not a telemetry heartbeat");
  }
  return {
    type: "heartbeat",
    server_time: requiredString(input, "server_time", { timestamp: true }),
  };
}

export function isHeartbeat(input: unknown): input is TelemetryHeartbeat {
  return isRecord(input) && input.type === "heartbeat";
}
