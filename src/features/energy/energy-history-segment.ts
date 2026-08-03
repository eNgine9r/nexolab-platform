import type { TelemetrySample } from "@/lib/telemetry/types";

const ENERGY_HISTORY_SEGMENT_PREFIX = "__nexolab_history_segment__:";

export function isEnergyHistorySegmentStart(eventId: string): boolean {
  return eventId.startsWith(ENERGY_HISTORY_SEGMENT_PREFIX);
}

export function energyHistorySourceEventId(eventId: string): string {
  return isEnergyHistorySegmentStart(eventId) ? eventId.slice(ENERGY_HISTORY_SEGMENT_PREFIX.length) : eventId;
}

export function markEnergyHistorySegmentStart(sample: TelemetrySample): TelemetrySample {
  if (isEnergyHistorySegmentStart(sample.event_id)) return sample;
  return { ...sample, event_id: `${ENERGY_HISTORY_SEGMENT_PREFIX}${sample.event_id}` };
}

export function clearEnergyHistorySegmentStart(sample: TelemetrySample): TelemetrySample {
  const eventId = energyHistorySourceEventId(sample.event_id);
  return eventId === sample.event_id ? sample : { ...sample, event_id: eventId };
}
