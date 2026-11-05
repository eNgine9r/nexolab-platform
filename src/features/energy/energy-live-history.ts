import {
  isEnergyHistoryBreakPending,
  markEnergyHistorySegmentStart,
} from "@/features/energy/energy-history-segment";
import { resolveEnergyMeter } from "@/features/energy/energy-telemetry";
import { energyMeterIdentity } from "@/features/energy/energy-commissioned-meters";
import type { TelemetrySample } from "@/lib/telemetry/types";

export interface EnergyLiveHistoryReconciliation {
  samples: TelemetrySample[];
  pendingMeterKeys: Set<string>;
  newestCapturedAtByMeterKey: Map<string, number>;
}

export interface EnergyLiveHistorySeed {
  pendingMeterKeys: Set<string>;
  newestCapturedAtByMeterKey: Map<string, number>;
}

function isRenderable(sample: TelemetrySample): boolean {
  return sample.quality === "valid" && sample.value !== null && Number.isFinite(sample.value);
}

export function seedEnergyLiveHistoryState(samples: readonly TelemetrySample[]): EnergyLiveHistorySeed {
  const latestByMeterKey = new Map<string, { sample: TelemetrySample; capturedAt: number }>();

  for (const sample of samples) {
    const meter = resolveEnergyMeter(sample);
    const capturedAt = Date.parse(sample.captured_at);
    if (!meter || !Number.isFinite(capturedAt)) continue;

    const key = energyMeterIdentity(sample.node_id, meter.equipmentId);
    const current = latestByMeterKey.get(key);
    if (current === undefined || capturedAt > current.capturedAt) {
      latestByMeterKey.set(key, { sample, capturedAt });
    }
  }

  const pendingMeterKeys = new Set<string>();
  const newestCapturedAtByMeterKey = new Map<string, number>();
  for (const [key, latest] of latestByMeterKey) {
    newestCapturedAtByMeterKey.set(key, latest.capturedAt);
    if (!isRenderable(latest.sample) || isEnergyHistoryBreakPending(latest.sample.event_id)) {
      pendingMeterKeys.add(key);
    }
  }

  return { pendingMeterKeys, newestCapturedAtByMeterKey };
}

export function reconcileEnergyLiveHistory(
  samples: readonly TelemetrySample[],
  pendingMeterKeys: ReadonlySet<string> = new Set(),
  newestCapturedAtByMeterKey: ReadonlyMap<string, number> = new Map(),
): EnergyLiveHistoryReconciliation {
  const pending = new Set(pendingMeterKeys);
  const newest = new Map(newestCapturedAtByMeterKey);
  const reconciled: TelemetrySample[] = [];
  const sorted = [...samples].sort(
    (left, right) => Date.parse(left.captured_at) - Date.parse(right.captured_at),
  );

  for (const sample of sorted) {
    const meter = resolveEnergyMeter(sample);
    const capturedAt = Date.parse(sample.captured_at);
    if (!meter || !Number.isFinite(capturedAt)) continue;

    const key = energyMeterIdentity(sample.node_id, meter.equipmentId);
    const newestCapturedAt = newest.get(key);
    const advancesCursor = newestCapturedAt === undefined || capturedAt > newestCapturedAt;

    if (!isRenderable(sample)) {
      if (advancesCursor) {
        pending.add(key);
        newest.set(key, capturedAt);
      }
      reconciled.push(sample);
      continue;
    }

    if (advancesCursor) {
      newest.set(key, capturedAt);
      if (pending.delete(key)) {
        reconciled.push(markEnergyHistorySegmentStart(sample));
        continue;
      }
    }

    reconciled.push(sample);
  }

  return {
    samples: reconciled,
    pendingMeterKeys: pending,
    newestCapturedAtByMeterKey: newest,
  };
}
