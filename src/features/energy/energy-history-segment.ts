import type { TelemetrySample } from "@/lib/telemetry/types";

const ENERGY_HISTORY_SEGMENT_PREFIX = "__nexolab_history_segment__:";
const ENERGY_HISTORY_PENDING_BREAK_PREFIX = "__nexolab_history_pending_break__:";

interface EnergyHistoryMarkers {
  sourceEventId: string;
  segmentStart: boolean;
  breakPending: boolean;
}

function parseEnergyHistoryMarkers(eventId: string): EnergyHistoryMarkers {
  let sourceEventId = eventId;
  let segmentStart = false;
  let breakPending = false;
  let changed = true;

  while (changed) {
    changed = false;
    if (sourceEventId.startsWith(ENERGY_HISTORY_SEGMENT_PREFIX)) {
      segmentStart = true;
      sourceEventId = sourceEventId.slice(ENERGY_HISTORY_SEGMENT_PREFIX.length);
      changed = true;
    }
    if (sourceEventId.startsWith(ENERGY_HISTORY_PENDING_BREAK_PREFIX)) {
      breakPending = true;
      sourceEventId = sourceEventId.slice(ENERGY_HISTORY_PENDING_BREAK_PREFIX.length);
      changed = true;
    }
  }

  return { sourceEventId, segmentStart, breakPending };
}

function encodeEnergyHistoryMarkers(markers: EnergyHistoryMarkers): string {
  let eventId = markers.sourceEventId;
  if (markers.segmentStart) eventId = `${ENERGY_HISTORY_SEGMENT_PREFIX}${eventId}`;
  if (markers.breakPending) eventId = `${ENERGY_HISTORY_PENDING_BREAK_PREFIX}${eventId}`;
  return eventId;
}

export function isEnergyHistorySegmentStart(eventId: string): boolean {
  return parseEnergyHistoryMarkers(eventId).segmentStart;
}

export function isEnergyHistoryBreakPending(eventId: string): boolean {
  return parseEnergyHistoryMarkers(eventId).breakPending;
}

export function energyHistorySourceEventId(eventId: string): string {
  return parseEnergyHistoryMarkers(eventId).sourceEventId;
}

export function clearEnergyHistoryMarkers(sample: TelemetrySample): TelemetrySample {
  const eventId = energyHistorySourceEventId(sample.event_id);
  return eventId === sample.event_id ? sample : { ...sample, event_id: eventId };
}

export function clearEnergyHistoryBreakPending(sample: TelemetrySample): TelemetrySample {
  const markers = parseEnergyHistoryMarkers(sample.event_id);
  if (!markers.breakPending) return sample;
  return {
    ...sample,
    event_id: encodeEnergyHistoryMarkers({ ...markers, breakPending: false }),
  };
}

export function markEnergyHistorySegmentStart(sample: TelemetrySample): TelemetrySample {
  const markers = parseEnergyHistoryMarkers(sample.event_id);
  return {
    ...sample,
    event_id: encodeEnergyHistoryMarkers({ ...markers, segmentStart: true }),
  };
}

export function markEnergyHistoryBreakPending(sample: TelemetrySample): TelemetrySample {
  const markers = parseEnergyHistoryMarkers(sample.event_id);
  return {
    ...sample,
    event_id: encodeEnergyHistoryMarkers({ ...markers, breakPending: true }),
  };
}
