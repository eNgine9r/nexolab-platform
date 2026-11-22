/**
 * Complete, bounded session telemetry history loading (#1649).
 *
 * The session workspace used to read ONE page (limit 1000, offset 0) and ignore `next_offset`,
 * so longer histories were silently truncated. This loader paginates until the server reports
 * no further page, merges by `event_id`, and reports `truncated` if the safety page cap is hit
 * so the UI can say so instead of pretending the chart is complete. Polls only fetch the tail
 * (newer than the newest cached sample, with a small overlap) and prune samples that left the
 * rolling window.
 */

export const SESSION_HISTORY_PAGE_LIMIT = 1_000;
export const SESSION_HISTORY_MAX_PAGES = 20;
export const SESSION_HISTORY_TAIL_OVERLAP_MS = 120_000;

export interface SessionHistoryItem {
  event_id: string;
  captured_at: string;
}

export interface SessionHistoryPage<T extends SessionHistoryItem> {
  items: readonly T[];
  next_offset: number | null;
}

export interface SessionHistoryLoadResult<T extends SessionHistoryItem> {
  items: T[];
  /** True when more pages exist than the safety cap allows; the data shown is incomplete. */
  truncated: boolean;
}

function capturedAt(item: SessionHistoryItem): number {
  const parsed = Date.parse(item.captured_at);
  return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
}

export async function loadSessionHistory<T extends SessionHistoryItem>({
  fetchPage,
  windowFrom,
  windowTo,
  existing,
  maxPages = SESSION_HISTORY_MAX_PAGES,
}: {
  fetchPage: (query: {
    from: Date;
    to: Date;
    offset: number;
    limit: number;
  }) => Promise<SessionHistoryPage<T>>;
  windowFrom: Date;
  windowTo: Date;
  /** Previously loaded items of the same session; enables tail-only fetching. */
  existing?: readonly T[];
  maxPages?: number;
}): Promise<SessionHistoryLoadResult<T>> {
  const byEvent = new Map<string, T>();
  const keepFrom = windowFrom.getTime();
  const cached = (existing ?? []).filter((item) => capturedAt(item) >= keepFrom);
  for (const item of cached) byEvent.set(item.event_id, item);

  const newestCached = cached.reduce((newest, item) => Math.max(newest, capturedAt(item)), keepFrom);
  const incremental = cached.length > 0;
  const from = incremental
    ? new Date(Math.max(keepFrom, newestCached - SESSION_HISTORY_TAIL_OVERLAP_MS))
    : windowFrom;

  let offset = 0;
  let truncated = false;
  for (let page = 0; ; page += 1) {
    if (page >= maxPages) {
      truncated = true;
      break;
    }
    const response = await fetchPage({ from, to: windowTo, offset, limit: SESSION_HISTORY_PAGE_LIMIT });
    for (const item of response.items) byEvent.set(item.event_id, item);
    if (response.next_offset === null || response.next_offset === undefined) break;
    if (response.next_offset <= offset) {
      throw new Error("Session telemetry history pagination did not advance.");
    }
    offset = response.next_offset;
  }

  const items = [...byEvent.values()].sort(
    (left, right) => capturedAt(left) - capturedAt(right) || left.event_id.localeCompare(right.event_id),
  );
  return { items, truncated };
}
