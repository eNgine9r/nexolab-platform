import {
  isEnergyHistoryBreakPending,
  markEnergyHistorySegmentStart,
} from "@/features/energy/energy-history-segment";
import { resolveEnergyMeter } from "@/features/energy/energy-telemetry";
import type { TelemetrySample } from "@/lib/telemetry/types";

export interface EnergyLiveHistoryReconciliation {
  samples: TelemetrySample[];
  pendingUnitIds: Set<number>;
  newestCapturedAtByUnitId: Map<number, number>;
}

export interface EnergyLiveHistorySeed {
  pendingUnitIds: Set<number>;
  newestCapturedAtByUnitId: Map<number, number>;
}

function isRenderable(sample: TelemetrySample): boolean {
  return sample.quality === "valid" && sample.value !== null && Number.isFinite(sample.value);
}

export function seedEnergyLiveHistoryState(
  samples: readonly TelemetrySample[],
): EnergyLiveHistorySeed {
  const latestByUnitId = new Map<number, { sample: TelemetrySample; capturedAt: number }>();

  for (const sample of samples) {
    const meter = resolveEnergyMeter(sample);
    const capturedAt = Date.parse(sample.captured_at);
    if (!meter || !Number.isFinite(capturedAt)) continue;

    const current = latestByUnitId.get(meter.unitId);
    if (current === undefined || capturedAt > current.capturedAt) {
      latestByUnitId.set(meter.unitId, { sample, capturedAt });
    }
  }

  const pendingUnitIds = new Set<number>();
  const newestCapturedAtByUnitId = new Map<number, number>();
  for (const [unitId, latest] of latestByUnitId) {
    newestCapturedAtByUnitId.set(unitId, latest.capturedAt);
    if (!isRenderable(latest.sample) || isEnergyHistoryBreakPending(latest.sample.event_id)) {
      pendingUnitIds.add(unitId);
    }
  }

  return { pendingUnitIds, newestCapturedAtByUnitId };
}

export function reconcileEnergyLiveHistory(
  samples: readonly TelemetrySample[],
  pendingUnitIds: ReadonlySet<number> = new Set(),
  newestCapturedAtByUnitId: ReadonlyMap<number, number> = new Map(),
): EnergyLiveHistoryReconciliation {
  const pending = new Set(pendingUnitIds);
  const newest = new Map(newestCapturedAtByUnitId);
  const reconciled: TelemetrySample[] = [];
  const sorted = [...samples].sort(
    (left, right) => Date.parse(left.captured_at) - Date.parse(right.captured_at),
  );

  for (const sample of sorted) {
    const meter = resolveEnergyMeter(sample);
    const capturedAt = Date.parse(sample.captured_at);
    if (!meter || !Number.isFinite(capturedAt)) continue;

    const newestCapturedAt = newest.get(meter.unitId);
    const advancesCursor = newestCapturedAt === undefined || capturedAt > newestCapturedAt;

    if (!isRenderable(sample)) {
      if (advancesCursor) {
        pending.add(meter.unitId);
        newest.set(meter.unitId, capturedAt);
      }
      reconciled.push(sample);
      continue;
    }

    if (advancesCursor) {
      newest.set(meter.unitId, capturedAt);
      if (pending.delete(meter.unitId)) {
        reconciled.push(markEnergyHistorySegmentStart(sample));
        continue;
      }
    }

    reconciled.push(sample);
  }

  return {
    samples: reconciled,
    pendingUnitIds: pending,
    newestCapturedAtByUnitId: newest,
  };
}
