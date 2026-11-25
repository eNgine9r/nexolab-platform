import { operatorEmbracoCelsius } from "@/features/refrigeration/embraco-operator-scale";
import type { TelemetrySample } from "@/lib/telemetry/types";

import type { LiveDashboardItem } from "./types";

/**
 * Only the actual observed Embraco Unit 2 channels at edge-01.
 * This is presentation logic, not an approved hardware temperature calibration.
 */
const OPERATOR_EMBRACO_SERIES = {
  "2-cabinet-temperature": {
    metric: "temperature.cabinet",
    name: "Температура в об’ємі",
    unit: "°C",
  },
  "2-evaporator-temperature": {
    metric: "temperature.evaporator",
    name: "Датчик відтайки",
    unit: "°C",
  },
  "2-compressor-speed": {
    metric: "compressor.speed",
    name: "Обороти компресора",
    unit: "rpm",
  },
} as const;

type OperatorSeriesChannel = keyof typeof OPERATOR_EMBRACO_SERIES;

function configuredOperatorSeries(item: LiveDashboardItem) {
  if (
    item.channel_ref_id !== null ||
    item.node_id !== "edge-01" ||
    item.equipment_id !== "EMBRACO-2" ||
    !Object.hasOwn(OPERATOR_EMBRACO_SERIES, item.channel_id)
  ) {
    return null;
  }
  const config = OPERATOR_EMBRACO_SERIES[item.channel_id as OperatorSeriesChannel];
  return config.metric === item.metric ? config : null;
}

export function savedDashboardSeriesLabel(item: LiveDashboardItem): string {
  return configuredOperatorSeries(item)?.name ?? `${item.channel_id} · ${item.metric}`;
}

/** Keep existing channel-cell identity for non-Embraco saved dashboards. */
export function savedDashboardChannelLabel(item: LiveDashboardItem): string {
  return configuredOperatorSeries(item)?.name ?? item.channel_id;
}

export function savedDashboardSeriesUnit(item: LiveDashboardItem): string {
  return configuredOperatorSeries(item)?.unit ?? item.native_unit;
}

export function isOperatorEmbracoTemperature(item: LiveDashboardItem): boolean {
  const config = configuredOperatorSeries(item);
  return config !== null && config.unit === "°C";
}

export interface DisplayedSample {
  value: number;
  unit: string;
  /** Source telemetry remains unknown/null; conversion must not overwrite it. */
  operatorDerived: boolean;
}

export function savedDashboardDisplaySample(
  item: LiveDashboardItem,
  sample: TelemetrySample | null,
): DisplayedSample | null {
  if (!sample) return null;
  const config = configuredOperatorSeries(item);
  if (config) {
    if (
      sample.node_id !== item.node_id ||
      sample.equipment_id !== item.equipment_id ||
      sample.channel_id !== item.channel_id ||
      sample.metric !== item.metric
    ) {
      return null;
    }
    if (config.unit === "°C") {
      const scaled = operatorEmbracoCelsius(sample);
      if (scaled !== null) return { value: scaled, unit: "°C", operatorDerived: true };
    }
  }
  if (sample.quality !== "valid" || sample.value === null || !Number.isFinite(sample.value)) return null;
  return { value: sample.value, unit: config?.unit ?? sample.unit, operatorDerived: false };
}
