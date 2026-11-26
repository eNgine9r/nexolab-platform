import { TelemetryClientError } from "./errors";

/**
 * #1811/#1813: client contract for `GET /api/v1/telemetry/history/aggregate`.
 *
 * Extremum-preserving history for up to 24 series per request. The endpoint exists only on
 * backends that include #1811; older backends answer 404 and callers fall back to raw pages.
 */
export interface HistorySeriesKey {
  node_id: string;
  equipment_id: string;
  channel_id: string;
  metric: string;
}

export interface HistoryAggregateQuery {
  from: Date;
  to: Date;
  series: readonly HistorySeriesKey[];
  buckets: number;
  snapshot_at?: string;
  statistics?: boolean;
}

/** [captured_ms, value, quality, alarm, event_id] */
export type HistoryAggregateRawRow = [number, number | null, string, string | null, string];

export interface HistoryAggregateBucket {
  index: number;
  count: number;
  validCount: number;
  invalidCount: number;
  firstInvalidMs: number | null;
  lastInvalidMs: number | null;
  first: [number, number] | null;
  last: [number, number] | null;
  minimum: [number, number] | null;
  maximum: [number, number] | null;
}

export interface HistoryIntervalStatisticsWire {
  valid_count: number;
  invalid_count: number;
  minimum: number | null;
  maximum: number | null;
  valid_sum: number;
  first_valid_ms: number | null;
  last_valid_ms: number | null;
  median_spacing_ms: number | null;
  gap_count: number;
  gap_total_ms: number;
  gap_longest_ms: number;
}

export interface HistoryAggregateSeries extends HistorySeriesKey {
  unit: string | null;
  mode: "raw" | "aggregate";
  count: number;
  validCount: number;
  raw: HistoryAggregateRawRow[];
  buckets: HistoryAggregateBucket[];
  statistics: HistoryIntervalStatisticsWire | null;
}

export interface HistoryAggregateResponse {
  fromMs: number;
  toMs: number;
  bucketMs: number;
  snapshotAt: string;
  series: HistoryAggregateSeries[];
}

export const AGGREGATE_SERIES_PER_REQUEST = 4;

function fail(path: string, detail: string): never {
  throw new TelemetryClientError("contract", `Invalid aggregated history at ${path}: ${detail}`);
}

function record(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail(path, "expected an object");
  return value as Record<string, unknown>;
}

function finite(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) fail(path, "expected a finite number");
  return value;
}

function nullableFinite(value: unknown, path: string): number | null {
  return value === null || value === undefined ? null : finite(value, path);
}

function text(value: unknown, path: string): string {
  if (typeof value !== "string" || value.length === 0) fail(path, "expected a non-empty string");
  return value;
}

function pair(ms: unknown, value: unknown, path: string): [number, number] | null {
  if (ms === null || value === null) return null;
  return [finite(ms, `${path}.ms`), finite(value, `${path}.value`)];
}

function parseStatistics(value: unknown, path: string): HistoryIntervalStatisticsWire | null {
  if (value === null || value === undefined) return null;
  const item = record(value, path);
  return {
    valid_count: finite(item.valid_count, `${path}.valid_count`),
    invalid_count: finite(item.invalid_count, `${path}.invalid_count`),
    minimum: nullableFinite(item.minimum, `${path}.minimum`),
    maximum: nullableFinite(item.maximum, `${path}.maximum`),
    valid_sum: finite(item.valid_sum, `${path}.valid_sum`),
    first_valid_ms: nullableFinite(item.first_valid_ms, `${path}.first_valid_ms`),
    last_valid_ms: nullableFinite(item.last_valid_ms, `${path}.last_valid_ms`),
    median_spacing_ms: nullableFinite(item.median_spacing_ms, `${path}.median_spacing_ms`),
    gap_count: finite(item.gap_count, `${path}.gap_count`),
    gap_total_ms: finite(item.gap_total_ms, `${path}.gap_total_ms`),
    gap_longest_ms: finite(item.gap_longest_ms, `${path}.gap_longest_ms`),
  };
}

export function parseHistoryAggregate(value: unknown): HistoryAggregateResponse {
  const body = record(value, "response");
  if (!Array.isArray(body.series)) fail("series", "expected an array");
  return {
    fromMs: finite(body.from_ms, "from_ms"),
    toMs: finite(body.to_ms, "to_ms"),
    bucketMs: finite(body.bucket_ms, "bucket_ms"),
    snapshotAt: text(body.snapshot_at, "snapshot_at"),
    series: body.series.map((entry, index) => {
      const path = `series[${index}]`;
      const item = record(entry, path);
      const mode = item.mode;
      if (mode !== "raw" && mode !== "aggregate") fail(`${path}.mode`, "expected raw or aggregate");
      const raw = Array.isArray(item.raw) ? item.raw : [];
      const buckets = Array.isArray(item.buckets) ? item.buckets : [];
      return {
        node_id: text(item.node_id, `${path}.node_id`),
        equipment_id: text(item.equipment_id, `${path}.equipment_id`),
        channel_id: text(item.channel_id, `${path}.channel_id`),
        metric: text(item.metric, `${path}.metric`),
        unit: typeof item.unit === "string" ? item.unit : null,
        mode,
        count: finite(item.count, `${path}.count`),
        validCount: finite(item.valid_count, `${path}.valid_count`),
        raw: raw.map((row, rowIndex) => {
          const rowPath = `${path}.raw[${rowIndex}]`;
          if (!Array.isArray(row) || row.length !== 5) fail(rowPath, "expected a 5-tuple");
          return [
            finite(row[0], `${rowPath}[0]`),
            nullableFinite(row[1], `${rowPath}[1]`),
            text(row[2], `${rowPath}[2]`),
            typeof row[3] === "string" ? row[3] : null,
            text(row[4], `${rowPath}[4]`),
          ] satisfies HistoryAggregateRawRow;
        }),
        buckets: buckets.map((row, rowIndex) => {
          const rowPath = `${path}.buckets[${rowIndex}]`;
          if (!Array.isArray(row) || row.length !== 15) fail(rowPath, "expected 15 columns");
          return {
            index: finite(row[0], `${rowPath}.index`),
            count: finite(row[1], `${rowPath}.count`),
            validCount: finite(row[2], `${rowPath}.valid`),
            invalidCount: finite(row[3], `${rowPath}.invalid`),
            firstInvalidMs: nullableFinite(row[4], `${rowPath}.first_invalid`),
            lastInvalidMs: nullableFinite(row[5], `${rowPath}.last_invalid`),
            first: pair(row[6], row[7], `${rowPath}.first`),
            last: pair(row[8], row[9], `${rowPath}.last`),
            minimum: pair(row[10], row[11], `${rowPath}.min`),
            maximum: pair(row[12], row[13], `${rowPath}.max`),
          };
        }),
        statistics: parseStatistics(item.statistics, `${path}.statistics`),
      };
    }),
  };
}

export function seriesKeyParameter(key: HistorySeriesKey): string {
  return [key.node_id, key.equipment_id, key.channel_id, key.metric].join("|");
}

/** True when the backend predates the aggregate endpoint (#1811): use raw pages instead. */
export function isAggregateUnsupported(error: unknown): boolean {
  return (
    error instanceof TelemetryClientError &&
    error.code === "http" &&
    (error.status === 404 || error.status === 405)
  );
}
