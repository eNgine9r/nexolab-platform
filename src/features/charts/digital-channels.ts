/**
 * Canonical digital-channel taxonomy (#1679, WP-O).
 *
 * Only metrics that the acquisition layer REALLY delivers are classified; nothing is invented:
 * - Danfoss AK-CC25 Pro: `compressor.state`, `fan.evaporator.state`, `controller.alarm_state` (0/1);
 * - Embraco Sync: `refrigeration.control_state` (enumerated mode code, 3 = defrost),
 *   `controller.relay_state_bits` (bitfield, relays 1..4), `controller.alarm_state_bits` (bitfield).
 * There is no door-state channel in any driver (door appears only as a temperature or an alarm
 * code), so no door lane exists.
 *
 * A lane state is ON, OFF, UNKNOWN (a poll happened but no valid state) or NO DATA (no poll);
 * the last two are produced by the lane builder, never by a decoder.
 */

export type DigitalLaneKind = "compressor" | "fan" | "alarm" | "relay" | "defrost" | "control_mode";

export interface DigitalLaneSpec {
  id: string;
  kind: DigitalLaneKind;
  label: string;
  /** ON / OFF for a valid raw value; null when the value is not a state this lane can represent. */
  decode: (value: number) => "on" | "off" | null;
  /** Operator-facing meaning of ON, shown with the lane. */
  onMeaning: string;
}

const EMBRACO_DEFROST_STATE = 3;
const EMBRACO_CONTROL_STATES = new Set([0, 1, 2, 3, 4, 5]);
const RELAY_COUNT = 4;

function binary(value: number): "on" | "off" | null {
  return value === 1 ? "on" : value === 0 ? "off" : null;
}

function relayLane(index: number): DigitalLaneSpec {
  return {
    id: `relay-${index + 1}`,
    kind: "relay",
    label: `Relay ${index + 1}`,
    decode: (value) => (Number.isInteger(value) && value >= 0 ? ((value >> index) & 1 ? "on" : "off") : null),
    onMeaning: "реле увімкнене (біт стану контролера)",
  };
}

const LANES_BY_METRIC: Readonly<Record<string, readonly DigitalLaneSpec[]>> = {
  "compressor.state": [
    {
      id: "compressor",
      kind: "compressor",
      label: "Компресор",
      decode: binary,
      onMeaning: "компресор працює (регістр стану)",
    },
  ],
  "fan.evaporator.state": [
    {
      id: "fan",
      kind: "fan",
      label: "Вентилятор випарника",
      decode: binary,
      onMeaning: "вентилятор працює (регістр стану)",
    },
  ],
  "controller.alarm_state": [
    {
      id: "alarm",
      kind: "alarm",
      label: "Аварія контролера",
      decode: binary,
      onMeaning: "контролер повідомляє про аварію",
    },
  ],
  "refrigeration.control_state": [
    {
      id: "defrost",
      kind: "defrost",
      label: "Відтайка",
      decode: (value) =>
        EMBRACO_CONTROL_STATES.has(Math.trunc(value))
          ? Math.trunc(value) === EMBRACO_DEFROST_STATE
            ? "on"
            : "off"
          : null,
      onMeaning: "код стану контролера = Defrost (3)",
    },
  ],
  "controller.relay_state_bits": Array.from({ length: RELAY_COUNT }, (_, index) => relayLane(index)),
  "controller.alarm_state_bits": [
    {
      id: "alarm-bits",
      kind: "alarm",
      label: "Аварії контролера",
      decode: (value) => (Number.isInteger(value) && value >= 0 ? (value > 0 ? "on" : "off") : null),
      onMeaning: "встановлено хоча б один біт аварії",
    },
  ],
};

/** Lane specifications for a metric, or an empty list when the metric is not a known digital channel. */
export function digitalLanesForMetric(metric: string): readonly DigitalLaneSpec[] {
  return LANES_BY_METRIC[metric] ?? [];
}

export function isDigitalMetric(metric: string): boolean {
  return Object.hasOwn(LANES_BY_METRIC, metric);
}

export const DIGITAL_METRICS: readonly string[] = Object.keys(LANES_BY_METRIC);
