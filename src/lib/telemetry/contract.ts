import { TelemetryClientError } from "./errors";
import type {
  TelemetryAlarm,
  TelemetryCollectionResponse,
  TelemetryQuality,
  TelemetryReadinessResponse,
  TelemetrySample,
} from "./types";

const QUALITIES: readonly TelemetryQuality[] = [
  "valid",
  "sensor_error",
  "communication_error",
  "unknown",
];
const ALARMS: readonly TelemetryAlarm[] = ["low", "high"];

export type ParsedTelemetryLiveMessage =
  | { kind: "sample"; sample: TelemetrySample }
  | { kind: "heartbeat"; serverTime: string }
  | { kind: "error"; detail: string };

function fail(path: string, detail: string): never {
  throw new TelemetryClientError(
    "contract",
    `Invalid telemetry response at ${path}: ${detail}`,
  );
}

function asRecord(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    fail(path, "expected an object");
  }
  return value as Record<string, unknown>;
}

function asString(value: unknown, path: string): string {
  if (typeof value !== "string" || value.length === 0) {
    fail(path, "expected a non-empty string");
  }
  return value;
}

function asNullableString(value: unknown, path: string): string | null {
  if (value === null) {
    return null;
  }
  return asString(value, path);
}

function asNumber(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    fail(path, "expected a finite number");
  }
  return value;
}

function asInteger(value: unknown, path: string): number {
  const parsed = asNumber(value, path);
  if (!Number.isInteger(parsed) || parsed < 0) {
    fail(path, "expected a non-negative integer");
  }
  return parsed;
}

function asNullableNumber(value: unknown, path: string): number | null {
  if (value === null) {
    return null;
  }
  return asNumber(value, path);
}

function asTimestamp(value: unknown, path: string): string {
  const parsed = asString(value, path);
  if (Number.isNaN(Date.parse(parsed))) {
    fail(path, "expected an ISO timestamp");
  }
  return parsed;
}

function asNullableTimestamp(value: unknown, path: string): string | null {
  if (value === null) {
    return null;
  }
  return asTimestamp(value, path);
}

function asEnum<T extends string>(
  value: unknown,
  allowed: readonly T[],
  path: string,
): T {
  if (typeof value !== "string" || !allowed.includes(value as T)) {
    fail(path, `expected one of ${allowed.join(", ")}`);
  }
  return value as T;
}

function asNullableEnum<T extends string>(
  value: unknown,
  allowed: readonly T[],
  path: string,
): T | null {
  if (value === null) {
    return null;
  }
  return asEnum(value, allowed, path);
}

export function parseTelemetrySample(
  value: unknown,
  path = "sample",
): TelemetrySample {
  const record = asRecord(value, path);
  const receivedAt = record.received_at;

  return {
    event_id: asString(record.event_id, `${path}.event_id`),
    node_id: asString(record.node_id, `${path}.node_id`),
    captured_at: asTimestamp(record.captured_at, `${path}.captured_at`),
    metric: asString(record.metric, `${path}.metric`),
    value: asNullableNumber(record.value, `${path}.value`),
    unit: asString(record.unit, `${path}.unit`),
    quality: asEnum(record.quality, QUALITIES, `${path}.quality`),
    source: asString(record.source, `${path}.source`),
    equipment_id: asString(record.equipment_id, `${path}.equipment_id`),
    channel_id: asString(record.channel_id, `${path}.channel_id`),
    alarm: asNullableEnum(record.alarm, ALARMS, `${path}.alarm`),
    raw_value: asNullableNumber(record.raw_value, `${path}.raw_value`),
    raw_status: asNullableNumber(record.raw_status, `${path}.raw_status`),
    ...(receivedAt === undefined
      ? {}
      : { received_at: asTimestamp(receivedAt, `${path}.received_at`) }),
  };
}

export function parseTelemetryCollection(
  value: unknown,
): TelemetryCollectionResponse {
  const record = asRecord(value, "collection");
  if (!Array.isArray(record.items)) {
    fail("collection.items", "expected an array");
  }

  const nextOffset = record.next_offset;
  return {
    items: record.items.map((item, index) =>
      parseTelemetrySample(item, `collection.items[${index}]`),
    ),
    count: asInteger(record.count, "collection.count"),
    limit: asInteger(record.limit, "collection.limit"),
    offset: asInteger(record.offset, "collection.offset"),
    next_offset:
      nextOffset === null
        ? null
        : asInteger(nextOffset, "collection.next_offset"),
  };
}

export function parseTelemetryReadiness(
  value: unknown,
): TelemetryReadinessResponse {
  const record = asRecord(value, "readiness");
  return {
    status: asEnum(record.status, ["ready", "not_ready"], "readiness.status"),
    database: asEnum(
      record.database,
      ["ready", "not_ready"],
      "readiness.database",
    ),
    mqtt: asEnum(record.mqtt, ["ready", "not_ready"], "readiness.mqtt"),
    queue_size: asInteger(record.queue_size, "readiness.queue_size"),
    websocket_clients: asInteger(
      record.websocket_clients,
      "readiness.websocket_clients",
    ),
    database_outage_since: asNullableTimestamp(
      record.database_outage_since,
      "readiness.database_outage_since",
    ),
    last_persisted_at: asNullableTimestamp(
      record.last_persisted_at,
      "readiness.last_persisted_at",
    ),
    ingestion_lag_seconds: asNullableNumber(
      record.ingestion_lag_seconds,
      "readiness.ingestion_lag_seconds",
    ),
    mqtt_error: asNullableString(record.mqtt_error, "readiness.mqtt_error"),
    database_error: asNullableString(
      record.database_error,
      "readiness.database_error",
    ),
    last_error: asNullableString(record.last_error, "readiness.last_error"),
  };
}

export function parseTelemetryLiveMessage(
  value: unknown,
): ParsedTelemetryLiveMessage {
  const record = asRecord(value, "live");
  if (record.type === "heartbeat") {
    return {
      kind: "heartbeat",
      serverTime: asTimestamp(record.server_time, "live.server_time"),
    };
  }
  if (record.type === "error") {
    return {
      kind: "error",
      detail: asString(record.detail, "live.detail"),
    };
  }

  return {
    kind: "sample",
    sample: parseTelemetrySample(record, "live.sample"),
  };
}
