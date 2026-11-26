import { appendLiveHistoryTail, downsampleLiveHistory } from "@/features/live/live-history";
import type { TelemetryHistoryWindow } from "@/lib/telemetry/history";
import type { TelemetrySample } from "@/lib/telemetry/types";

import { savedDashboardDisplaySample } from "./embraco-series";
import type { LiveDashboardItem } from "./types";

const SEGMENT_PREFIX = "nexolab-live-segment:";

function identityKey(sample: TelemetrySample): string {
  return JSON.stringify([sample.node_id, sample.equipment_id, sample.channel_id, sample.metric]);
}

/** True when the sorted `timestamps` contain a value strictly between `from` and `to`. */
function hasTimestampBetween(timestamps: readonly number[] | undefined, from: number, to: number): boolean {
  if (!timestamps || timestamps.length === 0 || !(to > from)) return false;
  let low = 0;
  let high = timestamps.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (timestamps[middle] <= from) low = middle + 1;
    else high = middle;
  }
  return low < timestamps.length && timestamps[low] < to;
}

function unmarkedId(eventId: string): string {
  return eventId.startsWith(SEGMENT_PREFIX) ? eventId.slice(SEGMENT_PREFIX.length) : eventId;
}

/**
 * The generic downsampler only admits valid engineering values. For operator-accepted
 * Embraco readings, supply a temporary presentation-only value so chart history
 * continuity is computed correctly; restore raw NULL/unknown evidence afterwards.
 */
export function operatorHistoryPreview(item: LiveDashboardItem, sample: TelemetrySample): TelemetrySample {
  const displayed = savedDashboardDisplaySample(item, sample);
  return displayed?.operatorDerived
    ? { ...sample, value: displayed.value, unit: displayed.unit, quality: "valid" }
    : sample;
}

export function restoreOperatorEvidence(
  displaySamples: readonly TelemetrySample[],
  originals: readonly TelemetrySample[],
): TelemetrySample[] {
  const originalByEvent = new Map(originals.map((sample) => [unmarkedId(sample.event_id), sample]));
  return displaySamples.map((display) => {
    const original = originalByEvent.get(unmarkedId(display.event_id));
    return original ? { ...original, event_id: display.event_id } : display;
  });
}

export function reduceSavedDashboardHistory(
  item: LiveDashboardItem,
  samples: readonly TelemetrySample[],
  window: TelemetryHistoryWindow,
  maxPoints = 240,
): TelemetrySample[] {
  const preview = samples.map((sample) => operatorHistoryPreview(item, sample));
  const selected = downsampleLiveHistory(preview, window, maxPoints);
  const restored = restoreOperatorEvidence(selected, samples);
  // Explicit communication errors between retained points must not create a
  // false line when the generic reducer omits the invalid event itself.
  // All comparisons remain scoped to the selected channel and source times.
  if (restored.length < 2) return restored;
  // Index non-valid samples per channel identity once (sorted timestamps), then answer each
  // "was there a bad sample strictly between these two retained points" query by binary search.
  // This keeps the check O(n log n) instead of O(n²), which matters at 5 000 points per series.
  const badByIdentity = new Map<string, number[]>();
  for (const candidate of preview) {
    if (candidate.quality === "valid" && candidate.value !== null) continue;
    const key = identityKey(candidate);
    const list = badByIdentity.get(key);
    const when = Date.parse(candidate.captured_at);
    if (list) list.push(when);
    else badByIdentity.set(key, [when]);
  }
  for (const list of badByIdentity.values()) list.sort((a, b) => a - b);
  return restored.map((sample, index) => {
    if (index === 0 || sample.event_id.startsWith(SEGMENT_PREFIX)) return sample;
    const previous = restored[index - 1];
    const from = Date.parse(previous.captured_at);
    const to = Date.parse(sample.captured_at);
    const hadBadSample = hasTimestampBetween(badByIdentity.get(identityKey(sample)), from, to);
    return hadBadSample ? { ...sample, event_id: SEGMENT_PREFIX + unmarkedId(sample.event_id) } : sample;
  });
}

/**
 * #1805: appends raw live samples of ONE dashboard series to its already reduced history without
 * re-deriving continuity from reduced points. `sourceGapMs` is the tolerance derived from the raw
 * history load (undefined: fallback tolerance). `pendingBreakChannels` keeps the break after a
 * non-renderable live sample across single-sample calls.
 */
export function appendSavedDashboardTail(
  item: LiveDashboardItem,
  current: readonly TelemetrySample[],
  incoming: readonly TelemetrySample[],
  window: TelemetryHistoryWindow,
  maxPoints: number,
  sourceGapMs: number | undefined,
  pendingBreakChannels: Set<string>,
): TelemetrySample[] {
  const appended = appendLiveHistoryTail(
    current.map((sample) => operatorHistoryPreview(item, sample)),
    incoming.map((sample) => operatorHistoryPreview(item, sample)),
    window,
    maxPoints,
    { sourceGapMsFor: () => sourceGapMs, pendingBreakChannels },
  );
  return restoreOperatorEvidence(appended, [...current, ...incoming]);
}
