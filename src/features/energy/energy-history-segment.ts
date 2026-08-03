import type { TelemetrySample } from "@/lib/telemetry/types";

const ENERGY_HISTORY_SEGMENT_PREFIX = "__nexolab_history_segment__:";
const ENERGY_HISTORY_PENDING_BREAK_PREFIX = "__nexolab_history_pending_break__:";

export function isEnergyHistorySegmentStart(eventId: string): boolean {
  return eventId.startsWith(ENERGY_HISTORY_SEGMENT_PREFIX);
}

export function isEnergyHistoryBreakPending(eventId: string): boolean {
  return eventId.startsWith(ENERGY_HISTORY_PENDING_BREAK_PREFIX);
}

export function energyHistorySourceEventId(eventId: string): string {
  if (isEnergyHistorySegmentStart(eventId)) return eventId.slice(ENERGY_HISTORY_SEGMENT_PREFIX.length);
  if (isEnergyHistoryBreakPending(eventId)) {
    return eventId.slice(ENERGY_HISTORY_PENDING_BREAK_PREFIX.length);
  }
  return eventId;
}

export function clearEnergyHistoryMarkers(sample: TelemetrySample): TelemetrySample {
  const eventId = energyHistorySourceEventId(sample.event_id);
  return eventId === sample.event_id ? sample : { ...sample, event_id: eventId };
}

export function clearEnergyHistoryBreakPending(sample: TelemetrySample): TelemetrySample {
  if (!isEnergyHistoryBreakPending(sample.event_id)) return sample;
  return { ...sample, event_id: energyHistorySourceEventId(sample.event_id) };
}

export function markEnergyHistorySegmentStart(sample: TelemetrySample): TelemetrySample {
  const normalized = clearEnergyHistoryMarkers(sample);
  return { ...normalized, event_id: `${ENERGY_HISTORY_SEGMENT_PREFIX}${normalized.event_id}` };
}

export function markEnergyHistoryBreakPending(sample: TelemetrySample): TelemetrySample {
  const normalized = clearEnergyHistoryMarkers(sample);
  return { ...normalized, event_id: `${ENERGY_HISTORY_PENDING_BREAK_PREFIX}${normalized.event_id}` };
}
