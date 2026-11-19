import { downsampleLiveHistory } from "@/features/live/live-history";
import type { TelemetryHistoryWindow } from "@/lib/telemetry/history";
import type { TelemetrySample } from "@/lib/telemetry/types";

import { savedDashboardDisplaySample } from "./embraco-series";
import type { LiveDashboardItem } from "./types";

const SEGMENT_PREFIX = "nexolab-live-segment:";

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
  const sorted = preview.toSorted((a, b) => Date.parse(a.captured_at) - Date.parse(b.captured_at));
  return restored.map((sample, index) => {
    if (index === 0 || sample.event_id.startsWith(SEGMENT_PREFIX)) return sample;
    const previous = restored[index - 1];
    const from = Date.parse(previous.captured_at);
    const to = Date.parse(sample.captured_at);
    const hadBadSample = sorted.some((candidate) => {
      const when = Date.parse(candidate.captured_at);
      return (
        when > from &&
        when < to &&
        candidate.node_id === sample.node_id &&
        candidate.equipment_id === sample.equipment_id &&
        candidate.channel_id === sample.channel_id &&
        candidate.metric === sample.metric &&
        (candidate.quality !== "valid" || candidate.value === null)
      );
    });
    return hadBadSample ? { ...sample, event_id: SEGMENT_PREFIX + unmarkedId(sample.event_id) } : sample;
  });
}
