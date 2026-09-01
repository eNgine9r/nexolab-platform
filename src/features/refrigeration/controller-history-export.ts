import type { TelemetrySample } from "@/lib/telemetry/types";

import type { CompressorRuntimeDuty, CompressorStartEvent } from "./compressor-runtime";
import { decodeRelayBits, EMBRACO_METRICS } from "./controller-monitoring";
import type { RelayTransition } from "./controller-timeline";

export type ControllerAnalysisExportRange = { fromMs: number; toMs: number };

export type ControllerAnalysisCsvInput = {
  history: ReadonlyMap<string, readonly TelemetrySample[]>;
  range: ControllerAnalysisExportRange;
  duty: CompressorRuntimeDuty;
  compressorStarts: readonly CompressorStartEvent[];
  relayTransitions: readonly RelayTransition[];
  equipmentId: string;
  timeZone: string;
};

type CsvRow = {
  selected_from_utc: string;
  selected_to_utc: string;
  timestamp_utc: string;
  timestamp_local: string;
  record_type: string;
  signal: string;
  state: string;
  value: string;
  unit: string;
  quality: string;
  equipment_id: string;
  channel_id: string;
  event_id: string;
  source: string;
  raw_value: string;
  raw_status: string;
  previous_timestamp_utc: string;
  previous_event_id: string;
  note: string;
};

const HEADERS: readonly (keyof CsvRow)[] = [
  "selected_from_utc",
  "selected_to_utc",
  "timestamp_utc",
  "timestamp_local",
  "record_type",
  "signal",
  "state",
  "value",
  "unit",
  "quality",
  "equipment_id",
  "channel_id",
  "event_id",
  "source",
  "raw_value",
  "raw_status",
  "previous_timestamp_utc",
  "previous_event_id",
  "note",
];

const EXPORTED_TELEMETRY_METRICS = [
  EMBRACO_METRICS.compressorSpeed,
  EMBRACO_METRICS.controlState,
  EMBRACO_METRICS.relays,
  EMBRACO_METRICS.alarms,
] as const;

export function buildControllerAnalysisCsv(input: ControllerAnalysisCsvInput): string {
  validateRange(input.range);
  const selectedFromUtc = new Date(input.range.fromMs).toISOString();
  const selectedToUtc = new Date(input.range.toMs).toISOString();
  const base = { selected_from_utc: selectedFromUtc, selected_to_utc: selectedToUtc };
  const rows: CsvRow[] = [
    summaryRow(base, input, "compressor.runtime_duty", input.duty.dutyPercent, "%"),
    summaryRow(base, input, "compressor.running_seconds", input.duty.runningMs / 1000, "s"),
    summaryRow(base, input, "compressor.coverage", input.duty.coveragePercent, "%"),
    summaryRow(base, input, "compressor.start_count", input.compressorStarts.length, "count"),
  ];

  const eventLookup = new Map<string, TelemetrySample>();
  for (const metric of EXPORTED_TELEMETRY_METRICS) {
    for (const sample of input.history.get(metric) ?? []) {
      eventLookup.set(sample.event_id, sample);
      const capturedAtMs = Date.parse(sample.captured_at);
      if (!Number.isFinite(capturedAtMs)) continue;
      if (capturedAtMs < input.range.fromMs || capturedAtMs > input.range.toMs) continue;
      rows.push(telemetryRow(base, sample, input.timeZone));
    }
  }

  for (const start of input.compressorStarts) {
    const sample = start.eventId ? eventLookup.get(start.eventId) : undefined;
    rows.push({
      ...emptyRow(base),
      timestamp_utc: new Date(start.observedAtMs).toISOString(),
      timestamp_local: localTimestamp(start.observedAtMs, input.timeZone),
      record_type: "compressor_start",
      signal: "compressor.start",
      state: "START",
      value: String(start.valueRpm),
      unit: "rpm",
      quality: "valid",
      equipment_id: sample?.equipment_id ?? input.equipmentId,
      channel_id: sample?.channel_id ?? "",
      event_id: start.eventId ?? "",
      source: sample?.source ?? "",
      previous_timestamp_utc: new Date(start.previousObservedAtMs).toISOString(),
      previous_event_id: start.previousEventId ?? "",
      note: "Пуск зафіксовано як валідний перехід RPM=0 → RPM>0; час є першим sample нового стану.",
    });
  }

  for (const transition of input.relayTransitions) {
    const sample = eventLookup.get(transition.eventId);
    rows.push({
      ...emptyRow(base),
      timestamp_utc: new Date(transition.observedAtMs).toISOString(),
      timestamp_local: localTimestamp(transition.observedAtMs, input.timeZone),
      record_type: "relay_transition",
      signal: `relay.${transition.relayIndex + 1}`,
      state: transition.toState ? "ON" : "OFF",
      value: transition.toState ? "1" : "0",
      unit: "state",
      quality: "valid",
      equipment_id: sample?.equipment_id ?? input.equipmentId,
      channel_id: sample?.channel_id ?? "",
      event_id: transition.eventId,
      source: sample?.source ?? "",
      previous_timestamp_utc: new Date(transition.previousObservedAtMs).toISOString(),
      previous_event_id: transition.previousEventId,
      note: `Observed ${transition.fromState ? "ON" : "OFF"} → ${transition.toState ? "ON" : "OFF"}; physical switching occurred between adjacent polls.`,
    });
  }

  const summaryRows = rows.slice(0, 4);
  const timeRows = rows
    .slice(4)
    .sort(
      (left, right) =>
        left.timestamp_utc.localeCompare(right.timestamp_utc) ||
        left.record_type.localeCompare(right.record_type),
    );
  return `\uFEFF${HEADERS.join(",")}\r\n${[...summaryRows, ...timeRows]
    .map((row) => HEADERS.map((header) => csvCell(row[header])).join(","))
    .join("\r\n")}\r\n`;
}

export function controllerAnalysisCsvFilename(
  equipmentId: string,
  range: ControllerAnalysisExportRange,
): string {
  validateRange(range);
  const safeEquipment = equipmentId.replace(/[^A-Za-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "") || "controller";
  const compact = (value: number) =>
    new Date(value)
      .toISOString()
      .replace(/[-:]/g, "")
      .replace(/\.\d{3}Z$/, "Z");
  return `nexolab-${safeEquipment}-${compact(range.fromMs)}-${compact(range.toMs)}.csv`;
}

function telemetryRow(
  base: Pick<CsvRow, "selected_from_utc" | "selected_to_utc">,
  sample: TelemetrySample,
  timeZone: string,
): CsvRow {
  const capturedAtMs = Date.parse(sample.captured_at);
  return {
    ...emptyRow(base),
    timestamp_utc: new Date(capturedAtMs).toISOString(),
    timestamp_local: localTimestamp(capturedAtMs, timeZone),
    record_type: "telemetry",
    signal: sample.metric,
    state: telemetryState(sample),
    value: sample.value === null ? "" : String(sample.value),
    unit: sample.unit,
    quality: sample.quality,
    equipment_id: sample.equipment_id,
    channel_id: sample.channel_id,
    event_id: sample.event_id,
    source: sample.source,
    raw_value: sample.raw_value === null ? "" : String(sample.raw_value),
    raw_status: sample.raw_status === null ? "" : String(sample.raw_status),
    note: sample.metric === EMBRACO_METRICS.relays ? "Decoded relay states are included in state." : "",
  };
}

function telemetryState(sample: TelemetrySample): string {
  if (sample.quality !== "valid" || sample.value === null || !Number.isFinite(sample.value)) return "";
  if (sample.metric === EMBRACO_METRICS.compressorSpeed) return sample.value > 0 ? "RUNNING" : "STOPPED";
  if (sample.metric === EMBRACO_METRICS.relays) {
    return decodeRelayBits(Math.trunc(sample.value))
      .map((state, index) => `Relay ${index + 1}=${state ? "ON" : "OFF"}`)
      .join(" | ");
  }
  return "";
}

function summaryRow(
  base: Pick<CsvRow, "selected_from_utc" | "selected_to_utc">,
  input: ControllerAnalysisCsvInput,
  signal: string,
  value: number | null,
  unit: string,
): CsvRow {
  return {
    ...emptyRow(base),
    record_type: "analysis_summary",
    signal,
    value: value === null ? "" : String(value),
    unit,
    quality: input.duty.status === "available" ? "valid" : "unknown",
    equipment_id: input.equipmentId,
  };
}

function emptyRow(base: Pick<CsvRow, "selected_from_utc" | "selected_to_utc">): CsvRow {
  return {
    ...base,
    timestamp_utc: "",
    timestamp_local: "",
    record_type: "",
    signal: "",
    state: "",
    value: "",
    unit: "",
    quality: "",
    equipment_id: "",
    channel_id: "",
    event_id: "",
    source: "",
    raw_value: "",
    raw_status: "",
    previous_timestamp_utc: "",
    previous_event_id: "",
    note: "",
  };
}

function localTimestamp(timestampMs: number, timeZone: string): string {
  try {
    return new Intl.DateTimeFormat("uk-UA", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    }).format(new Date(timestampMs));
  } catch {
    return new Date(timestampMs).toISOString();
  }
}

function csvCell(value: string): string {
  const spreadsheetSafeValue = formulaNeutralizedCell(value);
  return /[",\r\n]/.test(spreadsheetSafeValue)
    ? `"${spreadsheetSafeValue.replaceAll('"', '""')}"`
    : spreadsheetSafeValue;
}

function formulaNeutralizedCell(value: string): string {
  if (!/^[=+\-@]/.test(value)) return value;
  if (/^[+\-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+\-]?\d+)?$/.test(value)) return value;
  return `'${value}`;
}

function validateRange(range: ControllerAnalysisExportRange): void {
  if (!Number.isFinite(range.fromMs) || !Number.isFinite(range.toMs) || range.toMs <= range.fromMs) {
    throw new Error("Controller analysis export range must be a valid positive interval");
  }
}
