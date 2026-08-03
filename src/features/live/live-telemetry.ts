import type { TelemetryAlarm, TelemetryQuality, TelemetrySample } from "@/lib/telemetry/types";

export const LIVE_SELECTION_LIMIT = 8;
export const LIVE_STALE_AFTER_MS = 30_000;

export type LiveAlarmFilter = "all" | "active" | "none" | TelemetryAlarm;
export type LiveTelemetryState =
  | "live"
  | "stale"
  | "sensor_error"
  | "communication_error"
  | "unknown";

export interface LiveTelemetryFilters {
  search: string;
  nodeId: string;
  equipmentId: string;
  channelId: string;
  metric: string;
  quality: "all" | TelemetryQuality;
  alarm: LiveAlarmFilter;
}

export interface LiveTelemetryFilterOptions {
  nodeIds: string[];
  equipmentIds: string[];
  channelIds: string[];
  metrics: string[];
  qualities: TelemetryQuality[];
}

export interface LiveSelectionResult {
  selected: string[];
  changed: boolean;
  reason: "selected" | "removed" | "limit" | "missing";
}

const DEFAULT_FILTERS: LiveTelemetryFilters = {
  search: "",
  nodeId: "all",
  equipmentId: "all",
  channelId: "all",
  metric: "all",
  quality: "all",
  alarm: "all",
};

function timestamp(value: string | undefined): number {
  if (!value) return Number.NEGATIVE_INFINITY;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
}

function text(value: string): string {
  return value.trim().toLocaleLowerCase("uk-UA");
}

function sortedUnique(values: Iterable<string>): string[] {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right, "uk-UA"));
}

export function defaultLiveTelemetryFilters(): LiveTelemetryFilters {
  return { ...DEFAULT_FILTERS };
}

export function liveChannelKey(sample: TelemetrySample): string {
  return [sample.node_id, sample.equipment_id, sample.channel_id, sample.metric, sample.unit]
    .map((part) => encodeURIComponent(part))
    .join("|");
}

export function compareLiveSamples(left: TelemetrySample, right: TelemetrySample): number {
  return (
    left.node_id.localeCompare(right.node_id, "uk-UA") ||
    left.equipment_id.localeCompare(right.equipment_id, "uk-UA") ||
    left.channel_id.localeCompare(right.channel_id, "uk-UA") ||
    left.metric.localeCompare(right.metric, "uk-UA") ||
    left.unit.localeCompare(right.unit, "uk-UA")
  );
}

export function selectLatestLiveSamples(samples: readonly TelemetrySample[]): TelemetrySample[] {
  const latest = new Map<string, TelemetrySample>();

  for (const sample of samples) {
    const key = liveChannelKey(sample);
    const current = latest.get(key);
    if (!current) {
      latest.set(key, sample);
      continue;
    }

    const capturedDifference = timestamp(sample.captured_at) - timestamp(current.captured_at);
    const receivedDifference = timestamp(sample.received_at) - timestamp(current.received_at);
    if (
      capturedDifference > 0 ||
      (capturedDifference === 0 && receivedDifference > 0) ||
      (capturedDifference === 0 &&
        receivedDifference === 0 &&
        sample.event_id.localeCompare(current.event_id) > 0)
    ) {
      latest.set(key, sample);
    }
  }

  return [...latest.values()].sort(compareLiveSamples);
}

export function liveTelemetryState(
  sample: TelemetrySample,
  now = Date.now(),
  staleAfterMs = LIVE_STALE_AFTER_MS,
): LiveTelemetryState {
  if (sample.quality !== "valid") return sample.quality;
  const capturedAt = timestamp(sample.captured_at);
  if (!Number.isFinite(capturedAt) || now - capturedAt > staleAfterMs) return "stale";
  return "live";
}

export function filterLiveTelemetry(
  samples: readonly TelemetrySample[],
  filters: LiveTelemetryFilters,
): TelemetrySample[] {
  const search = text(filters.search);

  return samples.filter((sample) => {
    if (filters.nodeId !== "all" && sample.node_id !== filters.nodeId) return false;
    if (filters.equipmentId !== "all" && sample.equipment_id !== filters.equipmentId) return false;
    if (filters.channelId !== "all" && sample.channel_id !== filters.channelId) return false;
    if (filters.metric !== "all" && sample.metric !== filters.metric) return false;
    if (filters.quality !== "all" && sample.quality !== filters.quality) return false;
    if (filters.alarm === "active" && sample.alarm === null) return false;
    if (filters.alarm === "none" && sample.alarm !== null) return false;
    if ((filters.alarm === "low" || filters.alarm === "high") && sample.alarm !== filters.alarm) {
      return false;
    }
    if (!search) return true;

    return [
      sample.node_id,
      sample.equipment_id,
      sample.channel_id,
      sample.metric,
      sample.source,
      sample.unit,
      sample.quality,
      sample.alarm ?? "",
    ].some((value) => text(value).includes(search));
  });
}

export function liveTelemetryFilterOptions(
  samples: readonly TelemetrySample[],
): LiveTelemetryFilterOptions {
  return {
    nodeIds: sortedUnique(samples.map((sample) => sample.node_id)),
    equipmentIds: sortedUnique(samples.map((sample) => sample.equipment_id)),
    channelIds: sortedUnique(samples.map((sample) => sample.channel_id)),
    metrics: sortedUnique(samples.map((sample) => sample.metric)),
    qualities: sortedUnique(samples.map((sample) => sample.quality)) as TelemetryQuality[],
  };
}

export function toggleLiveSelection(
  selected: readonly string[],
  key: string,
  availableKeys: ReadonlySet<string>,
  limit = LIVE_SELECTION_LIMIT,
): LiveSelectionResult {
  if (!availableKeys.has(key)) {
    return { selected: [...selected], changed: false, reason: "missing" };
  }
  if (selected.includes(key)) {
    return {
      selected: selected.filter((selectedKey) => selectedKey !== key),
      changed: true,
      reason: "removed",
    };
  }
  if (selected.length >= limit) {
    return { selected: [...selected], changed: false, reason: "limit" };
  }
  return { selected: [...selected, key], changed: true, reason: "selected" };
}

export function reconcileLiveSelection(
  selected: readonly string[],
  samples: readonly TelemetrySample[],
  limit = LIVE_SELECTION_LIMIT,
): string[] {
  const available = new Set(samples.map(liveChannelKey));
  return [...new Set(selected)].filter((key) => available.has(key)).slice(0, limit);
}

export function selectedLiveSamples(
  selected: readonly string[],
  samples: readonly TelemetrySample[],
): TelemetrySample[] {
  const order = new Map(selected.map((key, index) => [key, index]));
  return samples
    .filter((sample) => order.has(liveChannelKey(sample)))
    .sort(
      (left, right) =>
        (order.get(liveChannelKey(left)) ?? Number.MAX_SAFE_INTEGER) -
        (order.get(liveChannelKey(right)) ?? Number.MAX_SAFE_INTEGER),
    );
}

export function groupLiveSamplesByUnit(
  samples: readonly TelemetrySample[],
): Map<string, TelemetrySample[]> {
  const groups = new Map<string, TelemetrySample[]>();
  for (const sample of samples) {
    const current = groups.get(sample.unit) ?? [];
    current.push(sample);
    groups.set(sample.unit, current);
  }
  return new Map(
    [...groups.entries()]
      .sort(([left], [right]) => left.localeCompare(right, "uk-UA"))
      .map(([unit, values]) => [unit, values.sort(compareLiveSamples)]),
  );
}
