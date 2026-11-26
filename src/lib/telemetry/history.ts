import { TelemetryClientError } from "./errors";
import { HISTORY_MAX_CONCURRENT_REQUESTS, RequestLimiter } from "./request-limiter";
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
  // Each timestamp is parsed once; the comparator used to parse both sides per comparison.
  const byEventId = new Map<string, { sample: TelemetrySample; capturedAt: number }>();
  for (const sample of samples) {
    const capturedAt = parsedTimestamp(sample.captured_at);
    if (!Number.isFinite(capturedAt)) {
      throw new Error(`Telemetry sample ${sample.event_id} has an invalid captured_at timestamp`);
    }
    if (!byEventId.has(sample.event_id)) byEventId.set(sample.event_id, { sample, capturedAt });
  }
  return [...byEventId.values()]
    .sort(
      (left, right) =>
        left.capturedAt - right.capturedAt || left.sample.event_id.localeCompare(right.sample.event_id),
    )
    .map((entry) => entry.sample);
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
  > & {
    /**
     * #1824: series loading at the same time (default: the history request slots of the tab).
     * Each series pages sequentially, so this keeps every slot busy while series complete in
     * order instead of all at the end, and callers can show them progressively.
     */
    seriesConcurrency?: number;
    /**
     * Raw row budget of the whole load (default HISTORY_MAX_RAW_ROWS). After each completed series
     * the total is projected from the rows per series; an over-budget load stops every request
     * and throws TelemetryHistoryVolumeError instead of reading for minutes.
     */
    maxRows?: number;
  } = {},
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

  let volumeError: TelemetryHistoryVolumeError | null = null;
  const failFast = <R>(promise: Promise<R>): Promise<R> =>
    promise.catch((error: unknown) => {
      linked.abort();
      throw volumeError ?? error;
    });
  const maxRows = options.maxRows ?? HISTORY_MAX_RAW_ROWS;
  let loadedRows = 0;
  let loadedSeries = 0;
  const withinBudget = (result: CompleteTelemetryHistoryResult): CompleteTelemetryHistoryResult => {
    if (volumeError) throw volumeError;
    loadedRows += result.samples.length;
    loadedSeries += 1;
    const projected = Math.round((loadedRows / loadedSeries) * filtersList.length);
    if (loadedRows > maxRows || projected > maxRows) {
      volumeError = new TelemetryHistoryVolumeError(Math.max(loadedRows, projected), maxRows);
      linked.abort();
      throw volumeError;
    }
    return result;
  };

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
    // #1824: the first series holds one series slot from the start; the others take slots in their
    // order once the snapshot is fixed. A FIFO page queue across all series made every series
    // finish at nearly the same moment.
    const seriesSlots = new RequestLimiter(
      Math.max(1, Math.floor(options.seriesConcurrency ?? HISTORY_MAX_CONCURRENT_REQUESTS)),
    );
    const first = failFast(
      seriesSlots
        .run(linked.signal, () => firstLoad)
        .then((result) => onSeriesLoaded(withinBudget(result), 0)),
    );
    const rest = filtersList.slice(1).map((filters, offset) =>
      failFast(
        snapshotFor()
          .then((snapshotAt) =>
            seriesSlots.run(linked.signal, () =>
              loadCompleteTelemetryHistory(adapter, filters, window, {
                ...options,
                signal: linked.signal,
                snapshotAt,
              }),
            ),
          )
          .then((result) => onSeriesLoaded(withinBudget(result), offset + 1)),
      ),
    );
    return await Promise.all([first, ...rest]);
  } finally {
    options.signal?.removeEventListener("abort", forwardAbort);
  }
}

/** Default slice length of a long history window (each slice pages separately). */
export const HISTORY_SLICE_MS = 6 * 60 * 60 * 1_000;
/**
 * Raw rows one history load may read before it stops (#P0 charts). About 500 pages of 1 000 rows:
 * the old single-stream page cap, now enforced up front from the measured density instead of
 * failing after minutes. Beyond it, aggregated history (backend after DR #1428) is required.
 */
export const HISTORY_MAX_RAW_ROWS = 500_000;

/** A history window holds more raw rows than one load may read; nothing partial is shown. */
export class TelemetryHistoryVolumeError extends Error {
  constructor(
    readonly estimatedRows: number,
    readonly maximumRows: number,
  ) {
    super(
      `Обраний період містить близько ${Math.round(estimatedRows / 1_000)} тис. вимірювань, ` +
        `більше за безпечну межу ${Math.round(maximumRows / 1_000)} тис. для сирої історії. ` +
        "Оберіть коротший період або менше каналів; агрегована історія для довгих періодів " +
        "стане доступною після оновлення backend.",
    );
    this.name = "TelemetryHistoryVolumeError";
  }
}

export interface TelemetryHistorySlice {
  index: number;
  from: Date;
  to: Date;
}

export interface SlicedTelemetryHistoryOptions extends Pick<
  TelemetryHistoryLoadOptions,
  "signal" | "snapshotAt" | "pageSize" | "retryDelaysMs"
> {
  /** Slice length (default 6 h). Each slice keeps its own page limit. */
  sliceMs?: number;
  /** Slices loading at once (default: the tab's history request slots). */
  sliceConcurrency?: number;
  /** Page limit of one slice (default 500). */
  maxPagesPerSlice?: number;
  /** Raw row budget of the whole load (default HISTORY_MAX_RAW_ROWS). */
  maxRows?: number;
}

export interface SlicedTelemetryHistoryResult {
  snapshotAt: string;
  rows: number;
  slices: number;
}

/** [from, to) split into slices, newest first. The backend reads from inclusive, to exclusive. */
export function telemetryHistorySlices(
  window: TelemetryHistoryWindow,
  sliceMs: number,
): TelemetryHistorySlice[] {
  validateWindow(window);
  const fromMs = window.from.getTime();
  const toMs = window.to.getTime();
  const length = Math.max(1, Math.floor(sliceMs));
  const slices: TelemetryHistorySlice[] = [];
  for (let end = toMs, index = 0; end > fromMs; end -= length, index += 1) {
    slices.push({ index, from: new Date(Math.max(fromMs, end - length)), to: new Date(end) });
  }
  return slices;
}

/**
 * Loads one history filter over a long window as time slices (#P0 charts): newest slice first (it
 * fixes the ingestion snapshot), the others under that snapshot with at most `sliceConcurrency`
 * slices at once, each paging sequentially with page retry and its own page limit. Slices do not
 * overlap. `onSlice` receives every slice's ordered, unique samples as soon as it has loaded, so
 * callers reduce them and keep no raw sample objects.
 *
 * The row budget is checked from the measured density as soon as a slice completes and again for
 * every slice; an over-budget window aborts every request and throws TelemetryHistoryVolumeError
 * instead of loading for minutes or failing at a page limit. Aborting `signal` cancels everything.
 */
export async function loadTelemetryHistorySlices(
  adapter: TelemetryAdapter,
  filters: TelemetryFilters,
  window: TelemetryHistoryWindow,
  options: SlicedTelemetryHistoryOptions,
  onSlice: (samples: TelemetrySample[], slice: TelemetryHistorySlice) => void,
): Promise<SlicedTelemetryHistoryResult> {
  const slices = telemetryHistorySlices(window, options.sliceMs ?? HISTORY_SLICE_MS);
  const totalMs = window.to.getTime() - window.from.getTime();
  const maxRows = options.maxRows ?? HISTORY_MAX_RAW_ROWS;
  const linked = new AbortController();
  const forwardAbort = () => linked.abort(options.signal?.reason);
  if (options.signal?.aborted) linked.abort(options.signal.reason);
  else options.signal?.addEventListener("abort", forwardAbort, { once: true });
  let rows = 0;
  let loadedMs = 0;
  let volumeError: TelemetryHistoryVolumeError | null = null;
  const checkBudget = () => {
    const estimated = loadedMs > 0 ? Math.round((rows / loadedMs) * totalMs) : rows;
    if (rows > maxRows || (loadedMs > 0 && estimated > maxRows)) {
      volumeError ??= new TelemetryHistoryVolumeError(Math.max(rows, estimated), maxRows);
      linked.abort();
      throw volumeError;
    }
  };
  const loadSlice = (
    slice: TelemetryHistorySlice,
    snapshotAt: string | undefined,
    onSnapshot?: (value: string) => void,
  ) =>
    loadCompleteTelemetryHistory(
      adapter,
      filters,
      { from: slice.from, to: slice.to },
      {
        signal: linked.signal,
        snapshotAt,
        pageSize: options.pageSize,
        maxPages: options.maxPagesPerSlice,
        retryDelaysMs: options.retryDelaysMs,
        onSnapshot,
      },
    ).then((result) => {
      if (volumeError) throw volumeError;
      rows += result.samples.length;
      loadedMs += slice.to.getTime() - slice.from.getTime();
      checkBudget();
      onSlice(result.samples, slice);
      return result.snapshotAt;
    });
  const failFast = <R>(promise: Promise<R>): Promise<R> =>
    promise.catch((error: unknown) => {
      linked.abort();
      throw volumeError ?? error;
    });
  try {
    let announce: (snapshotAt: string) => void = () => undefined;
    const announced = new Promise<string>((resolve) => {
      announce = resolve;
    });
    const sliceSlots = new RequestLimiter(
      Math.max(1, Math.floor(options.sliceConcurrency ?? HISTORY_MAX_CONCURRENT_REQUESTS)),
    );
    const first = failFast(
      sliceSlots.run(linked.signal, () => loadSlice(slices[0], options.snapshotAt, announce)),
    );
    const snapshotFor = async (): Promise<string> => options.snapshotAt ?? Promise.race([announced, first]);
    const rest = slices
      .slice(1)
      .map((slice) =>
        failFast(
          snapshotFor().then((snapshotAt) =>
            sliceSlots.run(linked.signal, () => loadSlice(slice, snapshotAt)),
          ),
        ),
      );
    const [snapshotAt] = await Promise.all([first, ...rest]);
    return { snapshotAt, rows, slices: slices.length };
  } finally {
    options.signal?.removeEventListener("abort", forwardAbort);
  }
}
