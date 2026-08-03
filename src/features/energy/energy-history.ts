import { isEnergySample, resolveEnergyMeter, type EnergyMetricId } from "@/features/energy/energy-telemetry";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

const HISTORY_PAGE_SIZE = 1_000;
const MAX_HISTORY_PAGES = 100;
export const MAX_HISTORY_POINTS_PER_METER = 240;
export const ENERGY_HISTORY_MAX_FUTURE_SKEW_MS = 30_000;

export interface EnergyHistoryWindow {
  nodeId: string;
  metric: EnergyMetricId;
  from: Date;
  to: Date;
}

function isRenderableEnergyHistorySample(sample: TelemetrySample): boolean {
  return sample.quality === "valid" && sample.value !== null && Number.isFinite(sample.value);
}

export function selectEnergyHistoryTail(
  samples: readonly TelemetrySample[],
  nodeId: string,
  metric: EnergyMetricId,
  now: number = Date.now(),
  maximumFutureSkewMs = ENERGY_HISTORY_MAX_FUTURE_SKEW_MS,
): TelemetrySample[] {
  return samples.filter((sample) => {
    const capturedAt = Date.parse(sample.captured_at);
    return (
      sample.node_id === nodeId &&
      sample.metric === metric &&
      isEnergySample(sample) &&
      isRenderableEnergyHistorySample(sample) &&
      Number.isFinite(capturedAt) &&
      capturedAt <= now + maximumFutureSkewMs
    );
  });
}

function bucketDownsample(
  samples: readonly TelemetrySample[],
  maximumPoints: number,
  window?: Pick<EnergyHistoryWindow, "from" | "to">,
): TelemetrySample[] {
  const sorted = [...samples].sort(
    (left, right) => Date.parse(left.captured_at) - Date.parse(right.captured_at),
  );
  if (sorted.length <= maximumPoints) return sorted;
  if (maximumPoints <= 1) return [sorted.at(-1)!];
  if (maximumPoints === 2) return [sorted[0], sorted.at(-1)!];

  const sampleFrom = Date.parse(sorted[0].captured_at);
  const sampleTo = Date.parse(sorted.at(-1)!.captured_at);
  const from = window?.from.getTime() ?? sampleFrom;
  const to = window?.to.getTime() ?? sampleTo;
  const rangeMs = Math.max(1, to - from);
  const bucketMs = Math.max(1, Math.ceil(rangeMs / (maximumPoints - 2)));
  const buckets = new Map<number, TelemetrySample>();

  for (const sample of sorted) {
    const capturedAt = Date.parse(sample.captured_at);
    if (!Number.isFinite(capturedAt)) continue;
    const bucket = Math.floor(capturedAt / bucketMs);
    const current = buckets.get(bucket);
    if (!current || Date.parse(current.captured_at) <= capturedAt) buckets.set(bucket, sample);
  }

  const first = sorted[0];
  const last = sorted.at(-1)!;
  buckets.set(Math.floor(Date.parse(first.captured_at) / bucketMs), first);
  buckets.set(Math.floor(Date.parse(last.captured_at) / bucketMs), last);

  return [...buckets.values()]
    .sort((left, right) => Date.parse(left.captured_at) - Date.parse(right.captured_at))
    .slice(-maximumPoints);
}

export function downsampleEnergyHistory(
  samples: readonly TelemetrySample[],
  maximumPointsPerMeter = MAX_HISTORY_POINTS_PER_METER,
  window?: Pick<EnergyHistoryWindow, "from" | "to">,
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
    .flatMap(([, meterSamples]) => bucketDownsample(meterSamples, maximumPointsPerMeter, window));
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

  return downsampleEnergyHistory([...merged.values()], MAX_HISTORY_POINTS_PER_METER, window);
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
      return downsampleEnergyHistory([...samples.values()], MAX_HISTORY_POINTS_PER_METER, window);
    }

    const capturedTimes = response.items
      .map((sample) => Date.parse(sample.captured_at))
      .filter(Number.isFinite);
    if (capturedTimes.length === 0) {
      throw new Error("Telemetry history page did not provide a stable cursor");
    }

    const oldestCapturedAt = Math.min(...capturedTimes);
    if (oldestCapturedAt <= window.from.getTime()) {
      return downsampleEnergyHistory([...samples.values()], MAX_HISTORY_POINTS_PER_METER, window);
    }

    const boundaryCount = capturedTimes.filter((capturedAt) => capturedAt === oldestCapturedAt).length;
    if (boundaryCount >= HISTORY_PAGE_SIZE) {
      throw new Error("Telemetry history timestamp density exceeds the safe cursor window");
    }

    const currentCursor = cursorTo.getTime();
    const overlappingBoundaryCursor = oldestCapturedAt + 1;
    cursorTo = new Date(
      overlappingBoundaryCursor < currentCursor ? overlappingBoundaryCursor : currentCursor - 1,
    );
  }

  throw new Error("Telemetry history exceeded the supported pagination window");
}
