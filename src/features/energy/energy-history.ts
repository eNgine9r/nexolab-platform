import { isEnergySample, resolveEnergyMeter, type EnergyMetricId } from "@/features/energy/energy-telemetry";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

const HISTORY_PAGE_SIZE = 1_000;
const MAX_HISTORY_PAGES = 100;
export const MAX_HISTORY_POINTS_PER_METER = 240;

export interface EnergyHistoryWindow {
  nodeId: string;
  metric: EnergyMetricId;
  from: Date;
  to: Date;
}

function isRenderableEnergyHistorySample(sample: TelemetrySample): boolean {
  return sample.quality === "valid" && sample.value !== null && Number.isFinite(sample.value);
}

function evenlyDownsample(samples: readonly TelemetrySample[], maximumPoints: number): TelemetrySample[] {
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
    if (!isRenderableEnergyHistorySample(sample)) continue;
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
        meterSamples.sort((left, right) => Date.parse(left.captured_at) - Date.parse(right.captured_at)),
        maximumPointsPerMeter,
      ),
    );
}

export function mergeEnergyHistoryTail(
  current: readonly TelemetrySample[],
  incoming: readonly TelemetrySample[],
  window: EnergyHistoryWindow,
): TelemetrySample[] {
  const from = window.from.getTime();
  const to = window.to.getTime();
  const merged = new Map<string, TelemetrySample>();

  for (const sample of [...current, ...incoming]) {
    const capturedAt = Date.parse(sample.captured_at);
    if (
      sample.node_id !== window.nodeId ||
      sample.metric !== window.metric ||
      !isEnergySample(sample) ||
      !isRenderableEnergyHistorySample(sample) ||
      !Number.isFinite(capturedAt) ||
      capturedAt < from ||
      capturedAt > to
    ) {
      continue;
    }
    merged.set(sample.event_id, sample);
  }

  return downsampleEnergyHistory([...merged.values()]);
}

export async function loadCompleteEnergyHistory(
  adapter: TelemetryAdapter,
  window: EnergyHistoryWindow,
  signal?: AbortSignal,
): Promise<TelemetrySample[]> {
  const samples = new Map<string, TelemetrySample>();
  let cursorTo = new Date(window.to);

  for (let page = 0; page < MAX_HISTORY_PAGES; page += 1) {
    const response = await adapter.history(
      {
        node_id: window.nodeId,
        metric: window.metric,
        from: window.from,
        to: cursorTo,
        limit: HISTORY_PAGE_SIZE,
        offset: 0,
      },
      signal,
    );

    for (const sample of response.items) {
      if (
        sample.node_id === window.nodeId &&
        sample.metric === window.metric &&
        isEnergySample(sample) &&
        isRenderableEnergyHistorySample(sample)
      ) {
        samples.set(sample.event_id, sample);
      }
    }

    if (response.next_offset === null) {
      return downsampleEnergyHistory([...samples.values()]);
    }

    const capturedTimes = response.items
      .map((sample) => Date.parse(sample.captured_at))
      .filter(Number.isFinite);
    if (capturedTimes.length === 0) {
      throw new Error("Telemetry history page did not provide a stable cursor");
    }

    const oldestCapturedAt = Math.min(...capturedTimes);
    if (oldestCapturedAt <= window.from.getTime()) {
      return downsampleEnergyHistory([...samples.values()]);
    }

    const boundaryCount = capturedTimes.filter((capturedAt) => capturedAt === oldestCapturedAt).length;
    if (boundaryCount >= HISTORY_PAGE_SIZE) {
      throw new Error("Telemetry history timestamp density exceeds the safe cursor window");
    }

    const currentCursor = cursorTo.getTime();
    cursorTo = new Date(oldestCapturedAt < currentCursor ? oldestCapturedAt : currentCursor - 1);
  }

  throw new Error("Telemetry history exceeded the supported pagination window");
}
