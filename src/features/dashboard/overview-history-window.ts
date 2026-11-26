import type { TelemetrySample } from "@/lib/telemetry/types";

export interface OverviewHistoryWindow {
  from: Date;
  to: Date;
}

function parsed(sample: TelemetrySample): number {
  return Date.parse(sample.captured_at);
}

/**
 * The samples inside [from, to], unique by event_id (the later occurrence wins) and ordered by
 * captured time then event_id. Each timestamp is parsed once (#1827: the comparator used to parse
 * both sides on every comparison).
 */
export function orderedHistoryWindow(
  samples: readonly TelemetrySample[],
  window: OverviewHistoryWindow,
): TelemetrySample[] {
  const fromMs = window.from.getTime();
  const toMs = window.to.getTime();
  const byEventId = new Map<string, { sample: TelemetrySample; timestampMs: number }>();
  for (const sample of samples) {
    const timestampMs = parsed(sample);
    if (!Number.isFinite(timestampMs) || timestampMs < fromMs || timestampMs > toMs) continue;
    byEventId.set(sample.event_id, { sample, timestampMs });
  }
  return [...byEventId.values()]
    .sort(
      (left, right) =>
        left.timestampMs - right.timestampMs || left.sample.event_id.localeCompare(right.sample.event_id),
    )
    .map((entry) => entry.sample);
}

/** First index whose captured time is >= `targetMs` (input ordered by captured time). */
function lowerBound(samples: readonly TelemetrySample[], targetMs: number): number {
  let low = 0;
  let high = samples.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (parsed(samples[middle]) < targetMs) low = middle + 1;
    else high = middle;
  }
  return low;
}

/** First index whose captured time is > `targetMs`. */
function upperBound(samples: readonly TelemetrySample[], targetMs: number): number {
  let low = 0;
  let high = samples.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (parsed(samples[middle]) <= targetMs) low = middle + 1;
    else high = middle;
  }
  return low;
}

/**
 * Drops samples outside a moved window from an already ordered, unique history by binary search.
 * Returns the same array when nothing changes.
 */
export function trimHistoryWindow(
  current: TelemetrySample[],
  window: OverviewHistoryWindow,
): TelemetrySample[] {
  const start = lowerBound(current, window.from.getTime());
  const end = upperBound(current, window.to.getTime());
  return start === 0 && end === current.length ? current : current.slice(start, end);
}

function after(left: { timestampMs: number; eventId: string }, right: TelemetrySample | undefined): boolean {
  if (!right) return true;
  const rightMs = parsed(right);
  return (
    left.timestampMs > rightMs ||
    (left.timestampMs === rightMs && left.eventId.localeCompare(right.event_id) > 0)
  );
}

/**
 * #1827: appends live samples to an ordered, unique history and trims it to the window.
 *
 * The usual case — reconciled live samples newer than everything held — is an append plus a
 * binary-search trim. Anything else (late or repeated events) takes the full ordered rebuild, so
 * the result is always identical to `orderedHistoryWindow([...current, ...incoming], window)`.
 */
export function appendHistoryTail(
  current: TelemetrySample[],
  incoming: readonly TelemetrySample[],
  window: OverviewHistoryWindow,
): TelemetrySample[] {
  if (incoming.length === 0) return trimHistoryWindow(current, window);
  const ordered = incoming
    .map((sample) => ({ sample, timestampMs: parsed(sample), eventId: sample.event_id }))
    .sort((left, right) => left.timestampMs - right.timestampMs || left.eventId.localeCompare(right.eventId));
  const fromMs = window.from.getTime();
  const toMs = window.to.getTime();
  // In order: strictly after the newest held sample and free of repeated event ids (a repeat
  // replaces the held copy in the full rebuild). The id set costs one pass, no parsing or sorting.
  let inOrder = after(ordered[0], current.at(-1));
  const held = inOrder ? new Set(current.map((sample) => sample.event_id)) : null;
  for (let index = 0; inOrder && index < ordered.length; index += 1) {
    const entry = ordered[index];
    const previous = ordered[index - 1];
    if (!Number.isFinite(entry.timestampMs) || held!.has(entry.eventId)) inOrder = false;
    else if (previous && !after(entry, previous.sample)) inOrder = false;
    held?.add(entry.eventId);
  }
  if (!inOrder) return orderedHistoryWindow([...current, ...incoming], window);
  const kept = trimHistoryWindow(current, window);
  const appended = ordered
    .filter((entry) => entry.timestampMs >= fromMs && entry.timestampMs <= toMs)
    .map((entry) => entry.sample);
  return appended.length === 0 ? kept : kept.concat(appended);
}
