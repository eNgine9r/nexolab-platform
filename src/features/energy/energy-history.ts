import {
  isEnergySample,
  resolveEnergyMeter,
  type EnergyMetricId,
} from "@/features/energy/energy-telemetry";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

const HISTORY_PAGE_SIZE = 1_000;
const MAX_HISTORY_PAGES = 100;
export const MAX_HISTORY_POINTS_PER_METER = 240;

export interface EnergyHistoryWindow {
  metric: EnergyMetricId;
  from: Date;
  to: Date;
}

function evenlyDownsample(
  samples: readonly TelemetrySample[],
  maximumPoints: number,
): TelemetrySample[] {
  if (samples.length <= maximumPoints) return [...samples];
  if (maximumPoints <= 1) return [samples[0]];

  const sampled: TelemetrySample[] = [];
  const lastIndex = samples.length - 1;
  for (let index = 0; index < maximumPoints; index += 1) {
    const sourceIndex = Math.round((index * lastIndex) / (maximumPoints - 1));
    const sample = samples[sourceIndex];
    if (sampled.at(-1)?.event_id !== sample.event_id) sampled.push(sample);
  }
  return sampled;
}

export function downsampleEnergyHistory(
  samples: readonly TelemetrySample[],
  maximumPointsPerMeter = MAX_HISTORY_POINTS_PER_METER,
): TelemetrySample[] {
  const byMeter = new Map<number, TelemetrySample[]>();

  for (const sample of samples) {
    const meter = resolveEnergyMeter(sample);
    if (!meter) continue;
    const current = byMeter.get(meter.unitId) ?? [];
    current.push(sample);
    byMeter.set(meter.unitId, current);
  }

  return [...byMeter.entries()]
    .sort(([left], [right]) => left - right)
    .flatMap(([, meterSamples]) =>
      evenlyDownsample(
        meterSamples.sort(
          (left, right) => Date.parse(left.captured_at) - Date.parse(right.captured_at),
        ),
        maximumPointsPerMeter,
      ),
    );
}

export async function loadCompleteEnergyHistory(
  adapter: TelemetryAdapter,
  window: EnergyHistoryWindow,
  signal?: AbortSignal,
): Promise<TelemetrySample[]> {
  const samples = new Map<string, TelemetrySample>();
  let offset = 0;

  for (let page = 0; page < MAX_HISTORY_PAGES; page += 1) {
    const response = await adapter.history(
      {
        metric: window.metric,
        from: window.from,
        to: window.to,
        limit: HISTORY_PAGE_SIZE,
        offset,
      },
      signal,
    );

    for (const sample of response.items) {
      if (isEnergySample(sample)) samples.set(sample.event_id, sample);
    }

    if (response.next_offset === null) {
      return downsampleEnergyHistory([...samples.values()]);
    }
    if (response.next_offset <= offset) {
      throw new Error("Telemetry history pagination did not advance");
    }
    offset = response.next_offset;
  }

  throw new Error("Telemetry history exceeded the supported pagination window");
}
