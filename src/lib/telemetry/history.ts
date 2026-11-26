import { TelemetryClientError } from "./errors";
import type {
  TelemetryAdapter,
  TelemetryCollectionResponse,
  TelemetryFilters,
  TelemetryHistoryQuery,
  TelemetrySample,
} from "./types";

const DEFAULT_PAGE_SIZE = 1_000;
const DEFAULT_MAX_PAGES = 500;
const MAX_FUTURE_SKEW_MS = 30_000;
const MAX_SEEN_EVENT_IDS = 10_000;
/**
 * #1809: one timed-out or overloaded page (503 from the bounded history pool, #1807) is retried
 * under the same ingestion snapshot instead of failing the whole chart. The request timeout itself
 * is not raised.
 */
export const HISTORY_PAGE_RETRY_DELAYS_MS: readonly number[] = [500, 1_500];
const RETRYABLE_HTTP_STATUSES = new Set([429, 502, 503, 504]);

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
  /** Delays before each retry of a retryable page failure; `[]` disables retries. */
  retryDelaysMs?: readonly number[];
  /** Called once, as soon as the first page has fixed the ingestion snapshot watermark. */
  onSnapshot?: (snapshotAt: string) => void;
}

export function isRetryableHistoryError(error: unknown): boolean {
  if (!(error instanceof TelemetryClientError)) return false;
  if (error.code === "timeout" || error.code === "network") return true;
  return error.code === "http" && RETRYABLE_HTTP_STATUSES.has(error.status ?? 0);
}

/**
 * Operator-facing explanation of a failed history load (#1809). Timeouts and overload keep the
 * technical detail for diagnosis but say what happened and that retrying is safe.
 */
export function describeHistoryLoadError(error: Error | null | undefined): string {
  if (!error) return "Невідома помилка завантаження історії.";
  if (isRetryableHistoryError(error)) {
    return `Сервер історії не відповів вчасно або перевантажений; повтори не допомогли. Дані не втрачено — повторіть завантаження. (${error.message})`;
  }
  return error.message;
}

function abortError(): TelemetryClientError {
  return new TelemetryClientError("aborted", "Telemetry request was aborted");
}

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return Promise.reject(abortError());
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer);
      reject(abortError());
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/** One history page with bounded retries for timeouts, network errors and overload statuses. */
export async function fetchHistoryPageWithRetry(
  adapter: TelemetryAdapter,
  query: TelemetryHistoryQuery,
  signal?: AbortSignal,
  retryDelaysMs: readonly number[] = HISTORY_PAGE_RETRY_DELAYS_MS,
): Promise<TelemetryCollectionResponse> {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await adapter.history(query, signal);
    } catch (error) {
      if (signal?.aborted || attempt >= retryDelaysMs.length || !isRetryableHistoryError(error)) throw error;
      await wait(retryDelaysMs[attempt], signal);
    }
  }
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
    const response = await fetchHistoryPageWithRetry(
      adapter,
      {
        ...filters,
        from: window.from,
        to: cursorTo,
        snapshot_at: snapshotAt,
        limit: pageSize,
        offset: 0,
      },
      options.signal,
      options.retryDelaysMs,
    );

    const responseSnapshotAt = response.snapshot_at;
    if (!responseSnapshotAt || Number.isNaN(Date.parse(responseSnapshotAt))) {
      throw new Error("Telemetry history page did not provide an ingestion snapshot watermark");
    }
    if (snapshotAt === undefined) {
      snapshotAt = responseSnapshotAt;
      options.onSnapshot?.(snapshotAt);
    }
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

/**
 * #1809: complete history for several series under ONE ingestion snapshot, loaded in parallel.
 *
 * The first series' first page fixes the snapshot; every other series starts as soon as it is
 * known (no extra request). Actual concurrency is bounded by the shared history request limiter.
 * The first failure aborts the remaining pages so an unusable load stops consuming the server.
 * Results keep the order of `filtersList`.
 */
export async function loadCompleteTelemetryHistoryForSeries<T = CompleteTelemetryHistoryResult>(
  adapter: TelemetryAdapter,
  filtersList: readonly TelemetryFilters[],
  window: TelemetryHistoryWindow,
  options: Pick<
    TelemetryHistoryLoadOptions,
    "signal" | "snapshotAt" | "pageSize" | "maxPages" | "retryDelaysMs"
  > = {},
  /**
   * Runs as soon as ONE series has loaded, so callers can reduce it and let its raw samples be
   * released instead of holding every series' complete raw history until the slowest finishes.
   */
  onSeriesLoaded: (result: CompleteTelemetryHistoryResult, index: number) => T = (result) =>
    result as unknown as T,
): Promise<T[]> {
  if (filtersList.length === 0) return [];
  const linked = new AbortController();
  const forwardAbort = () => linked.abort(options.signal?.reason);
  if (options.signal?.aborted) linked.abort(options.signal.reason);
  else options.signal?.addEventListener("abort", forwardAbort, { once: true });

  const failFast = <R>(promise: Promise<R>): Promise<R> =>
    promise.catch((error: unknown) => {
      linked.abort();
      throw error;
    });

  try {
    let announce: (snapshotAt: string) => void = () => undefined;
    const announced = new Promise<string>((resolve) => {
      announce = resolve;
    });
    const firstLoad = loadCompleteTelemetryHistory(adapter, filtersList[0], window, {
      ...options,
      signal: linked.signal,
      onSnapshot: announce,
    });
    const snapshotFor = async (): Promise<string> =>
      options.snapshotAt ?? Promise.race([announced, firstLoad.then((result) => result.snapshotAt)]);
    const first = failFast(firstLoad.then((result) => onSeriesLoaded(result, 0)));
    const rest = filtersList.slice(1).map((filters, offset) =>
      failFast(
        snapshotFor()
          .then((snapshotAt) =>
            loadCompleteTelemetryHistory(adapter, filters, window, {
              ...options,
              signal: linked.signal,
              snapshotAt,
            }),
          )
          .then((result) => onSeriesLoaded(result, offset + 1)),
      ),
    );
    return await Promise.all([first, ...rest]);
  } finally {
    options.signal?.removeEventListener("abort", forwardAbort);
  }
}
