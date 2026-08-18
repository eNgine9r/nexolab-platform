import type {
  TelemetryAdapter,
  TelemetryFilters,
  TelemetrySample,
} from "./types";

const DEFAULT_PAGE_SIZE = 1_000;
const DEFAULT_MAX_PAGES = 100;
const MAX_FUTURE_SKEW_MS = 30_000;
const MAX_SEEN_EVENT_IDS = 10_000;

export interface TelemetryHistoryWindow {
  from: Date;
  to: Date;
}

export interface CompleteTelemetryHistoryResult {
  samples: TelemetrySample[];
  snapshotAt: string;
}

export interface TelemetryHistoryLoadOptions {
  signal?: AbortSignal;
  snapshotAt?: string;
  pageSize?: number;
  maxPages?: number;
}

export interface TelemetryHistoryOrderingState {
  newestCapturedAtByIdentity: Map<string, number>;
  seenEventIds: Set<string>;
}

export interface TelemetryHistoryReconciliation {
  samples: TelemetrySample[];
  state: TelemetryHistoryOrderingState;
}

function parsedTimestamp(value: string): number {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

function validateWindow(window: TelemetryHistoryWindow): void {
  const from = window.from.getTime();
  const to = window.to.getTime();
  if (!Number.isFinite(from) || !Number.isFinite(to) || from >= to) {
    throw new Error("Telemetry history window must have a finite positive duration");
  }
}

function orderedUnique(samples: Iterable<TelemetrySample>): TelemetrySample[] {
  const byEventId = new Map<string, TelemetrySample>();
  for (const sample of samples) {
    const capturedAt = parsedTimestamp(sample.captured_at);
    if (!Number.isFinite(capturedAt)) {
      throw new Error(`Telemetry sample ${sample.event_id} has an invalid captured_at timestamp`);
    }
    if (!byEventId.has(sample.event_id)) byEventId.set(sample.event_id, sample);
  }
  return [...byEventId.values()].sort(
    (left, right) =>
      parsedTimestamp(left.captured_at) - parsedTimestamp(right.captured_at) ||
      left.event_id.localeCompare(right.event_id),
  );
}

export function telemetryHistoryIdentityKey(sample: TelemetrySample): string {
  return [sample.node_id, sample.equipment_id, sample.channel_id, sample.metric, sample.unit]
    .map((part) => `${part.length}:${part}`)
    .join("|");
}

export async function loadCompleteTelemetryHistory(
  adapter: TelemetryAdapter,
  filters: TelemetryFilters,
  window: TelemetryHistoryWindow,
  options: TelemetryHistoryLoadOptions = {},
): Promise<CompleteTelemetryHistoryResult> {
  validateWindow(window);
  const pageSize = options.pageSize ?? DEFAULT_PAGE_SIZE;
  const maxPages = options.maxPages ?? DEFAULT_MAX_PAGES;
  if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 1_000) {
    throw new Error("Telemetry history pageSize must be an integer between 1 and 1000");
  }
  if (!Number.isInteger(maxPages) || maxPages < 1) {
    throw new Error("Telemetry history maxPages must be a positive integer");
  }

  const samples = new Map<string, TelemetrySample>();
  let cursorTo = new Date(window.to);
  let snapshotAt = options.snapshotAt;

  for (let page = 0; page < maxPages; page += 1) {
    const response = await adapter.history(
      {
        ...filters,
        from: window.from,
        to: cursorTo,
        snapshot_at: snapshotAt,
        limit: pageSize,
        offset: 0,
      },
      options.signal,
    );

    const responseSnapshotAt = response.snapshot_at;
    if (!responseSnapshotAt || Number.isNaN(Date.parse(responseSnapshotAt))) {
      throw new Error("Telemetry history page did not provide an ingestion snapshot watermark");
    }
    if (snapshotAt === undefined) snapshotAt = responseSnapshotAt;
    if (responseSnapshotAt !== snapshotAt) {
      throw new Error("Telemetry history ingestion snapshot changed during pagination");
    }

    for (const sample of response.items) {
      const capturedAt = parsedTimestamp(sample.captured_at);
      if (!Number.isFinite(capturedAt)) {
        throw new Error(`Telemetry sample ${sample.event_id} has an invalid captured_at timestamp`);
      }
      samples.set(sample.event_id, sample);
    }

    if (response.next_offset === null) {
      return { samples: orderedUnique(samples.values()), snapshotAt };
    }

    const capturedTimes = response.items.map((sample) => parsedTimestamp(sample.captured_at));
    if (capturedTimes.length === 0) {
      throw new Error("Telemetry history page did not provide a stable captured-time cursor");
    }
    const oldestCapturedAt = Math.min(...capturedTimes);
    if (oldestCapturedAt <= window.from.getTime()) {
      return { samples: orderedUnique(samples.values()), snapshotAt };
    }
    if (capturedTimes.filter((capturedAt) => capturedAt === oldestCapturedAt).length >= pageSize) {
      throw new Error("Telemetry history timestamp density exceeds the safe cursor window");
    }

    const currentCursor = cursorTo.getTime();
    const nextCursor = Math.min(oldestCapturedAt + 1, currentCursor - 1);
    if (nextCursor <= window.from.getTime() || nextCursor >= currentCursor) {
      throw new Error("Telemetry history cursor did not advance safely");
    }
    cursorTo = new Date(nextCursor);
  }

  throw new Error("Telemetry history exceeded the supported pagination window");
}

function trimSeenEventIds(seen: Set<string>): void {
  while (seen.size > MAX_SEEN_EVENT_IDS) {
    const oldest = seen.values().next().value as string | undefined;
    if (oldest === undefined) return;
    seen.delete(oldest);
  }
}

export function seedTelemetryHistoryOrderingState(
  samples: readonly TelemetrySample[],
): TelemetryHistoryOrderingState {
  const newestCapturedAtByIdentity = new Map<string, number>();
  const seenEventIds = new Set<string>();
  for (const sample of orderedUnique(samples)) {
    const capturedAt = parsedTimestamp(sample.captured_at);
    const key = telemetryHistoryIdentityKey(sample);
    const newest = newestCapturedAtByIdentity.get(key);
    if (newest === undefined || capturedAt > newest) newestCapturedAtByIdentity.set(key, capturedAt);
    seenEventIds.add(sample.event_id);
    trimSeenEventIds(seenEventIds);
  }
  return { newestCapturedAtByIdentity, seenEventIds };
}

export function reconcileTelemetryHistoryEvents(
  incoming: readonly TelemetrySample[],
  currentState: TelemetryHistoryOrderingState,
  options: { now?: number; allowedChannelIds?: ReadonlySet<string> | null } = {},
): TelemetryHistoryReconciliation {
  const newestCapturedAtByIdentity = new Map(currentState.newestCapturedAtByIdentity);
  const seenEventIds = new Set(currentState.seenEventIds);
  const samples: TelemetrySample[] = [];
  const now = options.now ?? Date.now();

  for (const sample of orderedUnique(incoming)) {
    if (options.allowedChannelIds && !options.allowedChannelIds.has(sample.channel_id)) continue;
    const capturedAt = parsedTimestamp(sample.captured_at);
    if (capturedAt > now + MAX_FUTURE_SKEW_MS || seenEventIds.has(sample.event_id)) continue;
    const key = telemetryHistoryIdentityKey(sample);
    const newest = newestCapturedAtByIdentity.get(key);
    if (newest !== undefined && capturedAt <= newest) continue;

    newestCapturedAtByIdentity.set(key, capturedAt);
    seenEventIds.add(sample.event_id);
    trimSeenEventIds(seenEventIds);
    samples.push(sample);
  }

  return {
    samples,
    state: { newestCapturedAtByIdentity, seenEventIds },
  };
}
